"""NBA player-prop prices from PointsBet's public feed, for the value test (owner, 2026-11-03).

Token-free and read-only. Each run lists the NBA games, fetches each game's markets, keeps the
player markets (points, rebounds, assists, threes, ...) and the game lines, and writes a game's
snapshot to the `nba-props` container only when a price changed:
<UTC date>/<event key>/<HHMMSS>.json.gz, with last.sha beside it.
"""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import time
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

try:
    import nba_challenge  # the deployed package: copied from melbcup/nba_challenge.py
except ImportError:  # the repository (tests)
    from melbcup import nba_challenge
try:
    import nba_legs  # the deployed package: copied from melbcup/nba_legs.py by azure-deploy.yml
except ImportError:  # the repository (tests)
    from melbcup import nba_legs

NY = ZoneInfo("America/New_York")
PB = "https://api.au.pointsbet.com/api/mes/v3"
NBA = "7176"
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"
TIMEOUT_S = 8
MAX_GAMES = 20
ESPN_INJURIES = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
INJURY_TIMEOUT_S = 5


def get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return json.loads(resp.read())


def slim_market(m: dict) -> dict:
    return {
        "key": m.get("key"),
        "name": m.get("name"),
        "class": m.get("eventClass"),
        "group": m.get("groupName"),
        "outcomes": [
            {
                k: o.get(k)
                for k in ("name", "price", "points", "playerId", "side", "teamId", "unitType")
            }
            for o in m.get("outcomes") or []
            if o.get("isOpenForBetting", True)
        ],
    }


def collect(
    container, now: dt.datetime, budget_s: float = 45.0, keep: list | None = None
) -> tuple[int, int]:
    """Save changed game snapshots. Returns (games seen, snapshots written); every snapshot fetched
    (changed or not) is appended to `keep` when given, for the legs step."""
    deadline = time.monotonic() + budget_s
    listing = get(f"{PB}/events/featured/competition/{NBA}?page=1")
    events = [e for e in listing.get("events", []) if not e.get("isLive")][:MAX_GAMES]
    written = 0
    for e in events:
        if time.monotonic() > deadline:
            break
        key = str(e["key"])
        full = get(f"{PB}/events/{urllib.parse.quote(key)}")
        markets = (full.get("fixedOddsMarkets") or []) + (full.get("specialFixedOddsMarkets") or [])
        snap = {
            "event": key,
            "name": e.get("name"),
            "startsAt": e.get("startsAt"),
            "markets": [slim_market(m) for m in markets],
        }
        if keep is not None:
            keep.append(snap)
        digest = hashlib.sha256(json.dumps(snap, sort_keys=True).encode()).hexdigest()
        base = f"{now:%Y-%m-%d}/{key}"
        last = container.get_blob_client(f"{base}/last.sha")
        try:
            if last.download_blob().readall().decode() == digest:
                continue
        except Exception:  # first sight of this game today
            pass
        body = gzip.compress(json.dumps(snap | {"fetchedAt": now.isoformat()}).encode())
        container.get_blob_client(f"{base}/{now:%H%M%S}.json.gz").upload_blob(body, overwrite=True)
        last.upload_blob(digest.encode(), overwrite=True)
        written += 1
    return len(events), written


def _events(snaps: list[dict]) -> list[dict]:
    return [
        {
            "event": s["event"],
            "name": s["name"],
            "startsAt": s.get("startsAt"),
            "markets": [
                {"group": m.get("group"), "outcomes": m.get("outcomes") or []} for m in s["markets"]
            ],
        }
        for s in snaps
    ]


VIEW_BUDGET_S = 40  # the Function stops at 60 s: Sportsbet is skipped if PointsBet took this long


def injuries(fetch=None) -> dict[str, str]:
    """{normalised player name: 'out' | 'doubtful' | 'questionable' | 'day-to-day'} from ESPN's
    injury list (the board's own endpoint). Any failure gives {}: the view is then unchanged."""
    try:
        if fetch is None:
            req = urllib.request.Request(ESPN_INJURIES, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=INJURY_TIMEOUT_S) as resp:
                data = json.loads(resp.read())
        else:
            data = fetch(ESPN_INJURIES)
        out: dict[str, str] = {}
        for t in data.get("injuries", []):
            for i in t.get("injuries", []):
                st = str(i.get("status", "")).lower()
                name = (i.get("athlete") or {}).get("displayName")
                if not name or not st:
                    continue
                out[nba_legs.norm(name)] = "out" if st.startswith("out") else st
        return out
    except Exception:
        return {}


def _outcome_player(o: dict) -> str | None:
    if "player" in o:
        return o["player"]
    hit = nba_legs.LEG.match(o.get("name") or "")
    return hit["who"] if hit else None


def drop_out(events: list[dict], inj: dict[str, str]) -> list[dict]:
    """The events without any outcome for a player marked Out."""
    if not any(v == "out" for v in inj.values()):
        return events
    res = []
    for e in events:
        ms = [
            m
            | {
                "outcomes": [
                    o
                    for o in m.get("outcomes") or []
                    if inj.get(nba_legs.norm(_outcome_player(o) or "")) != "out"
                ]
            }
            for m in e["markets"]
        ]
        res.append(e | {"markets": ms})
    return res


def mark_injuries(node, inj: dict[str, str]) -> None:
    """Set "injury" on every leg (any dict with player and stat) whose player is on the list."""
    if isinstance(node, dict):
        if "player" in node and "stat" in node:
            st = inj.get(nba_legs.norm(node["player"] or ""))
            if st and st != "out":
                node["injury"] = st
        for v in node.values():
            mark_injuries(v, inj)
    elif isinstance(node, list):
        for v in node:
            mark_injuries(v, inj)


LEG_KEYS = (
    "event", "game", "startsAt", "player", "team", "stat", "line", "under", "label",
    "price", "chance", "model", "market", "injury",
)  # fmt: skip


def log_leg(agency: str, g: dict, value: bool) -> dict:
    return {"agency": agency, "k": g["line"], "value": value} | {
        k: g[k] for k in LEG_KEYS if k in g
    }


def _multi_key(m: dict) -> tuple:
    return (m["kind"], m.get("target"), tuple(m["picks"]))


def _prod(xs) -> float:
    r = 1.0
    for x in xs:
        r *= x
    return r


def _slim_detail(g: dict) -> dict:
    return {k: g.get(k) for k in LEG_KEYS if k in g and k != "event"} | {
        "line": g["line"],
        "k": g["line"],
    }


def _slim_multi(m: dict) -> dict:
    return {
        "target": m.get("target"),
        "legs": m["legs"],
        "chance": m["chance"],
        "price": m["price"],
        "picks": m["picks"],
        "detail": [_slim_detail(d) for d in m["detail"]],
        "tip": m.get("tip", ""),
    }


def build_log(agency: str, rep: dict, prior: dict, now: dt.datetime) -> dict:
    """The day's log for one agency: the legs and suggested multis as last seen before tip. A game
    that has started drops out of the feed, so its legs (and multis starting on it) are carried
    forward from the prior log."""
    value = {(g["event"], g["label"]) for g in rep["value_legs"]}
    legs = [log_leg(agency, g, (g["event"], g["label"]) in value) for g in rep["all_legs"]]
    live = {g["event"] for g in legs}
    legs += [g for g in prior.get("legs", []) if g["event"] not in live]
    multis = []
    for kind, items in (("stacks", rep["stacks"]), ("stacks_same", rep["stacks_same"])):
        multis += [{"kind": kind, "agency": agency} | _slim_multi(m) for m in items]
    for grp in rep["by_game"]:
        multis.append(
            {
                "kind": "by_game",
                "agency": agency,
                "target": None,
                "legs": len(grp["legs"]),
                "chance": round(_prod(g["chance"] for g in grp["legs"]), 4),
                "price": round(_prod(g["price"] for g in grp["legs"]), 2),
                "picks": [g["label"] for g in grp["legs"]],
                "detail": [_slim_detail(g) for g in grp["legs"]],
                "tip": grp.get("startsAt") or "",
            }
        )
    have = {_multi_key(m) for m in multis}
    iso = now.isoformat()
    for m in prior.get("multis", []):
        if _multi_key(m) not in have and any(
            (d.get("startsAt") or "9") <= iso for d in m["detail"]
        ):
            multis.append(m)
    return {"agency": agency, "day": rep["day"], "loggedAt": iso, "legs": legs, "multis": multis}


def save_logs(nba, view: dict, now: dt.datetime) -> None:
    for code, a in view["agencies"].items():
        rep = a["report"]
        if not rep["all_legs"] or a.get("error"):
            continue  # nothing priced this round: keep the last good log
        name = f"{rep['day']}/log-{code}.json"
        try:
            prior = json.loads(nba.get_blob_client(name).download_blob().readall())
        except Exception:
            prior = {}
        nba.get_blob_client(name).upload_blob(
            json.dumps(build_log(code, rep, prior, now)).encode(), overwrite=True
        )


def build_view(nba, snaps: list[dict], now: dt.datetime, sb_fetch=None, inj_fetch=None) -> str:
    """Work out everything the NBA page shows, for both agencies, and save it gzipped as
    view-latest.json.gz: the web app (a quarter of a CPU) then only reads it, so its pages stay
    fast (owner, 2026-11-04). The board can be today's or the next game day's."""
    import gzip
    import time

    started = time.monotonic()
    try:
        board = json.loads(nba.get_blob_client("board-latest.json").download_blob().readall())
    except Exception:  # no board yet
        return "no board"
    xs = {n: nba_challenge.stage_x(10.0, 1000.0, n, True) for n in nba_challenge.STAGES}
    inj = injuries(inj_fetch) if time.monotonic() - started < VIEW_BUDGET_S / 2 else {}
    view = nba_legs.view(board, {"pb": drop_out(_events(snaps), inj)}, xs)
    sb_error = None
    if time.monotonic() - started < VIEW_BUDGET_S:
        try:
            sb_events = drop_out((sb_fetch or nba_legs.live_sportsbet)(), inj)
            sb = nba_legs.view(board, {"sb": sb_events}, xs)
            view["agencies"].update(sb["agencies"])
            view["preview"].update(sb["preview"])
        except Exception as exc:  # Sportsbet down: PointsBet still shows
            sb_error = f"Sportsbet did not answer ({type(exc).__name__})."
    else:
        sb_error = "Sportsbet skipped this round (time)."
    if sb_error:
        view["agencies"]["sb"] = {
            "report": nba_legs.report(board, []),
            "games": 0,
            "error": sb_error,
        }
    mark_injuries(view, inj)
    view["injuries"] = len([k for k, v in inj.items() if v == "out"])
    try:
        save_logs(nba, view, now)
    except Exception as exc:  # logging must never stop the page
        view["logError"] = type(exc).__name__
    view["pricedAt"] = now.isoformat()
    view["seconds"] = round(time.monotonic() - started, 1)
    nba.get_blob_client("view-latest.json.gz").upload_blob(
        gzip.compress(json.dumps(view).encode()), overwrite=True
    )
    return f"view {view['seconds']}s: " + ", ".join(
        f"{c} {len(a['report']['all_legs'])}" for c, a in view["agencies"].items()
    )


def price_legs(nba, snaps: list[dict], now: dt.datetime) -> str:
    """Turn this run's prices into legs and multis with the day's board (written each morning by the
    melbcup-nba job). Games that have started drop out of PointsBet's list, so their legs from the
    last run before tip-off are carried forward: settling needs every leg that was offered."""
    try:
        board = json.loads(nba.get_blob_client("board-latest.json").download_blob().readall())
    except Exception:  # no board yet
        return "no board"
    day = now.astimezone(NY).strftime("%Y%m%d")
    if board.get("day") != day:
        return f"board is for {board.get('day')}, not {day}"
    events = _events(snaps)
    res = nba_legs.report(board, events)
    try:
        prior = json.loads(nba.get_blob_client(f"{day}/legs.json").download_blob().readall())
    except Exception:  # first run of the day
        prior = {}
    now_events = {e["event"] for e in events}
    res["all_legs"] += [g for g in prior.get("all_legs", []) if g["event"] not in now_events]
    res["closed_value_legs"] = [
        g
        for g in prior.get("value_legs", []) + prior.get("closed_value_legs", [])
        if g["event"] not in now_events
    ]
    res["pricedAt"] = now.isoformat()
    body = json.dumps(res).encode()
    nba.get_blob_client(f"{day}/legs.json").upload_blob(body, overwrite=True)
    nba.get_blob_client("legs-latest.json").upload_blob(body, overwrite=True)
    return f"{day}: {res['legs_seen']} legs, {len(res['value_legs'])} value, {res['verdict']}"
