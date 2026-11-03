"""NBA feed probe (owner, 2026-11-03): which agencies' public web feeds answer, and do they
carry player props? Read-only GETs, one per URL, short timeout; returns a small JSON-able report.
No parsing beyond counting tell-tale words, so a changed feed shape cannot break it.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"
PROBES = {
    "tab_nba": "https://api.beta.tab.com.au/v1/tab-info-service/sports/Basketball/competitions/NBA?jurisdiction=VIC",
    "sportsbet_nba": "https://www.sportsbet.com.au/apigw/sportsbook-sports/Sportsbook/Sports/Competitions/6927?displayType=default&includeTopMarkets=true",
    "pointsbet_nba": "https://api.au.pointsbet.com/api/v2/competitions/7176/events/featured?includeLive=false",
    "ladbrokes_sports": "https://api.ladbrokes.com.au/v2/sport/event-request?category_ids=%5B%223c34d075-dc14-436d-bfc4-9272a49c2b39%22%5D",
    "neds_sports": "https://api.neds.com.au/v2/sport/event-request?category_ids=%5B%223c34d075-dc14-436d-bfc4-9272a49c2b39%22%5D",
    "nba_scoreboard": "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json",
    "nba_schedule": "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json",
    "nba_stats_gamelog": "https://stats.nba.com/stats/leaguegamelog?Counter=0&Direction=DESC&LeagueID=00&PlayerOrTeam=P&Season=2026-27&SeasonType=Regular%20Season&Sorter=DATE",
}
WORDS = (
    "player",
    "points",
    "rebounds",
    "assists",
    "Points",
    "Rebounds",
    "Assists",
    "Threes",
    "To Score",
)
TIMEOUT_S = 12


def probe_one(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/json",
            "Referer": "https://www.nba.com/",
            "Origin": "https://www.nba.com",
        },
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            body = resp.read(3_000_000)
            text = body.decode("utf-8", "replace")
            return {
                "status": resp.status,
                "bytes": len(body),
                "ms": round((time.monotonic() - t0) * 1000),
                "words": {w: text.count(w) for w in WORDS if w in text},
                "head": text[:300],
            }
    except urllib.error.HTTPError as e:
        return {"status": e.code, "error": "HTTP", "ms": round((time.monotonic() - t0) * 1000)}
    except Exception as e:  # timeouts, TLS, DNS
        return {
            "status": None,
            "error": type(e).__name__,
            "ms": round((time.monotonic() - t0) * 1000),
        }


def run() -> dict:
    return {name: probe_one(url) for name, url in PROBES.items()}


if __name__ == "__main__":
    import json

    for k, v in run().items():
        print(k, json.dumps({x: v.get(x) for x in ("status", "bytes", "ms", "error", "words")}))
