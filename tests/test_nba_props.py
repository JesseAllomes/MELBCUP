"""NBA prop price collector (azure/function/nba_props.py): writes a game only when prices change."""

import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "azure" / "function"))
import nba_props  # noqa: E402
from test_racelens_snapshot import Container  # noqa: E402


def feed(price):
    market = {
        "key": "1",
        "name": "Player Points",
        "eventClass": "Player Points Over/Under",
        "groupName": "Player Points",
        "outcomes": [
            {"name": "J Embiid Over 25.5", "price": price, "points": 25.5, "playerId": "9"}
        ],
    }

    def get(url):
        if "featured" in url:
            return {"events": [{"key": "77", "name": "A @ B", "startsAt": "x", "isLive": False}]}
        return {"fixedOddsMarkets": [market], "specialFixedOddsMarkets": []}

    return get


def test_only_changes_are_written(monkeypatch):
    box, now = Container(), dt.datetime(2026, 11, 5, 0, 0, tzinfo=dt.UTC)
    monkeypatch.setattr(nba_props, "get", feed(1.9))
    assert nba_props.collect(box, now) == (1, 1)
    assert nba_props.collect(box, now) == (1, 0)
    monkeypatch.setattr(nba_props, "get", feed(1.85))
    assert nba_props.collect(box, now + dt.timedelta(minutes=20)) == (1, 1)
    assert len([k for k in box.store if k.endswith(".gz")]) == 2


BOARD = {
    "day": "20261104",
    "params": {
        s: {"phi": 1.2, "ca": 1.0, "cb": 0.0} for s in ("points", "rebounds", "assists", "threes")
    },
    "games": [
        {"name": "Philadelphia 76ers at Detroit Pistons", "teams": {"home": "DET", "away": "PHI"}}
    ],
    "players": [{"name": "Joel Embiid", "team": "PHI", "minutes": 32.0, "mu": {"points": 26.0}}],
}


def snap(event, name, price):
    out = {"name": "Joel Embiid To Score 10+ Points", "price": price, "unitType": "Points"}
    return {
        "event": event,
        "name": name,
        "markets": [{"group": "Player Points Markets", "outcomes": [out]}],
    }


def test_price_legs_needs_todays_board_and_carries_started_games_forward():
    nba = Container()
    now = dt.datetime(2026, 11, 4, 23, 0, tzinfo=dt.UTC)  # 7pm 4 Nov in New York
    game = snap("1", "Philadelphia 76ers @ Detroit Pistons", 1.30)
    assert nba_props.price_legs(nba, [game], now) == "no board"
    nba.store["board-latest.json"] = json.dumps(BOARD | {"day": "20261103"}).encode()
    assert "not 20261104" in nba_props.price_legs(nba, [game], now)
    nba.store["board-latest.json"] = json.dumps(BOARD).encode()
    assert "1 value" in nba_props.price_legs(nba, [game], now)
    legs = json.loads(nba.store["20261104/legs.json"])
    assert legs["value_legs"][0]["label"] == "Joel Embiid To Score 10+ Points"
    assert nba.store["legs-latest.json"] == nba.store["20261104/legs.json"]
    # the game tips off and leaves the list: its legs stay for settling, but are no longer offered
    nba_props.price_legs(nba, [], now + dt.timedelta(minutes=20))
    legs = json.loads(nba.store["20261104/legs.json"])
    assert legs["value_legs"] == [] and legs["verdict"] == "nothing worth taking today"
    assert [g["event"] for g in legs["all_legs"]] == ["1"]
    assert [g["event"] for g in legs["closed_value_legs"]] == ["1"]
