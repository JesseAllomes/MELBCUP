"""The Sports page's player-prop catalogue view: read, filter and page the ingestion's catalogue.

Reads catalogue/<sport>/index.json + comp-<competition_id>.json.gz shards (or, for a small or older
sport, latest.json.gz) and catalogue/coverage.json (contract: catalogue_format.md)
from blob container `nba` (managed identity, same as nba_feed) or, locally, from the folder named
by CATALOGUE_DIR. Everything offered is shown: filters and pages only narrow what is on screen,
and a sport's multi/challenge policy never hides a row (T51, T55, T56).
"""

import gzip
import json
import os
import time
from collections import OrderedDict
from collections.abc import Callable
from urllib.parse import urlencode

SPORT_KEYS = (
    "nba",
    "nbl",
    "ncaab",
    "nfl",
    "ncaaf",
    "afl",
    "aflw",
    "nrl",
    "rugby-league",
    "football",
    "nhl",
    "tennis",
    "cricket",
    "mlb",
    "rugby-union",
)
OTHER_KEYS = ("basketball-other", "american-football-other", "ice-hockey-other", "baseball-other")
GROUPS = {"other": OTHER_KEYS, "all": SPORT_KEYS + OTHER_KEYS}
PAGE_SIZE = 50
MAX_SHARDS_CACHED = 2  # a big sport is read one competition shard at a time
MAX_EVENT_OPTS = 200
TTL_S = 60.0
NO_FEED = "No player-prop feed connected for this sport"
FILTERS = ("q", "family", "event", "side", "period", "alt", "fresh", "model", "mapped")
MODELS = ("market-only", "model-validated", "model-experimental", "model-unavailable")
FRESH = {"fresh": "Fresh", "stale": "Stale", "unverified": "Unverified", "suspended": "Suspended"}

_cache: dict[str, tuple[float, object]] = {}
_shards: OrderedDict = OrderedDict()  # (sport, shard, built) -> rows, the last 2 only


def clear_cache() -> None:
    _cache.clear()
    _shards.clear()


def _read(name: str) -> bytes | None:
    root = os.environ.get("CATALOGUE_DIR")
    if root:
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            return None
        with open(path, "rb") as f:
            return f.read()
    account = os.environ.get("NBA_ACCOUNT")
    if account:
        from melbcup.nba_feed import blob_reader

        return blob_reader(account, os.environ.get("AZURE_CLIENT_ID"))(f"catalogue/{name}")
    return None


def _cached(key: str, build: Callable[[], object]):
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < TTL_S:
        return hit[1]
    try:
        val = build()
    except Exception:  # a broken or unreachable feed shows as "no feed", never as a 500
        val = None
    _cache[key] = (time.monotonic(), val)
    return val


def coverage() -> dict[str, dict]:
    """coverage.json rows by sport (the newest build per sport, summed over providers' counts)."""

    def build():
        raw = _read("coverage.json")
        out: dict[str, dict] = {}
        for row in json.loads(raw) if raw else []:
            cur = out.get(row.get("sport"))
            if cur is None:
                out[row["sport"]] = dict(row, providers=[row.get("provider")])
                continue
            for k in (
                "events",
                "raw_outcomes",
                "displayed_outcomes",
                "unmapped_groups",
                "mapped_groups",
                "raw_player_market_groups",
                "suspended_outcomes",
                "modelled_outcomes",
                "stale_outcomes",
            ):
                cur[k] = (cur.get(k) or 0) + (row.get(k) or 0)
            cur["providers"].append(row.get("provider"))
            cur["built"] = max(cur.get("built") or "", row.get("built") or "")
            if row.get("feed") == "connected":
                cur["feed"] = "connected"
            cur["adapter_errors"] = (cur.get("adapter_errors") or []) + (
                row.get("adapter_errors") or []
            )
        return out

    return _cached("coverage", build) or {}


def _sort_key(s: dict):
    return (
        s.get("event_start_utc") or "",
        str(s.get("event_id")),
        s.get("participant_name") or "",
        s.get("market_family") or "",
        s.get("market_name_raw") or "",
        s.get("period") or "",
        s.get("line_numeric") if isinstance(s.get("line_numeric"), int | float) else -1e9,
        str(s.get("side") or ""),
        str(s.get("key") or ""),
    )


def _index(sport: str) -> dict | None:
    """The small per-sport index (events, a row per competition). An older sport with only
    latest.json.gz gets one competition holding all its rows."""

    def build():
        raw = _read(f"{sport}/index.json")
        if raw is not None:
            return json.loads(raw)
        raw = _read(f"{sport}/latest.json.gz")
        if raw is None:
            return None
        doc = json.loads(gzip.decompress(raw))
        del raw
        rows = doc.get("selections", [])
        evs = doc.get("events", [])
        starts = [e.get("starts_at") for e in evs if e.get("starts_at")]
        comp = {
            "competition_id": "",
            "competition": "All",
            "events": len(evs),
            "first_start": min(starts, default=None),
            "outcomes": len(rows),
            "player_outcomes": sum(1 for r in rows if r.get("is_player_prop")),
            "families": sorted({r.get("market_family") or "other" for r in rows}),
            "periods": sorted({r.get("period") or "" for r in rows} - {""}),
            "shard": "latest.json.gz" if rows else None,
        }
        return {
            "built": doc.get("built"),
            "sport": sport,
            "rows": len(rows),
            "player_rows": comp["player_outcomes"],
            "events": evs,
            "competitions": [comp],
        }

    return _cached(f"index:{sport}", build)


def _units(sport: str) -> list[tuple[str, dict]]:
    """(sport key, competition row) of everything the tab covers, soonest-starting first."""
    out = []
    for k in GROUPS.get(sport) or (sport,):
        idx = _index(k)
        out += [(k, c) for c in (idx or {}).get("competitions", [])]
    out.sort(key=lambda u: (u[1].get("first_start") or "~", u[0], u[1]["competition_id"]))
    return out


def _shard(sport: str, comp: dict) -> list[dict]:
    """One competition's rows, annotated and sorted. At most MAX_SHARDS_CACHED stay in memory."""
    idx = _index(sport) or {}
    key = (sport, comp.get("shard"), idx.get("built"))
    hit = _shards.get(key)
    if hit is not None:
        _shards.move_to_end(key)
        return hit
    raw = _read(f"{sport}/{comp['shard']}")
    doc = json.loads(gzip.decompress(raw)) if raw else {}
    del raw
    names = {str(e["event_id"]): e.get("event_name") for e in doc.get("events", [])}
    rows = doc.get("selections", [])
    del doc
    for r in rows:
        r["sport"] = sport
        r["_ev"] = names.get(str(r.get("event_id"))) or str(r.get("event_id"))
    rows.sort(key=_sort_key)
    _shards[key] = rows
    while len(_shards) > MAX_SHARDS_CACHED:
        _shards.popitem(last=False)
    return rows


def is_alt(r: dict) -> bool:
    return "alt" in f"{r.get('market_subtype') or ''} {r.get('market_name_raw') or ''}".lower()


def flags(r: dict) -> list[tuple[str, str]]:
    """(css tone, label) chips for one selection."""
    out = []
    if r.get("model_status") == "market-only":
        out.append(("muted", "market-only"))
    if r.get("model_status") == "model-experimental":
        out.append(("warn", "model-experimental"))
    if r.get("quote_status") in ("stale", "unverified"):
        out.append(("warn", "stale" if r["quote_status"] == "stale" else "unverified"))
    if r.get("suspended"):
        out.append(("bad", "suspended"))
    if not r.get("mapped", True):
        out.append(("warn", "unmapped"))
    if r.get("eligible_for_multis") is False:
        out.append(("muted", "not-combinable"))
    elif r.get("eligible_for_multis") is None:
        out.append(("muted", "terms-unknown"))
    return out


def _fresh_of(r: dict) -> str:
    return "suspended" if r.get("suspended") else (r.get("quote_status") or "unverified")


def _match(r: dict, f: dict[str, str]) -> bool:
    q = f["q"].lower()
    if q:
        hay = " ".join(
            str(r.get(k) or "")
            for k in (
                "participant_name",
                "_ev",
                "market_name_raw",
                "market_family",
                "stat_key",
                "bookmaker",
                "line_raw",
            )
        ).lower()
        if not all(w in hay for w in q.split()):
            return False
    if f["family"] and (r.get("market_family") or "other") != f["family"]:
        return False
    if (
        f["event"]
        and f["event"] != f"{r['sport']}:{r['event_id']}"
        and f["event"] != str(r["event_id"])
    ):
        return False
    if f["side"] and (r.get("side") or "").lower() != f["side"]:
        return False
    if f["period"] and (r.get("period") or "") != f["period"]:
        return False
    if f["alt"] and not is_alt(r):
        return False
    if f["fresh"] and _fresh_of(r) != f["fresh"]:
        return False
    if f["model"] and r.get("model_status") != f["model"]:
        return False
    if f["mapped"] == "mapped" and not r.get("mapped", True):
        return False
    return not (f["mapped"] == "unmapped" and r.get("mapped", True))


def _qs(sport: str, view: str, f: dict[str, str], page: int | None = None, comp: str = "") -> str:
    p = {"sport": sport, "tab": "all", "view": view, **{k: v for k, v in f.items() if v}}
    if comp:
        p["comp"] = comp
    if page and page > 1:
        p["page"] = str(page)
    return "/sports?" + urlencode(p)


def _offered(c: dict, view: str) -> int:
    return c.get("player_outcomes" if view == "players" else "outcomes") or 0


def _comp_label(sport: str, k: str, c: dict) -> str:
    return (c.get("competition") or "All") + (f" ({k})" if sport in ("all", "other") else "")


def _scope(sport: str, view: str, units, f, explicit: str):
    """(units to read, selected picker value or None when there is no picker)."""
    live = [u for u in units if _offered(u[1], view)]
    if f["event"]:  # an event filter reads only the competition(s) holding that event
        ev = f["event"].split(":", 1)[-1]
        hold = [
            u
            for u in live
            if any(
                str(e.get("event_id")) == ev
                and str(e.get("competition_id") or "") == u[1]["competition_id"]
                for e in (_index(u[0]) or {}).get("events", [])
            )
        ]
        live = hold or live
    if sport == "all" or len(units) < 2:
        return live, None
    if explicit == "all" or (not explicit and any(f.values())):
        return live, "all"
    pick = next((u for u in live if f"{u[0]}:{u[1]['competition_id']}" == explicit), None)
    pick = pick or (live[0] if live else None)  # default: the soonest-starting competition
    return ([pick] if pick else []), (f"{pick[0]}:{pick[1]['competition_id']}" if pick else "all")


def query(sport: str, view: str, params) -> dict:
    """Everything the template needs: filtered rows of the requested page, counts, facets, links.

    view "players" keeps player props only; "markets" keeps every selection. Competition shards
    are read one at a time; across several, reading stops once the page is filled."""
    f = {k: (params.get(k) or "").strip()[:80] for k in FILTERS}
    if f["alt"] not in ("1", ""):
        f["alt"] = ""
    explicit = (params.get("comp") or "").strip()[:80]
    try:
        page = max(1, int(params.get("page") or 1))
    except ValueError:
        page = 1
    cov = coverage()
    units = _units(sport)
    keys = GROUPS.get(sport) or (sport,)
    c = (
        _all_coverage({k: v for k, v in cov.items() if k in keys})
        if sport in GROUPS
        else cov.get(sport)
    )
    out = {
        "sport": sport,
        "view": view,
        "f": f,
        "cov": c,
        "feed": bool(units) and (c is None or c.get("feed") != "none"),
        "no_feed": NO_FEED,
        "built": max([(_index(k) or {}).get("built") or "" for k in keys] or [""])
        or (c or {}).get("built"),
        "rows": [],
        "groups": [],
        "total": 0,
        "all_total": 0,
        "page": 1,
        "pages": 1,
        "page_size": PAGE_SIZE,
        "fresh_opts": FRESH,
        "model_opts": MODELS,
        "comp_opts": [],
        "comp": "",
        "partial": False,
        "shard_counts": [],
    }
    if not units:
        return out
    out["n_props"] = sum((_index(k) or {}).get("player_rows") or 0 for k in keys)
    out["n_rows"] = sum((_index(k) or {}).get("rows") or 0 for k in keys)
    scope, picked = _scope(sport, view, units, f, explicit)
    if picked is not None:
        out["comp"] = picked
        out["comp_opts"] = [("all", "All competitions")] + [
            (
                f"{k}:{c['competition_id']}",
                f"{_comp_label(sport, k, c)} · {_offered(c, view)} outcomes",
            )
            for k, c in units
            if _offered(c, view)
        ]
    out["all_total"] = sum(_offered(c, view) for _, c in scope)
    need = (page - 1) * PAGE_SIZE + PAGE_SIZE + 1  # one extra row tells there is a next page
    hits: list[dict] = []
    broke = False
    for i, (k, comp) in enumerate(scope):
        n = 0
        for r in _shard(k, comp):
            if view == "players" and not r.get("is_player_prop"):
                continue
            if not _match(r, f):
                continue
            n += 1
            if len(hits) < need:
                hits.append(r)
        out["shard_counts"].append((k, comp["competition"], n))
        if len(hits) >= need and i + 1 < len(scope):
            broke = True  # shards left unread: counts are "at least"
            break
    total = None if broke else sum(n for _, _, n in out["shard_counts"])
    if total is not None:
        pages = max(1, -(-total // PAGE_SIZE))
        page = min(page, pages)
    rows = hits[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
    has_next = page < pages if total is not None else len(hits) > page * PAGE_SIZE
    if total is None:
        pages = page + 1 if has_next else page
    fam = {x for _, c in scope for x in c.get("families") or []}
    per = {x for _, c in scope for x in c.get("periods") or []}
    evs = OrderedDict()
    shown = {(k, c["competition_id"]) for k, c in scope}
    for k in dict.fromkeys(k for k, _ in scope):
        for e in sorted(
            (_index(k) or {}).get("events", []), key=lambda e: e.get("starts_at") or ""
        ):
            if (k, str(e.get("competition_id") or "")) in shown and len(evs) < MAX_EVENT_OPTS:
                evs.setdefault(
                    f"{k}:{e['event_id']}" if sport in GROUPS else str(e["event_id"]),
                    e.get("event_name"),
                )
    qc = out["comp"] if out["comp"] and explicit else ""
    out.update(
        rows=rows,
        total=total if total is not None else len(hits),
        all_total=out["all_total"],
        page=page,
        pages=pages,
        partial=total is None,
        first=(page - 1) * PAGE_SIZE + 1 if rows else 0,
        last=(page - 1) * PAGE_SIZE + len(rows),
        families=sorted(fam),
        periods=sorted(per),
        events=list(evs.items()),
        sports=sorted({k for k, _ in scope}),
        groups=_group(rows),
        link_next=_qs(sport, view, f, page + 1, qc) if has_next else "",
        link_prev=_qs(sport, view, f, page - 1, qc) if page > 1 else "",
        link_first=_qs(sport, view, f, 1, qc),
        link_last=_qs(sport, view, f, pages, qc) if total is not None else "",
        link_clear=_qs(sport, view, {}),
    )
    return out


def _group(rows: list[dict]) -> list[dict]:
    """event -> player -> market family -> rows, in the rows' order."""
    evs: OrderedDict = OrderedDict()
    for r in rows:
        ev = evs.setdefault(
            (r["sport"], r["event_id"]),
            {
                "sport": r["sport"],
                "name": r["_ev"],
                "start": r.get("event_start_utc"),
                "players": OrderedDict(),
            },
        )
        who = r.get("participant_name") or "No player named"
        pl = ev["players"].setdefault(
            (r.get("participant_id"), who), {"name": who, "fams": OrderedDict()}
        )
        fam = (r.get("market_family") or "other") if r.get("mapped", True) else "Other / Unmapped"
        pl["fams"].setdefault(fam, []).append(r)
    return [
        {
            **e,
            "players": [
                {
                    "name": p["name"],
                    "n": sum(len(v) for v in p["fams"].values()),
                    "fams": list(p["fams"].items()),
                }
                for p in e["players"].values()
            ],
        }
        for e in evs.values()
    ]


def _all_coverage(cov: dict[str, dict]) -> dict | None:
    rows = [v for v in cov.values() if v.get("feed") == "connected"]
    if not rows:
        return None
    return {
        "feed": "connected",
        "events": sum(v.get("events") or 0 for v in rows),
        "displayed_outcomes": sum(v.get("displayed_outcomes") or 0 for v in rows),
        "raw_outcomes": sum(v.get("raw_outcomes") or 0 for v in rows),
        "unmapped_groups": sum(v.get("unmapped_groups") or 0 for v in rows),
        "built": max(v.get("built") or "" for v in rows),
        "n_sports": len(rows),
    }


def coverage_line(sport: str) -> dict | None:
    """The coverage.json row for one sport, or None (no feed): events, outcomes, unmapped, built."""
    c = coverage().get(sport)
    return c if c and c.get("feed") == "connected" else None
