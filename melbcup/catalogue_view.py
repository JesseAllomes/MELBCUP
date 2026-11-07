"""The Sports page's player-prop catalogue view: read, filter and page the ingestion's catalogue.

Reads catalogue/<sport>/latest.json.gz and catalogue/coverage.json (contract: catalogue_format.md)
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
PAGE_SIZE = 50
TTL_S = 60.0
NO_FEED = "No player-prop feed connected for this sport"
FILTERS = ("q", "family", "event", "side", "period", "alt", "fresh", "model", "mapped")
MODELS = ("market-only", "model-validated", "model-experimental", "model-unavailable")
FRESH = {"fresh": "Fresh", "stale": "Stale", "unverified": "Unverified", "suspended": "Suspended"}

_cache: dict[str, tuple[float, object]] = {}


def clear_cache() -> None:
    _cache.clear()


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


def _load_one(sport: str) -> dict | None:
    def build():
        raw = _read(f"{sport}/latest.json.gz")
        if raw is None:
            return None
        doc = json.loads(gzip.decompress(raw))
        events = {str(e["event_id"]): e for e in doc.get("events", [])}
        rows = doc.get("selections", [])
        for r in rows:
            r["sport"] = sport
            r["_ev"] = (events.get(str(r.get("event_id"))) or {}).get("event_name") or str(
                r.get("event_id")
            )
        rows.sort(key=_sort_key)
        return {"built": doc.get("built"), "events": events, "rows": rows}

    return _cached(f"sport:{sport}", build)


def load(sport: str) -> dict | None:
    """{"built", "events", "rows"} for one sport, or for "all" the union of every sport; None if
    nothing is readable."""
    if sport != "all":
        return _load_one(sport)
    parts = [(k, _load_one(k)) for k in SPORT_KEYS]
    parts = [(k, d) for k, d in parts if d]
    if not parts:
        return None
    rows = [r for _, d in parts for r in d["rows"]]
    rows.sort(key=lambda r: (_sort_key(r)[0], r["sport"]) + _sort_key(r)[1:])
    events = {f"{k}:{i}": e for k, d in parts for i, e in d["events"].items()}
    return {"built": max(d["built"] or "" for _, d in parts), "events": events, "rows": rows}


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


def _facet(rows: list[dict], key: str) -> list[str]:
    return sorted(
        {(r.get(key) or ("other" if key == "market_family" else "")) for r in rows} - {""}
    )


def _qs(sport: str, view: str, f: dict[str, str], page: int | None = None) -> str:
    p = {"sport": sport, "view": view, **{k: v for k, v in f.items() if v}}
    if page and page > 1:
        p["page"] = str(page)
    return "/sports?" + urlencode(p)


def query(sport: str, view: str, params) -> dict:
    """Everything the template needs: filtered rows of the requested page, counts, facets, links.

    view "players" keeps player props only; "markets" keeps every selection."""
    f = {k: (params.get(k) or "").strip()[:80] for k in FILTERS}
    if f["alt"] not in ("1", ""):
        f["alt"] = ""
    try:
        page = max(1, int(params.get("page") or 1))
    except ValueError:
        page = 1
    cov = coverage()
    data = load(sport)
    c = cov.get(sport) if sport != "all" else _all_coverage(cov)
    out = {
        "sport": sport,
        "view": view,
        "f": f,
        "cov": c,
        "feed": bool(data) and (c is None or c.get("feed") != "none"),
        "no_feed": NO_FEED,
        "built": (data or {}).get("built") or (c or {}).get("built"),
        "rows": [],
        "groups": [],
        "total": 0,
        "all_total": 0,
        "page": 1,
        "pages": 1,
        "page_size": PAGE_SIZE,
        "fresh_opts": FRESH,
        "model_opts": MODELS,
    }
    if not data:
        return out
    out["n_props"] = sum(1 for r in data["rows"] if r.get("is_player_prop"))
    out["n_rows"] = len(data["rows"])
    base = [r for r in data["rows"] if view != "players" or r.get("is_player_prop")]
    hit = [r for r in base if _match(r, f)]
    pages = max(1, -(-len(hit) // PAGE_SIZE))
    page = min(page, pages)
    rows = hit[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
    evs = OrderedDict()
    for r in base:
        evs.setdefault(
            f"{r['sport']}:{r['event_id']}" if sport == "all" else str(r["event_id"]), r["_ev"]
        )
    out.update(
        rows=rows,
        total=len(hit),
        all_total=len(base),
        page=page,
        pages=pages,
        first=(page - 1) * PAGE_SIZE + 1 if hit else 0,
        last=(page - 1) * PAGE_SIZE + len(rows),
        families=_facet(base, "market_family"),
        periods=_facet(base, "period"),
        events=list(evs.items()),
        sports=sorted({r["sport"] for r in base}),
        groups=_group(rows),
        link_next=_qs(sport, view, f, page + 1) if page < pages else "",
        link_prev=_qs(sport, view, f, page - 1) if page > 1 else "",
        link_first=_qs(sport, view, f, 1),
        link_last=_qs(sport, view, f, pages),
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
