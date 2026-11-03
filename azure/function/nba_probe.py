"""NBA feed probe (owner, 2026-11-03): which agencies' public web feeds answer from
Australia, and do they carry player props? Read-only GETs with a short timeout. Each answer is
summarised (status, size, tell-tale word counts) and its body kept, so the feed shapes can be
read offline. A second pass follows the first Sportsbet NBA game into its markets.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"
SB = "https://www.sportsbet.com.au/apigw/sportsbook-sports/Sportsbook/Sports"
PROBES = {
    "sportsbet_nba": f"{SB}/Competitions/6927?displayType=default&includeTopMarkets=true",
    "pointsbet_comp_v2": "https://api.au.pointsbet.com/api/v2/competitions/7176/events/featured?includeLive=false&page=1",
    "pointsbet_mes_v3": "https://api.au.pointsbet.com/api/mes/v3/events/featured/competition/7176?page=1",
    "pointsbet_sports": "https://api.au.pointsbet.com/api/v2/sports/basketball/competitions",
    "tab_nba_nsw": "https://api.beta.tab.com.au/v1/tab-info-service/sports/Basketball/competitions/NBA?jurisdiction=NSW",
    "tab_sports": "https://api.beta.tab.com.au/v1/tab-info-service/sports?jurisdiction=NSW",
    "ladbrokes_categories": "https://api.ladbrokes.com.au/v2/sport/categories",
    "ladbrokes_events": "https://api.ladbrokes.com.au/v2/sport/event-request",
    "neds_categories": "https://api.neds.com.au/v2/sport/categories",
    "nba_scoreboard": "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json",
}
SB_EVENT_PATHS = (
    "/Events/{id}/Markets",
    "/Events/{id}/MarketGroupings",
    "/Events/{id}/SportCard?displayWithCard=true",
)
WORDS = ("player", "Points", "Rebounds", "Assists", "Threes", "To Score", "Player Points")
TIMEOUT_S = 4  # 13 probes worst case stays under the 60 s function timeout
KEEP_BYTES = 400_000


def probe_one(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Accept": "application/json", "Referer": "https://www.nba.com/"},
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            body = resp.read(3_000_000)
            text = body.decode("utf-8", "replace")
            return {
                "url": url,
                "status": resp.status,
                "bytes": len(body),
                "ms": round((time.monotonic() - t0) * 1000),
                "words": {w: text.count(w) for w in WORDS if w in text},
                "head": text[:300],
                "body": text[:KEEP_BYTES],
            }
    except urllib.error.HTTPError as e:
        return {
            "url": url,
            "status": e.code,
            "error": "HTTP",
            "ms": round((time.monotonic() - t0) * 1000),
        }
    except Exception as e:  # timeouts, TLS, DNS
        return {
            "url": url,
            "status": None,
            "error": type(e).__name__,
            "ms": round((time.monotonic() - t0) * 1000),
        }


def first_sportsbet_event(text: str) -> int | None:
    try:
        data = json.loads(text)
    except ValueError:
        return None
    found = re.search(r'"(?:eventId|id)"\s*:\s*(\d{6,})', json.dumps(data.get("events", data)))
    return int(found.group(1)) if found else None


def run() -> dict:
    out = {name: probe_one(url) for name, url in PROBES.items()}
    event = first_sportsbet_event(out["sportsbet_nba"].get("body", ""))
    if event:
        for n, path in enumerate(SB_EVENT_PATHS):
            out[f"sportsbet_event_{n}"] = probe_one(SB + path.format(id=event))
    return out


if __name__ == "__main__":
    for k, v in run().items():
        print(k, json.dumps({x: v.get(x) for x in ("status", "bytes", "ms", "error", "words")}))
