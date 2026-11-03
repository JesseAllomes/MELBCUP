# ruff: noqa: E501
"""The $10 -> $1000 challenge (melbcup/nba_challenge.py) and its tab on the NBA page."""

from melbcup import nba_challenge as C


def test_a_run_rolls_the_bank_and_ends_at_the_goal():
    s = C.apply(None, {"ch": "start"})
    assert (s["bank"], s["goal"], s["steps"], s["mode"]) == (10.0, 1000.0, [], "game")
    assert C.next_x(s) == 5.0
    s = C.apply(s, {"ch": "won", "chs": "0", "chr": "52.40"})
    assert s["bank"] == 52.4 and len(s["steps"]) == 1
    s = C.apply(s, {"ch": "won", "chs": "1", "chr": "270"})
    assert round(C.next_x(s), 2) == 3.7  # what is left to $1000, not another 5x
    s = C.apply(s, {"ch": "won", "chs": "2", "chr": "1010"})
    assert s["bank"] == 10.0 and s["last_win"] == 1010.0  # made it: a new run starts
    assert s["past"] == [{"steps": 3, "best": 1010.0, "made_it": True}]


def test_a_loss_ends_the_run_and_a_reload_never_counts_twice():
    s = C.apply(C.apply(None, {"ch": "start"}), {"ch": "won", "chs": "0", "chr": "50"})
    again = C.apply(s, {"ch": "won", "chs": "0", "chr": "50"})  # the same page reloaded
    assert again == s
    lost = C.apply(s, {"ch": "lost", "chs": "1"})
    assert lost["bank"] == 10.0 and lost["past"][-1] == {"steps": 1, "best": 50.0, "made_it": False}
    assert C.apply(lost, {"ch": "lost", "chs": "1"}) == lost  # reload after the loss: no change


def test_bad_input_changes_nothing():
    s = C.apply(None, {"ch": "start", "chstart": "abc", "chgoal": "5"})
    assert (s["start"], s["goal"]) == (10.0, 20.0)  # goal at least 2x the start
    assert C.apply(s, {"ch": "won", "chs": "0", "chr": "9"}) == s  # a win must grow the bank
    assert C.parse("not json") is None and C.parse('{"x": 1}') is None


def test_the_challenge_tab_keeps_its_state_in_a_cookie(monkeypatch, tmp_path):
    import json

    from test_asynym import ON, make
    from test_nba_page import BOARD, NOW, events

    from melbcup import nba_feed

    path = tmp_path / "board.json"
    path.write_text(json.dumps(BOARD))
    monkeypatch.setattr(nba_feed.NbaFeed.__init__, "__defaults__", (None, events(1.75), path, lambda: NOW))
    with make(ON) as c:
        html = c.get("/nba?tab=challenge").text
        assert "$10 → $1000 challenge" in html and 'name="chstart"' in html
        r = c.get("/nba?tab=challenge&ch=start")
        assert C.COOKIE in r.cookies or C.COOKIE in c.cookies
        html = r.text
        assert "Stage 1 · bank $10.00 of $1000" in html and "No game reaches" in html  # one line a game
        r = c.get("/nba?tab=challenge&ch=start&chmode=multi")
        assert "Stage 1 · bank $10.00" in r.text and "3-leg multi" in r.text
        r = c.get("/nba?tab=challenge&ch=won&chs=0&chr=53.59")
        assert "Stage 2 · bank $53.59" in r.text
        r = c.get("/nba?tab=challenge&ch=won&chs=0&chr=53.59")  # reload
        assert "Stage 2 · bank $53.59" in r.text
        r = c.get("/nba?tab=challenge&ch=lost&chs=1")
        assert "Stage 1 · bank $10.00" in r.text and "✗ at stage 2" in r.text


def test_one_game_per_stage_picks_the_likeliest_same_game_multi():
    from melbcup import nba_legs as L

    legs = [{"event": e, "game": f"G{e}", "startsAt": f"2026-11-05T0{e}:00:00Z", "player": f"{e}{i}", "label": f"{e}{i}",
             "team": "T", "chance": c, "price": p}
            for e, c, p in (("1", 0.8, 1.8), ("2", 0.7, 1.8)) for i in range(3)]
    games = L.same_game_for(legs, 5.0)
    assert [g["game"] for g in games] == ["G1", "G2"]  # soonest tip-off first
    assert all(g["legs"] == 3 and g["price"] >= 5.0 for g in games)
    assert max(games, key=lambda g: g["chance"])["game"] == "G1"
