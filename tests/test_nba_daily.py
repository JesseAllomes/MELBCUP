# ruff: noqa: E501
"""Daily NBA job (tools/nba/daily.py): history grows, yesterday settles once, today's board is written."""

import datetime as dt
import gzip
import json
import os
import sys

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "nba"))
import daily  # noqa: E402


def box_player(pid, name, team, pts, starter=True):
    return {"id": pid, "name": name, "starter": starter, "min": 30.0, "points": pts, "reboundsTotal": 5, "assists": 3, "threePointersMade": 1, "team": team}


def game(i, when, pts):
    return {"id": str(i), "gameTimeUTC": when, "season": "00225",
            "players": [box_player("1", "Joel Embiid", "PHI", pts), box_player("2", "Cade Cunningham", "DET", 20)]}


def summary(rows):
    """The ESPN summary shape that espn_history.game_rows reads."""
    teams = {}
    for r in rows:
        teams.setdefault(r["team"], []).append(r)
    return {"boxscore": {"players": [
        {"team": {"abbreviation": t}, "statistics": [{"labels": ["MIN", "PTS", "REB", "AST", "3PT"], "athletes": [
            {"athlete": {"id": r["id"], "displayName": r["name"]}, "starter": True, "stats": [str(int(r["min"])), str(r["points"]), "5", "3", "1-3"]} for r in rs]}]}
        for t, rs in teams.items()]}}


def fake_espn(finished_day):
    """One finished game on finished_day (US date), one fixture on 20261104."""
    def fetch(url):
        if "scoreboard" in url and finished_day in url:
            return {"events": [{"id": "900", "date": "2026-11-04T00:00Z", "season": {"year": 2027, "type": 2}, "status": {"type": {"completed": True}}}]}
        if "scoreboard" in url and "20261104" in url:
            return {"events": [{"date": "2026-11-05T00:00Z", "name": "Philadelphia 76ers at Detroit Pistons",
                                "competitions": [{"competitors": [{"homeAway": "home", "team": {"abbreviation": "DET"}}, {"homeAway": "away", "team": {"abbreviation": "PHI"}}]}]}]}
        if "scoreboard" in url:
            return {"events": []}
        if "summary" in url:
            return summary([box_player("1", "Joel Embiid", "PHI", 31), box_player("2", "Cade Cunningham", "DET", 12)])
        if "injuries" in url:
            return {"injuries": []}
        raise AssertionError(url)
    return fetch


def test_daily_adds_games_settles_yesterday_once_and_builds_board(tmp_path):
    hist = [game(i, f"2025-11-{i + 1:02d}T00:00Z", 20 + i % 5) for i in range(20)]
    store = daily.LocalStore(str(tmp_path))
    store.write(daily.HISTORY, gzip.compress("\n".join(json.dumps(g) for g in hist).encode()))
    legs = [{"event": "e1", "label": "Joel Embiid To Score 25+ Points", "player": "Joel Embiid", "stat": "points", "line": 25, "price": 1.5, "chance": 0.7},
            {"event": "e1", "label": "Cade Cunningham To Score 20+ Points", "player": "Cade Cunningham", "stat": "points", "line": 20, "price": 1.8, "chance": 0.6}]
    store.write("20261103/legs.json", json.dumps({"all_legs": legs, "value_legs": [], "closed_value_legs": legs[:1]}).encode())
    now = dt.datetime(2026, 11, 4, 22, 30, tzinfo=dt.UTC)
    daily.run(store, now, fake_espn("20261103"))
    after = [json.loads(x) for x in gzip.decompress(store.read(daily.HISTORY)).decode().splitlines()]
    assert len(after) == 21 and after[-1]["season"] == "00226"
    settled = [json.loads(x) for x in store.read("20261103/settled.jsonl").decode().splitlines()]
    assert [(x["result"], x["value"]) for x in settled] == [("won", True), ("lost", False)]
    board = json.loads(store.read("board-latest.json"))
    assert board["day"] == "20261104" and {p["name"] for p in board["players"]} == {"Joel Embiid", "Cade Cunningham"}
    assert store.read("20261104/board.json") == store.read("board-latest.json")
    daily.run(store, now, fake_espn("20261103"))  # a second run neither re-adds nor re-settles
    assert len(gzip.decompress(store.read(daily.HISTORY)).decode().splitlines()) == 21
    assert len(store.read("forward.jsonl").decode().splitlines()) == 2


def test_a_night_off_builds_the_next_game_day(tmp_path):
    hist = [game(i, f"2025-11-{i + 1:02d}T00:00Z", 20 + i % 5) for i in range(20)]
    store = daily.LocalStore(str(tmp_path))
    store.write(daily.HISTORY, gzip.compress("\n".join(json.dumps(g) for g in hist).encode()))
    now = dt.datetime(2026, 11, 3, 22, 30, tzinfo=dt.UTC)  # 3 Nov in New York: no games
    daily.run(store, now, fake_espn("20261102"))
    assert json.loads(store.read("board-latest.json"))["day"] == "20261104"


def test_settles_agency_logs_legs_and_multis_and_reports(tmp_path):
    import forward_report
    from settle import settle_multi

    rows = {"joel embiid": {"min": 30, "points": 30}, "cade cunningham": {"min": 30, "points": 10}}
    a = {"player": "Joel Embiid", "stat": "points", "line": 25, "under": False, "price": 1.5, "chance": 0.7, "label": "a"}
    b = {"player": "Cade Cunningham", "stat": "points", "line": 20, "under": False, "price": 1.8, "chance": 0.6, "label": "b"}
    c = {"player": "Cade Cunningham", "stat": "points", "line": 20, "under": True, "price": 2.0, "chance": 0.4, "label": "c"}
    d = {"player": "No Show", "stat": "points", "line": 5, "under": False, "price": 1.2, "chance": 0.9, "label": "d"}
    assert settle_multi({"price": 2.7, "detail": [a, b]}, rows)["result"] == "lost"
    assert settle_multi({"price": 3.0, "detail": [a, c]}, rows)["result"] == "won"  # the under wins
    v = settle_multi({"price": 1.8, "detail": [a, d]}, rows)
    assert v["result"] == "won" and v["price"] == 1.5  # the void leg drops out
    store = daily.LocalStore(str(tmp_path))
    for ag in ("pb", "sb"):
        log = {"agency": ag, "day": "20261103", "legs": [a | {"event": "e"}, b | {"event": "e"}],
               "multis": [{"kind": "stacks", "price": 3.0, "chance": 0.28, "picks": ["a", "c"], "detail": [a, c]}]}
        store.write(f"20261103/log-{ag}.json", json.dumps(log).encode())
    n = daily.settle_day(store, "20261103", {"Joel Embiid": rows["joel embiid"], "Cade Cunningham": rows["cade cunningham"]})
    assert n == 6
    text = forward_report.report(forward_report.load(str(tmp_path / "forward.jsonl")))
    assert "legs / agency sb" in text and "multis / kind stacks" in text and "stat points" in text
