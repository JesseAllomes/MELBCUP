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
            {k: o.get(k) for k in ("name", "price", "points", "playerId", "side", "teamId")}
            for o in m.get("outcomes") or []
            if o.get("isOpenForBetting", True)
        ],
    }


def collect(container, now: dt.datetime, budget_s: float = 45.0) -> tuple[int, int]:
    """Save changed game snapshots. Returns (games seen, snapshots written)."""
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
