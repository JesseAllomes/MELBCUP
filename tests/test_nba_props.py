# ruff: noqa: E501
"""NBA prop price collector (azure/function/nba_props.py): writes a game only when prices change."""

import datetime as dt
import gzip
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
        s: {"phi": 1.2, "ca": 1.0, "cb": 0.0}
        for s in ("points", "reboundsTotal", "assists", "threePointersMade")
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



def test_build_view_saves_both_agencies_for_the_page():

    nba = Container()
    now = dt.datetime(2026, 11, 4, 23, 0, tzinfo=dt.UTC)
    assert nba_props.build_view(nba, [], now, inj_fetch=lambda u: {}) == "no board"
    nba.store["board-latest.json"] = json.dumps(BOARD).encode()
    game = snap("1", "Philadelphia 76ers @ Detroit Pistons", 1.30)
    sb = [{"event": "sb1", "name": "Philadelphia 76ers @ Detroit Pistons", "startsAt": "x", "markets": [{"group": "sportsbet", "outcomes": [
        {"name": "Joel Embiid 10+ Points", "price": 1.4, "player": "Joel Embiid", "stat": "points", "k": 10, "under": False}]}]}]
    out = nba_props.build_view(nba, [game], now, sb_fetch=lambda: sb, inj_fetch=lambda u: {})
    assert out.startswith("view") and "pb 1" in out and "sb 1" in out
    view = json.loads(gzip.decompress(nba.store["view-latest.json.gz"]))
    assert view["day"] == "20261104" and view["pricedAt"] == now.isoformat() and set(view["preview"]) == {"pb", "sb"}

    def down():
        raise OSError("blocked")

    nba_props.build_view(nba, [game], now, sb_fetch=down, inj_fetch=lambda u: {})
    view = json.loads(gzip.decompress(nba.store["view-latest.json.gz"]))
    assert "did not answer" in view["agencies"]["sb"]["error"] and view["agencies"]["pb"]["report"]["all_legs"]


def test_injuries_drop_out_players_mark_doubtful_and_log_both_agencies():

    nba = Container()
    now = dt.datetime(2026, 11, 4, 23, 0, tzinfo=dt.UTC)
    nba.store["board-latest.json"] = json.dumps(BOARD).encode()
    game = snap("1", "Philadelphia 76ers @ Detroit Pistons", 1.30)
    sb = [{"event": "sb1", "name": "Philadelphia 76ers @ Detroit Pistons", "startsAt": "x", "markets": [{"group": "sportsbet", "outcomes": [
        {"name": "Joel Embiid 10+ Points", "price": 1.4, "player": "Joel Embiid", "stat": "points", "k": 10, "under": False}]}]}]

    def espn(status):
        return lambda u: {"injuries": [{"injuries": [{"status": status, "athlete": {"displayName": "Joel Embiid"}}]}]}

    nba_props.build_view(nba, [game], now, sb_fetch=lambda: sb, inj_fetch=espn("Out"))
    view = json.loads(gzip.decompress(nba.store["view-latest.json.gz"]))
    assert view["agencies"]["pb"]["report"]["all_legs"] == [] and view["agencies"]["sb"]["report"]["all_legs"] == []
    assert view["injuries"] == 1
    nba_props.build_view(nba, [game], now, sb_fetch=lambda: sb, inj_fetch=espn("Doubtful"))
    view = json.loads(gzip.decompress(nba.store["view-latest.json.gz"]))
    assert view["agencies"]["pb"]["report"]["all_legs"][0]["injury"] == "doubtful"
    for ag in ("pb", "sb"):
        log = json.loads(nba.store[f"20261104/log-{ag}.json"])
        leg = log["legs"][0]
        assert leg["agency"] == ag and leg["k"] == 10 and leg["player"] == "Joel Embiid" and leg["injury"] == "doubtful"
        assert {"price", "chance", "under", "stat"} <= set(leg)
        assert any(m["kind"] == "by_game" for m in log["multis"])
    # ESPN down: no change
    nba_props.build_view(nba, [game], now, sb_fetch=lambda: sb, inj_fetch=lambda u: 1 / 0)
    view = json.loads(gzip.decompress(nba.store["view-latest.json.gz"]))
    assert "injury" not in view["agencies"]["pb"]["report"]["all_legs"][0]
