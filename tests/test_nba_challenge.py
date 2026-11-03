# ruff: noqa: E501
"""The $10 -> $1000 challenge (melbcup/nba_challenge.py), its tab, and its money in the header."""

from melbcup import nba_challenge as C

DAY = "2026-11-05"


def place(s, n, price="5.2", ag="pb"):
    return C.apply(s, {"ch": "place", "chs": str(n), "chp": price, "chag": ag, "chl": "G: a, b"}, DAY)


def test_a_run_places_rolls_keeps_the_start_and_ends_at_the_goal():
    s = C.apply(None, {"ch": "start"}, DAY)
    assert (s["bank"], s["goal"], s["mode"], s["keep"]) == (10.0, 1000.0, "game", True)
    assert C.apply(s, {"ch": "won", "chs": "0", "chr": "52"}, DAY) == s  # not placed yet: nothing
    s = place(s, 0)
    assert s["placed"]["stake"] == 10.0 and s["bets"][-1]["state"] == "placed"
    assert place(s, 0) == s  # placing twice: once
    s = C.apply(s, {"ch": "won", "chs": "0", "chr": "52"}, DAY)
    assert (s["bank"], s["kept"], s["placed"]) == (42.0, 10.0, None)  # the $10 start goes back
    assert s["bets"][-1] | {} == s["bets"][-1] and s["bets"][-1]["state"] == "won" and s["bets"][-1]["ret"] == 52.0
    s = C.apply(place(s, 1), {"ch": "won", "chs": "1", "chr": "210"}, DAY)
    assert s["bank"] == 210.0 and round(C.next_x(s), 2) == 4.76  # what is left to $1000
    s = C.apply(place(s, 2), {"ch": "won", "chs": "2", "chr": "1050"}, DAY)
    assert s["bank"] == 10.0 and s["last_win"] == 1050.0 and s["past"][-1]["made_it"]


def test_a_loss_ends_the_run_and_reloads_never_count_twice():
    s = place(C.apply(None, {"ch": "start", "chkeep": "0"}, DAY), 0)
    s = C.apply(s, {"ch": "won", "chs": "0", "chr": "50"}, DAY)
    assert s["bank"] == 50.0 and s["kept"] == 0.0  # keep off: everything rolls
    assert C.apply(s, {"ch": "won", "chs": "0", "chr": "50"}, DAY) == s  # the same page reloaded
    s = place(s, 1)
    lost = C.apply(s, {"ch": "lost", "chs": "1"}, DAY)
    assert lost["bank"] == 10.0 and lost["past"][-1] == {"steps": 1, "best": 50.0, "made_it": False}
    assert [b["state"] for b in lost["bets"]] == ["won", "lost"]
    assert C.apply(lost, {"ch": "lost", "chs": "1"}, DAY) == lost


def test_todays_money_takes_stakes_off_and_pays_wins_back():
    s = place(C.apply(None, {"ch": "start"}, DAY), 0)
    used, profit = C.today_money(s, DAY)
    assert used == {"pb": 10.0} and profit == 0.0  # placed: off the balance, no result yet
    s = C.apply(s, {"ch": "won", "chs": "0", "chr": "52"}, DAY)
    used, profit = C.today_money(s, DAY)
    assert used == {"pb": -42.0} and profit == 42.0  # the win paid back in
    s = C.apply(place(s, 1, ag="sb"), {"ch": "lost", "chs": "1"}, DAY)
    used, profit = C.today_money(s, DAY)
    assert used == {"pb": -42.0, "sb": 42.0} and profit == 0.0
    assert C.today_money(s, "2026-11-06") == ({}, 0.0)  # tomorrow starts clean


def test_bad_input_changes_nothing():
    s = C.apply(None, {"ch": "start", "chstart": "abc", "chgoal": "5"}, DAY)
    assert (s["start"], s["goal"]) == (10.0, 20.0)  # goal at least 2x the start
    s = place(s, 0)
    assert C.apply(s, {"ch": "won", "chs": "0", "chr": "9"}, DAY) == s  # a win must pay more than the stake
    assert C.apply(s, {"ch": "reset", "chs": "0"}, DAY) == s  # a placed stage settles first
    assert C.parse("not json") is None and C.parse('{"x": 1}') is None


def test_the_tab_and_the_header_money(monkeypatch, tmp_path):
    import json

    from test_asynym import ON, make
    from test_nba_page import BOARD, NOW, events

    from melbcup import nba_feed
    from melbcup.web import views

    path = tmp_path / "board.json"
    path.write_text(json.dumps(BOARD))
    monkeypatch.setattr(nba_feed.NbaFeed.__init__, "__defaults__", (None, events(1.75), path, lambda: NOW))
    from melbcup.web import app as app_module

    day = __import__("datetime").date(2026, 11, 5)
    monkeypatch.setattr(views, "melbourne_today", lambda: day)
    monkeypatch.setattr(app_module, "melbourne_today", lambda: day)
    with make(ON) as c:
        c.get("/?ag=1&on_pb=1&on_sb=1&pb=100")
        html = c.get("/nba?tab=challenge").text
        assert "$10 → $1000 challenge" in html and 'name="chkeep"' in html
        html = c.get("/nba?tab=challenge&ch=start&chmode=multi").text
        assert "Stage 1 · bank $10.00 of $1000" in html and "Mark as placed · $10.00" in html
        html = c.get("/nba?tab=challenge&ch=place&chs=0&chag=pb&chp=5.36&chl=x").text
        assert "Placed: $10.00 at PointsBet" in html and 'value="53.60"' in html
        assert "$90" in html  # $100 at PointsBet, $10 out
        html = c.get("/nba?tab=challenge&ch=won&chs=0&chr=53.60").text
        assert "Stage 2 · bank $43.60" in html and "$10 kept" in html
        today = html.split('<small>Today</small>')[1][:40]
        assert "43.60" in today  # the win counts in today's money
        assert "$143.60" in html  # PointsBet: $100 - $10 stake + $53.60 back
        html = c.get("/nba?tab=challenge&ch=won&chs=0&chr=53.60").text  # reload
        assert "Stage 2 · bank $43.60" in html
