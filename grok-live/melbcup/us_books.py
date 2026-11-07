"""US bookmakers' NBA player over/unders (DraftKings, FanDuel and others) from The Odds API, in the
shape melbcup/nba_legs.legs_from reads (owner, 2026-11-06: pulled on request, never on a timer;
about 4 credits a game). Shared by the web app and tools/nba/books_test.py."""

from __future__ import annotations

import datetime as dt
import json
import math
import urllib.request

LAST: dict = {}  # the last answer's headers: credits left


ODDS = "https://api.the-odds-api.com/v4/sports/basketball_nba"
MARKETS = {
    "player_points": "points",
    "player_rebounds": "reboundsTotal",
    "player_assists": "assists",
    "player_threes": "threePointersMade",
}
TEAM = {"Los Angeles Clippers": "LA Clippers"}  # the Odds API name -> ESPN's


def _get(url: str):
    with urllib.request.urlopen(url, timeout=30) as r:
        left = r.headers.get("x-requests-remaining")
        if left is not None:
            LAST["remaining"] = int(float(left))
        return json.loads(r.read())


def outcomes(bookmaker: dict) -> list[dict]:
    """One bookmaker's player over/unders in legs_from's parsed shape (whole-number lines skipped:
    they can push)."""
    out = []
    for m in bookmaker.get("markets", []):
        stat = MARKETS.get(m.get("key"))
        for o in m.get("outcomes", []):
            point = o.get("point")
            if stat is None or point is None or float(point).is_integer() or not o.get("price"):
                continue
            out.append(
                {
                    "name": f"{o.get('description')} {o.get('name')} {point} {stat}",
                    "player": o.get("description") or "",
                    "stat": stat,
                    "k": math.floor(point) + 1,
                    "under": o.get("name") == "Under",
                    "price": float(o["price"]),
                }
            )
    return out


def us_books(key: str, hours: float = 36) -> dict:
    """{book: [event]} for NBA games starting within `hours`."""
    now = dt.datetime.now(dt.UTC)
    books: dict = {}
    for e in _get(f"{ODDS}/events?apiKey={key}"):
        start = dt.datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00"))
        if not now < start < now + dt.timedelta(hours=hours):
            continue
        d = _get(
            f"{ODDS}/events/{e['id']}/odds?apiKey={key}&regions=us"
            f"&markets={','.join(MARKETS)}&oddsFormat=decimal"
        )
        away, home = (TEAM.get(e[t], e[t]) for t in ("away_team", "home_team"))
        name = f"{away} @ {home}"
        for b in d.get("bookmakers", []):
            books.setdefault(b["key"], []).append(
                {
                    "event": e["id"],
                    "name": name,
                    "startsAt": e["commence_time"],
                    "markets": [{"group": b["key"], "outcomes": outcomes(b)}],
                }
            )
    return books


