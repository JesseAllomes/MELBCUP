"""Synthetic but schema-true payloads for a two-race Flemington card (eight runners each).

racing.com carries the card, the prices and the results. The prices are real: tests/fixtures/
rc_market.json holds trimmed ``GetBettingData`` replies recorded by tools/live_collector.py
(Sportsbet, Ladbrokes, PointsBet and bet365 fixed odds per runner), served for the two races
here with only the start time moved to Cup day. The rest are synthetic builders that give
complete, internally consistent fields for the two races.
"""

from __future__ import annotations

import copy
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
        (7, "Copper Reef", 3, "C Williams", "C Waller", 53.5, "4x5566", 68),
        (8, "Silver Quay", 10, "B Melham", "P Snowden", 53.0, "x7890", 62),
    ],
    2: [
        (1, "Grand Tempo", 3, "J McDonald", "C Waller", 57.0, "1121x1", 100),
        (2, "Stone Circle", 8, "J Kah", "C Maher", 56.0, "3x2231", 96),
        (3, "Paper Moon", 5, "D Lane", "P Snowden", 55.0, "6x5412", 90),
        (4, "Night Patrol", 1, "M Zahra", "G Waterhouse & A Bott", 54.0, "7x8890", 84),
        (5, "Last Orders", 7, "B Melham", "C Maher", 53.0, "2x3243", 92),
        (6, "Winter Gale", 2, "M Zahra", "C Waller", 52.5, "3x4455", 88),
        (7, "Iron Lantern", 4, "C Williams", "C Maher", 52.0, "8x7654", 86),
        (8, "Harbour Master", 6, "D Lane", "G Waterhouse & A Bott", 51.5, "5x6677", 82),
    ],
}
DISTANCE = {1: 1200, 2: 3200}
START_UTC = {1: "2026-11-03T00:45:00.000Z", 2: "2026-11-03T04:00:00.000Z"}
# Race names for the card (racing.com sends them upper-case sometimes; these are plain).
NAMES = {1: "Furphy Sprint", 2: "Lexus Melbourne Cup"}
CLASSES = {1: "BenchMark 90", 2: "Group 1"}


def rc_market(race: int, scratched: tuple[int, ...] = ()) -> dict:
    """One race's ``GetBettingData`` reply: the recorded racing.com market, start time moved
    to Cup day, and any runners in ``scratched`` marked as scratched."""
    data = copy.deepcopy(load_fixture("rc_market")[f"race{race}"]["data"])
    betting = data["GetBettingData"]
    betting["time"] = betting["officialTime"] = START_UTC[race]
    for e in betting["formRaceEntries"]:
        e["scratched"] = e["scratched"] or e["raceEntryNumber"] in scratched
    return data


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


def rc_payload(
    query: str, variables: dict, scratched: dict[int, tuple[int, ...]] | None = None
) -> dict:
    """racing.com's data service: the meeting list, one meeting with its races and fields,
    prices (the recorded market), results, and past runs with a stewards' comment for each
    race's runner 1 (plus one run after race day, to be ignored)."""
    if "GetMeetingByVenueDateTrial" in query:
        return {"data": {"GetMeetingByVenueDateTrial": [{"id": "M1"}]}}
    if "GetRaceMeetingsByStateNew" in query:
        rows = [
            {
                "id": "M1",
                "venue": VENUE,
                "date": f"{RACE_DATE.isoformat()}T00:00:00",
                "state": "VIC",
                "isTrial": False,
                "isJumpOut": False,
            }
        ]
        return {"data": {"GetRaceMeetingsByStateNew": rows if variables["states"] == "VIC" else []}}
    if "getRacesForMeet" in query:
        return {
            "data": {
                "getRacesForMeet": [
                    {
                        "raceNumber": n,
                        "raceStatus": "FinalFields",
                        "time": START_UTC[n],
                        "trackCondition": "Good 4",
                        "name": NAMES[n],
                        "distance": f"{DISTANCE[n]}m",
                        "class": CLASSES[n],
                        "meet": {
                            "trackCondition": "Good 4",
                            "weather": "Fine",
                            "railPosition": "True",
                        },
                    }
                    for n in FIELDS
                ]
            }
        }
    if "GetBettingData" in query and "getRaceForm" not in query:  # prices before the race
        race = variables["raceNumber"]
        return {"data": rc_market(race, (scratched or {}).get(race, ()))}
    if "GetBettingData" in query:  # results: runners finish in saddlecloth order
        race = variables["raceNumber"]
        entries = [
            {
                "raceEntryNumber": n,
                "horseName": name,
                "finish": n,
                "scratched": False,
                "startingPrice": f"${2.0 + n:.2f}",
                "odds": [{"providerCode": "SB2", "oddsPlace": f"${1.2 + 0.4 * n:.2f}"}],
            }
            for n, name, *_ in FIELDS.get(race, [])
        ]
        exotics = [
            {"poolStatusCode": "Trifecta", "selections": "1/2/3", "amount": "$60.00"},
            {"poolStatusCode": "First 4", "selections": "1/2/3/4", "amount": "$400.00"},
        ]
        return {
            "data": {
                "getRaceForm": {"status": "Results", "formRaceEntries": entries},
                "GetBettingData": {"exotics": exotics},
            }
        }
    if "getRaceForm" in query:
        race = variables["raceNumber"]
        entries = [
            {
                "raceEntryNumber": n,
                "horseCode": f"H{race}-{n}",
                "horseName": name,
                "barrierNumber": barrier,
                "weight": f"{weight}kg",
                "jockeyName": jockey,
                "trainerName": trainer,
                "scratched": False,
                "emergency": False,
                "handicapRating": rating,
                "gearChanges": "Blinkers FIRST TIME" if n == 3 else None,
                "lastRaceDate": "2026-10-17",
                "trackStats": "3:1-0-1",
                "distanceStats": "5:2-1-0",
                "horse": {
                    "age": "5",
                    "sex": "Gelding",
                    "owners": f"{trainer} Racing Syndicate",
                    "sireHorseName": "Sire",
                    "damHorseName": "Dam",
                    "lastFive": '["1","x","2","3","1"]',
                    "goodStats": "8-3-1-1",
                    "softStats": "2-0-1-0",
                    "firstUpStats": "2:1-0-0",
                },
            }
            for n, name, barrier, jockey, trainer, weight, _last, rating in FIELDS.get(race, [])
        ]
        return {"data": {"getRaceForm": {"formRaceEntries": entries}}}
    if "GetRaceEntryItemByHorsePaged" in query:
        horse = variables["horseCode"]
        note = "Slow to begin. Held up in the straight." if horse.endswith("-1") else None

        def run(day: str, finish: str, comment: str | None) -> dict:
            return {
                "finish": finish,
                "margin": "1.5L",
                "startingPrice": "$6.50",
                "weightCarried": "57kg",
                "jockeyName": "J.Kah",
                "positionAtSettledAbv": "4th",
                "commentStewards": comment,
                "race": {
                    "date": day,
                    "isTrial": False,
                    "isJumpOut": False,
                    "venueAbbr": "FLEM",
                    "distance": "1600m",
                    "trackCondition": "Good 4",
                    "class": "BM78",
                    "runnersCount": 12,
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


RC_CALLS = (  # (text in the GraphQL query, label in Router.hits)
    ("GetMeetingByVenueDateTrial", "rc/meeting"),
    ("GetRaceMeetingsByStateNew", "rc/meetings"),
    ("GetRaceEntryItemByHorsePaged", "rc/runs"),
    ("exotics", "rc/results"),
    ("oddsByProvider", "rc/prices"),
    ("trainerName", "rc/card_field"),
    ("horseCode", "rc/field"),
    ("distance", "rc/card_races"),
    ("getRacesForMeet", "rc/races"),  # race list for a price check
)


def rc_label(query: str) -> str:
    return next((label for text, label in RC_CALLS if text in query), "rc/other")


class Router:
    """httpx transport that answers from the builders above. ``hits`` counts calls: FormFav by
    path, racing.com by what was asked (``rc/prices``, ``rc/results``, ``rc/card_field`` ...)."""

    def __init__(
        self, *, ff_tier: str = "pro", scratched: dict[int, tuple[int, ...]] | None = None
    ):
        self.ff_tier = ff_tier
        self.scratched = scratched or {}
        self.hits: dict[str, int] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        q = request.url.params
        host = request.url.host
        label = rc_label(q.get("query", "")) if host == "graphql.rmdprod.racing.com" else path
        self.hits[label] = self.hits.get(label, 0) + 1
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
            body = rc_payload(q["query"], json.loads(q["variables"]), self.scratched)
            return httpx.Response(200, json=body)
        return httpx.Response(404, json={"detail": f"no route {host}{path}"})


@pytest.fixture
def router() -> Router:
    return Router()


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())
