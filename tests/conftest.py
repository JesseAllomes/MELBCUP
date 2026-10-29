"""Synthetic but schema-true payloads for a two-race Flemington card.

Field names follow the vendors' OpenAPI specs (.agent/api/). Vendor example payloads live in
tests/fixtures/ and are used for shape checks; these builders give complete, internally
consistent fields that the examples (truncated to two runners) cannot.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

RACE_DATE = date(2026, 11, 3)
VENUE = "Flemington"
FIXTURES = Path(__file__).parent / "fixtures"

# number, name, barrier, jockey, trainer, weight, last10, hcp
FIELDS = {
    1: [
        (1, "Swift Comet", 4, "J Kah", "C Waller", 58.5, "1x2311", 82),
        (2, "Red Harbour", 1, "J McDonald", "C Maher", 58.0, "21x412", 80),
        (3, "Quiet Thunder", 9, "D Lane", "C Waller", 57.0, "5x6789", 72),
        (4, "Lantern Bay", 6, "M Zahra", "G Waterhouse & A Bott", 56.5, "33x324", 76),
        (5, "Ocean Verse", 2, "B Melham", "C Maher", 55.0, "0x9087", 64),
        (6, "Harbour Lights", 11, "C Williams", "P Snowden", 54.0, "x41", 70),
    ],
    2: [
        (1, "Grand Tempo", 3, "J McDonald", "C Waller", 57.0, "1121x1", 100),
        (2, "Stone Circle", 8, "J Kah", "C Maher", 56.0, "3x2231", 96),
        (3, "Paper Moon", 5, "D Lane", "P Snowden", 55.0, "6x5412", 90),
        (4, "Night Patrol", 1, "M Zahra", "G Waterhouse & A Bott", 54.0, "7x8890", 84),
        (5, "Last Orders", 7, "B Melham", "C Maher", 53.0, "2x3243", 92),
    ],
}
DISTANCE = {1: 1200, 2: 3200}
# Two books per race, decimal win prices per runner number.
WIN_PRICES = {
    1: {
        "sportsbet": {1: 3.2, 2: 3.6, 3: 15.0, 4: 6.0, 5: 31.0, 6: 9.0},
        "tab": {1: 3.0, 2: 3.8, 3: 13.0, 4: 6.5, 5: 26.0, 6: 10.0},
    },
    2: {
        "sportsbet": {1: 2.6, 2: 4.2, 3: 8.0, 4: 21.0, 5: 6.0},
        "tab": {1: 2.5, 2: 4.6, 3: 7.5, 4: 19.0, 5: 6.5},
    },
}


def acceptances_payload() -> dict:
    races = []
    for n, field in FIELDS.items():
        races.append(
            {
                "race_number": n,
                "race_id": f"race-{n}",
                "race_name": "Lexus Melbourne Cup" if n == 2 else "Furphy Sprint",
                "start_time_local": "3:00PM" if n == 2 else "11:45AM",
                "distance_m": DISTANCE[n],
                "race_class": "Group 1" if n == 2 else "BenchMark 90",
                "prize_total": 10_000_000 if n == 2 else 200_000,
                "runners": [
                    {
                        "number": num,
                        "barrier": bar,
                        "runner_name": name,
                        "jockey": jockey,
                        "trainer": trainer,
                        "weight_kg": wt,
                        "last10": last10,
                        "hcp_rating": hcp,
                        "emergency": False,
                        "scratched": False,
                        "age": 5,
                        "sex": "gelding",
                        "owner": f"{trainer} Racing Syndicate",
                        "gear_changes": "Blinkers FIRST TIME" if num == 3 else None,
                        "last_start_date": "2026-10-17",
                    }
                    for num, name, bar, jockey, trainer, wt, last10, hcp in field
                ],
            }
        )
    return {
        "date": RACE_DATE.isoformat(),
        "meetings": [
            {
                "venue": VENUE,
                "track": {"rail": "True", "track_condition": "Good 4"},
                "races": races,
            }
        ],
    }


def pe_form_payload(race: int) -> dict:
    runners = []
    for num, name, bar, jockey, _trainer, wt, last10, _ in FIELDS[race]:
        digits = [c for c in last10 if c.isdigit()][-4:]
        runs = []
        for i, d in enumerate(reversed(digits)):
            pos = 10 if d == "0" else int(d)
            runs.append(
                {
                    "date": f"2026-10-{17 - 7 * i:02d}",
                    "venue": "Caulfield",
                    "distance_m": DISTANCE[race] - 200,
                    "track_condition": "Good (4)",
                    "position": pos,
                    "status": "ran",
                    "margin": "0.5L" if pos == 1 else f"{pos * 0.8:.1f}L",
                    "sp": 4.0 + pos,
                    "field_size": 14,
                    "weight_kg": wt,
                    "jockey": jockey,
                    "race_class": "Group 2",
                }
            )
        wins = sum(1 for d in digits if d == "1")
        top3 = sum(1 for d in digits if d in "123")
        runners.append(
            {
                "number": num,
                "name": name,
                "barrier": bar,
                "scratched": False,
                "stats": {"starts": len(digits), "wins": wins, "places": top3},
                "runs": runs,
            }
        )
    return {"race_number": race, "runners": runners}


def ntg_race(race: int, scratched: tuple[int, ...] = ()) -> dict:
    """One race as /v1/racing/next-to-go returns it: every book's win and place per runner."""
    books = WIN_PRICES[race]
    runners = []
    for num, name, *_ in FIELDS[race]:
        if num in scratched:
            continue
        runners.append(
            {
                "number": num,
                "name": name,
                "bookmakers": [
                    {
                        "key": key,
                        "win_price": prices[num],
                        "place_price": round(1 + (prices[num] - 1) / 4, 2),
                        "last_update": "2026-11-03T03:50:00Z",
                        "stale": False,
                    }
                    for key, prices in books.items()
                ],
            }
        )
    start = "2026-11-03T04:00:00Z" if race == 2 else "2026-11-03T00:45:00Z"
    return {
        "race_id": f"race-{race}",
        "venue": VENUE,
        "race_number": race,
        "start_time": start,
        "places_paid": 3,
        "scratchings": [{"number": n} for n in scratched],
        "runners": runners,
    }


def results_payload() -> list[dict]:
    """Every race finishes in saddlecloth order (1 wins, 2 second...), SP = Sportsbet price."""
    out = []
    for race, field in FIELDS.items():
        sp = WIN_PRICES[race]["sportsbet"]
        nums = [f[0] for f in field]
        out.append(
            {
                "venue": VENUE,
                "race_number": race,
                "start_time": ntg_race(race)["start_time"],
                "status": "final",
                "runners": [
                    {"number": n, "name": name, "position": i + 1, "status": "ran", "sp": sp[n]}
                    for i, (n, name, *_) in enumerate(field)
                ],
                "dividends": {
                    "straight": [
                        {
                            "number": n,
                            "position": i + 1,
                            "market": "PLC",
                            "product": "FIXED",
                            "amount": round(1 + (sp[n] - 1) / 4, 2),
                        }
                        for i, n in enumerate(nums[:3])
                    ],
                    "exotics": [
                        {"code": "TF", "selection": ",".join(map(str, nums[:3])), "amount": 60.0},
                        {"code": "FF", "selection": ",".join(map(str, nums[:4])), "amount": 400.0},
                    ],
                },
            }
        )
    return out


def ff_form_payload(race: int) -> dict:
    runners = []
    for num, name, *_ in FIELDS[race]:
        runners.append(
            {
                "number": num,
                "name": name,
                "scratched": False,
                "last20Starts": "x" + "".join(str((num + i) % 9 + 1) for i in range(12)),
                "stats": {
                    "overall": {"starts": 20, "wins": 6 - num, "seconds": 3, "thirds": 2},
                    "track": {"starts": 4, "wins": 1 if num < 3 else 0, "seconds": 1, "thirds": 0},
                    "distance": {"starts": 5, "wins": 1, "seconds": 1, "thirds": 1},
                    "conditions": {"good": {"starts": 12, "wins": 3, "seconds": 2, "thirds": 1}},
                    "firstUp": None,
                    "secondUp": {"starts": 3, "wins": 1, "seconds": 0, "thirds": 1},
                },
                "speedMap": {
                    "runningStyle": "leader" if num == 1 else "midfield",
                    "earlySpeedIndex": 9 - num,
                    "settlingPosition": float(num),
                },
                "classProfile": {"currentRating": 100 - num},
                "raceClassFit": {"classDifference": num - 3, "withinOptimalRange": num < 4},
                "decorators": [{"label": "Track specialist", "sentiment": "positive"}]
                if num == 2
                else [],
            }
        )
    return {"condition": "Good 4", "runners": runners}


def ff_predictions_payload(race: int) -> dict:
    n = len(FIELDS[race])
    weights = [n - i for i in range(n)]
    total = sum(weights)
    return {
        "predictions": [
            {
                "number": num,
                "winProb": round(w / total, 4),
                "placeProb": round(min(0.95, 3 * w / total), 4),
                "modelRank": i + 1,
            }
            for i, ((num, *_), w) in enumerate(zip(FIELDS[race], weights, strict=True))
        ]
    }


def ff_person_payload(name: str, role: str) -> dict:
    seed = sum(map(ord, name)) % 7
    return {
        f"{role}Name": name,
        "totalStarts": 500,
        "totalWins": 60 + seed * 5,
        "overallPlaceRate": 0.35,
        "trackStats": [{"venue": VENUE, "totalStarts": 80, "wins": 10 + seed, "places": 30}],
        "recentStats": {"totalStarts": 60, "totalWins": 8 + seed, "overallPlaceRate": 0.38},
        "conditionStats": [
            {"condition": "Good", "totalStarts": 400, "wins": 50 + seed, "places": 140},
            {"condition": "Soft", "totalStarts": 90, "wins": 9, "places": 30},
        ],
    }


def ff_bias_payload() -> dict:
    return {
        "barrierStats": [
            {"barrierNumber": b, "totalStarts": 200, "advantage": round(0.02 - 0.003 * b, 4)}
            for b in range(1, 17)
        ],
        "distanceStats": [],
    }


def rc_payload(query: str, variables: dict) -> dict:
    """racing.com's form service: one meeting, every runner a horse code, and past runs with a
    stewards' comment for each race's runner 1 (plus one run after race day, to be ignored)."""
    if "GetMeetingByVenueDateTrial" in query:
        return {"data": {"GetMeetingByVenueDateTrial": [{"id": "M1"}]}}
    if "getRaceForm" in query:
        race = variables["raceNumber"]
        entries = [
            {"raceEntryNumber": n, "horseCode": f"H{race}-{n}"} for n, *_ in FIELDS.get(race, [])
        ]
        return {"data": {"getRaceForm": {"formRaceEntries": entries}}}
    if "GetRaceEntryItemByHorsePaged" in query:
        horse = variables["horseCode"]
        note = "Slow to begin. Held up in the straight." if horse.endswith("-1") else None

        def run(day: str, finish: str, comment: str | None) -> dict:
            return {
                "finish": finish,
                "positionAtSettledAbv": "4th",
                "commentStewards": comment,
                "race": {
                    "date": day,
                    "isTrial": False,
                    "isJumpOut": False,
                    "venueAbbr": "FLEM",
                    "distance": "1600m",
                    "trackCondition": "Good 4",
                },
            }

        runs = [
            run("2026-11-10", "1", "After the meeting."),
            run("2026-10-17", "5", note),
            run("2026-09-26", "2", None),
            run("2026-09-01", "1", None) | {"race": {"date": "2026-09-01", "isTrial": True}},
        ]
        return {"data": {"GetRaceEntryItemByHorsePaged": runs}}
    return {"errors": [{"message": "unknown query"}], "data": None}


class Router:
    """httpx transport that answers from the builders above and counts calls per path."""

    def __init__(
        self, *, ff_tier: str = "pro", scratched: dict[int, tuple[int, ...]] | None = None
    ):
        self.ff_tier = ff_tier
        self.scratched = scratched or {}
        self.hits: dict[str, int] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        q = request.url.params
        self.hits[path] = self.hits.get(path, 0) + 1
        host = request.url.host
        if host == "api.puntersedge.online":
            spent = sum(v for k, v in self.hits.items() if k != "/v1/keys/info")
            credits = {"x-credits-remaining": str(3000 - 2 * spent), "x-credits-limit": "3000"}
            if path == "/v1/keys/info":
                return httpx.Response(200, json={"credits_remaining": 2999, "credits_limit": 3000})
            if path == "/v1/racing/acceptances":
                return httpx.Response(200, json=acceptances_payload(), headers=credits)
            if path == "/v1/racing/next-to-go":
                return httpx.Response(
                    200,
                    json=[ntg_race(n, self.scratched.get(n, ())) for n in FIELDS],
                    headers=credits,
                )
            if path == "/v1/racing/results":
                return httpx.Response(200, json=results_payload(), headers=credits)
            if path == "/v1/racing/form":
                return httpx.Response(
                    200, json=pe_form_payload(int(q["race_number"])), headers=credits
                )
        if host == "api.formfav.com":
            if path == "/v1/form":
                return httpx.Response(200, json=ff_form_payload(int(q["race"])))
            if self.ff_tier != "pro":
                return httpx.Response(403, json={"detail": "Pro tier required"})
            if path == "/v1/predictions":
                return httpx.Response(200, json=ff_predictions_payload(int(q["race"])))
            if path.startswith("/v1/stats/jockey/"):
                return httpx.Response(200, json=ff_person_payload(path.rsplit("/", 1)[1], "jockey"))
            if path.startswith("/v1/stats/trainer/"):
                return httpx.Response(
                    200, json=ff_person_payload(path.rsplit("/", 1)[1], "trainer")
                )
            if path.startswith("/v1/stats/track-bias/"):
                return httpx.Response(200, json=ff_bias_payload())
        if host == "graphql.rmdprod.racing.com":
            return httpx.Response(200, json=rc_payload(q["query"], json.loads(q["variables"])))
        return httpx.Response(404, json={"detail": f"no route {host}{path}"})


@pytest.fixture
def router() -> Router:
    return Router()


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())
