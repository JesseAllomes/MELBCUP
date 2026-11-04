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


def build_view(nba, snaps: list[dict], now: dt.datetime, sb_fetch=None) -> str:
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
    view = nba_legs.view(board, {"pb": _events(snaps)}, xs)
    sb_error = None
    if time.monotonic() - started < VIEW_BUDGET_S:
        try:
            sb = nba_legs.view(board, {"sb": (sb_fetch or nba_legs.live_sportsbet)()}, xs)
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
