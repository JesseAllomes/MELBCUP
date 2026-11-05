# ruff: noqa: E501
"""The $10 -> $1000 challenge (melbcup/nba_challenge.py), its tab, and its money in the header."""

from melbcup import nba_challenge as C

DAY = "2026-11-05"


def place(s, n, price="5.2", ag="pb"):
    return C.apply(
        s, {"ch": "place", "chs": str(n), "chp": price, "chag": ag, "chl": "G: a, b"}, DAY
    )


def test_a_run_places_rolls_keeps_the_start_and_ends_at_the_goal():
    s = C.apply(None, {"ch": "start"}, DAY)
    assert (s["bank"], s["goal"], s["mode"], s["keep"]) == (10.0, 1000.0, "game", True)
    assert C.apply(s, {"ch": "won", "chs": "0", "chr": "52"}, DAY) == s  # not placed yet: nothing
    s = place(s, 0)
    assert s["placed"]["stake"] == 10.0 and s["bets"][-1]["state"] == "placed"
    assert place(s, 0) == s  # placing twice: once
    s = C.apply(s, {"ch": "won", "chs": "0", "chr": "52"}, DAY)
    assert (s["bank"], s["kept"], s["placed"]) == (42.0, 10.0, None)  # the $10 start goes back
    assert (
        s["bets"][-1] | {} == s["bets"][-1]
        and s["bets"][-1]["state"] == "won"
        and s["bets"][-1]["ret"] == 52.0
    )
    s = C.apply(place(s, 1), {"ch": "won", "chs": "1", "chr": "210"}, DAY)
    assert (
        s["bank"] == 210.0 and round(C.next_x(s), 2) == 4.67
    )  # what is left to $980 (2% under $1000)
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
    assert (
        C.apply(s, {"ch": "won", "chs": "0", "chr": "9"}, DAY) == s
    )  # a win must pay more than the stake
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
    monkeypatch.setattr(
        nba_feed.NbaFeed.__init__, "__defaults__", (None, events(1.75), path, lambda: NOW)
    )
    from melbcup.web import app as app_module

    day = __import__("datetime").date(2026, 11, 5)
    monkeypatch.setattr(views, "melbourne_today", lambda: day)
    monkeypatch.setattr(app_module, "melbourne_today", lambda: day)
    with make(ON) as c:
        c.get("/?ag=1&on_pb=1&on_sb=1&pb=100")
        html = c.get("/nba?tab=challenge").text
        assert "$10 → $1000 challenge" in html and 'name="chkeep"' in html
        html = c.get("/nba?tab=challenge&ch=start&chmode=multi").text
        assert "Stage 1 of 3 · bank $10.00 of $1000" in html and "Mark as placed · $10.00" in html
        assert (
            'name="chtip" value="2026-11-05T00:00:00Z"' in html
        )  # the stage's tip-off travels with it
        html = c.get("/nba?tab=challenge&ch=place&chs=0&chag=pb&chp=5.36&chl=x").text
        assert "Placed: $10.00 at PointsBet" in html and 'value="53.60"' in html
        for tab in ("stacks", "games", "same", "all"):  # the challenge stays on its own tab
            other = c.get(f"/nba?tab={tab}").text
            assert (
                "Stage 1" not in other
                and "result due" not in other
                and "Mark as placed" not in other
            )
        assert "$90" in html  # $100 at PointsBet, $10 out
        html = c.get("/nba?tab=challenge&ch=won&chs=0&chr=53.60").text
        assert "Stage 2 of 3 · bank $43.60" in html and "$10 kept" in html
        today = html.split("<small>Today</small>")[1][:40]
        assert "43.60" in today  # the win counts in today's money
        assert "$143.60" in html  # PointsBet: $100 - $10 stake + $53.60 back
        html = c.get("/nba?tab=challenge&ch=won&chs=0&chr=53.60").text  # reload
        assert "Stage 2 of 3 · bank $43.60" in html
        assert "New challenge (change the settings)" in html
        html = c.get("/nba?tab=challenge&ch=new&chs=1").text
        assert 'name="chn"' in html and "Stage 2" not in html  # back to the set-up screen


def test_stages_set_the_payout_per_stage_and_rebalance():
    assert (
        round(C.stage_x(10, 1000, 3, True), 2) == 4.97
    )  # aims at $980: $10 -> $49.70 (keep $10) -> ... -> $980
    assert round(C.stage_x(10, 1000, 2, False), 2) == 9.9
    assert C.stage_x(10, 1000, 5, True) < C.stage_x(10, 1000, 4, True)
    s = C.apply(None, {"ch": "start", "chn": "5"}, DAY)
    assert s["stages"] == 5 and round(C.next_x(s), 2) == 2.74
    s = C.apply(place(s, 0), {"ch": "won", "chs": "0", "chr": "40"}, DAY)  # paid more than planned
    assert s["bank"] == 30.0 and C.remaining(s) == 4
    assert round(C.next_x(s), 2) == round((980 / 30) ** 0.25, 2)  # the rest re-balance
    assert C.apply(None, {"ch": "start", "chn": "99"}, DAY)["stages"] == 3  # only 2-8


def test_two_a_night_spaces_games_and_then_waits_for_the_next_night():
    s = C.apply(None, {"ch": "start", "chpn": "2"}, DAY)
    assert s["per_night"] == 2 and C.allowed(s, "2026-11-05T00:00:00Z")  # nothing played: anything
    s = C.apply(
        C.apply(s, {"ch": "place", "chs": "0", "chp": "5", "chtip": "2026-11-05T00:00:00Z"}, DAY),
        {"ch": "won", "chs": "0", "chr": "50"},
        DAY,
    )
    assert not C.allowed(s, "2026-11-05T01:30:00Z")  # overlaps the first game
    assert not C.allowed(s, "2026-11-05T03:00:00Z")  # game over ~2:30, but no hour to place
    assert C.allowed(s, "2026-11-05T03:30:00Z")  # 2h15 of game + 1 h to see it and place
    s = C.apply(
        C.apply(s, {"ch": "place", "chs": "1", "chp": "5", "chtip": "2026-11-05T03:30:00Z"}, DAY),
        {"ch": "won", "chs": "1", "chr": "200"},
        DAY,
    )
    assert not C.allowed(s, "2026-11-05T07:00:00Z")  # two done this night
    assert C.allowed(s, "2026-11-06T00:00:00Z")  # the next game day


def test_one_a_night_waits_and_the_chance_to_finish_grows_with_each_win():
    s = C.apply(None, {"ch": "start"}, DAY)
    assert round(C.finish_chance(0.34, s), 3) == round(0.34**3, 3)
    s = C.apply(
        C.apply(s, {"ch": "place", "chs": "0", "chp": "5", "chtip": "2026-11-05T00:00:00Z"}, DAY),
        {"ch": "won", "chs": "0", "chr": "50"},
        DAY,
    )
    assert round(C.finish_chance(0.34, s), 3) == round(0.34**2, 3)
    assert not C.allowed(s, "2026-11-05T05:00:00Z") and C.allowed(s, "2026-11-06T00:30:00Z")
    placed = C.apply(
        s, {"ch": "place", "chs": "1", "chp": "5", "chtip": "2026-11-06T00:30:00Z"}, DAY
    )
    assert C.result_due(placed).isoformat() == "2026-11-06T02:45:00+00:00"


def test_a_new_challenge_keeps_the_history_and_waits_for_a_placed_stage():
    s = C.apply(
        place(C.apply(None, {"ch": "start", "chn": "4"}, DAY), 0), {"ch": "lost", "chs": "0"}, DAY
    )
    s = place(s, 0)
    assert C.apply(s, {"ch": "new", "chs": "0"}, DAY) == s  # placed: settle it first
    s = C.apply(s, {"ch": "won", "chs": "0", "chr": "40"}, DAY)
    ended = C.apply(s, {"ch": "new", "chs": "1"}, DAY)
    assert ended["active"] is False and len(ended["bets"]) == 2 and ended["past"]
    assert C.apply(ended, {"ch": "place", "chs": "0", "chp": "5"}, DAY) == ended  # no run, no bets
    again = C.apply(ended, {"ch": "start", "chn": "2", "chpn": "2"}, DAY)
    assert (again["stages"], again["per_night"], again.get("active", True)) == (2, 2, True)
    assert len(again["bets"]) == 2  # today's money still counts the earlier stages


def test_plan_recommends_the_stage_count_most_likely_to_finish():
    def chances_for(xmap):  # a bigger payout a stage is harder: chance ~ 0.9 / price per game
        return {
            n: [min(0.95, 0.9 / x), min(0.95, 0.85 / x), min(0.95, 0.8 / x), 0.1]
            for n, x in xmap.items()
        }

    opts = C.plan(10, 250, True, chances_for)
    assert [o["n"] for o in opts] == list(C.STAGES)
    for o in opts:  # typical = the mean of the 3 best games, searched HAIRCUT above the payout
        assert (
            abs(o["typical"] - sum(c / (o["x"] / (1 - C.HAIRCUT)) for c in (0.9, 0.85, 0.8)) / 3)
            < 1e-9
        )
        assert abs(o["run"] - o["typical"] ** o["n"]) < 1e-12
    best, why = C.recommend(opts)
    assert best["run"] == max(o["run"] for o in opts) and f"{best['n']} stages" in why
    assert C.recommend([]) == (None, "")


def test_finish_chance_uses_a_typical_later_stage():
    s = C.fresh(stages=3)
    assert abs(C.finish_chance(0.6, s) - 0.6**3) < 1e-12
    assert abs(C.finish_chance(0.6, s, 0.5) - 0.6 * 0.25) < 1e-12


def test_skip_moves_the_stage_to_a_later_night():
    s = C.apply(None, {"ch": "start", "chn": "4"}, DAY)
    tonight = "2026-11-05T00:10:00Z"  # Thu 5 Nov 11:10am Melbourne
    tomorrow = "2026-11-06T00:10:00Z"
    assert C.allowed(s, tonight)
    s = C.apply(s, {"ch": "skip", "chs": "0", "chnight": "2026-11-05"}, DAY)
    assert s["skip"] == "2026-11-05" and not C.allowed(s, tonight) and C.allowed(s, tomorrow)
    assert C.apply(s, {"ch": "skip", "chs": "0", "chnight": "nope"}, DAY) == s


def test_own_bets_are_logged_counted_in_the_day_and_settled():
    q = {"ch": "bet", "nbag": "sb", "nbs": "10", "nbp": "5.03", "nbl": "Bucks @ Celtics: A, B, C, D"}
    s = C.apply(None, q, DAY)
    assert s["active"] is False and C.own_bets(s, DAY)[0]["state"] == "placed"
    assert C.apply(s, q, DAY) == s  # a reload saves nothing twice
    assert C.today_money(s, DAY) == ({"sb": 10.0}, 0.0)  # off the Sportsbet balance
    bid = str(C.own_bets(s, DAY)[0]["id"])
    won = C.apply(s, {"ch": "betwon", "nbid": bid, "nbr": "50.30"}, DAY)
    assert C.today_money(won, DAY) == ({"sb": -40.3}, 40.3)
    lost = C.apply(s, {"ch": "betlost", "nbid": bid}, DAY)
    assert C.today_money(lost, DAY) == ({"sb": 10.0}, -10.0)
    assert C.own_bets(lost, "2099-01-01") == []  # settled on an earlier day: off the list
    run = C.apply(s, {"ch": "start", "chn": "3"}, DAY)  # starting a challenge keeps the bet
    assert C.own_bets(run, DAY) and run.get("active", True) is not False


def test_lost_by_one_leg_replays_the_stage_with_the_bonus_bet():
    s = C.apply(None, {"ch": "start", "chn": "3"}, DAY)
    s = C.apply(s, {"ch": "place", "chs": "0", "chp": "2.62", "chag": "sb"}, DAY)
    b = C.apply(s, {"ch": "lost1", "chs": "0"}, DAY)
    assert b["bonus"] == 10.0 and b["placed"] is None and not b["steps"] and b.get("active", True)
    assert C.next_x(b) == round(C.next_x(C.fresh(stages=3)) + 1, 6) or C.next_x(b) > C.next_x(C.fresh(stages=3))
    b = C.apply(b, {"ch": "place", "chs": "0", "chp": "2.62", "chag": "sb"}, DAY)
    assert b["placed"]["bonus"] and "bonus" not in b
    assert C.apply(b, {"ch": "lost1", "chs": "0"}, DAY)["past"][-1]["made_it"] is False  # no second refund
    won = C.apply(b, {"ch": "won", "chs": "0", "chr": "16.20"}, DAY)  # winnings only
    assert won["bank"] == 16.2 and won["kept"] == 0.0  # no stake back from a bonus bet
    used, profit = C.today_money(won, DAY)
    assert used == {"sb": -6.2} and profit == 6.2  # $10 lost, then $16.20 from the bonus bet


def test_a_placed_stage_can_be_marked_as_a_bonus_bet():
    s = C.apply(None, {"ch": "start", "chn": "2", "chgoal": "200"}, DAY)
    s = C.apply(s, {"ch": "place", "chs": "0", "chp": "5.25", "chag": "sb"}, DAY)
    s = C.apply(s, {"ch": "isbonus", "chs": "0"}, DAY)
    assert s["placed"]["bonus"] and C.today_money(s, DAY) == ({"sb": 0.0}, 0.0)  # no cash out
    won = C.apply(s, {"ch": "won", "chs": "0", "chr": "42.50"}, DAY)
    assert won["bank"] == 42.5 and C.today_money(won, DAY) == ({"sb": -42.5}, 42.5)
    b = C.apply(C.apply(None, {"ch": "start"}, DAY), {"ch": "place", "chs": "0", "chp": "3", "chbonus": "1"}, DAY)
    assert b["placed"]["bonus"]


def test_undo_puts_a_mistyped_result_back_to_placed():
    s = C.apply(None, {"ch": "start", "chn": "2", "chgoal": "200"}, DAY)
    s = C.apply(s, {"ch": "place", "chs": "0", "chp": "5.25", "chag": "sb", "chbonus": "1"}, DAY)
    typo = C.apply(s, {"ch": "won", "chs": "0", "chr": "5.25"}, DAY)  # the odds, not the dollars
    assert typo["bank"] == 5.25 and len(typo["steps"]) == 1
    back = C.apply(typo, {"ch": "undo", "chs": "1"}, DAY)
    assert back["placed"]["state"] == "placed" and back["bank"] == 10.0 and back["steps"] == [] and back["kept"] == 0.0
    fixed = C.apply(back, {"ch": "won", "chs": "0", "chr": "42.50"}, DAY)
    assert fixed["bank"] == 42.5 and C.today_money(fixed, DAY) == ({"sb": -42.5}, 42.5)


def test_stages_can_be_added_or_removed_mid_run():
    s = C.apply(None, {"ch": "start", "chn": "2", "chgoal": "200"}, DAY)
    x2 = C.next_x(s)
    s = C.apply(s, {"ch": "addstage", "chs": "0"}, DAY)
    assert s["stages"] == 3 and C.next_x(s) < x2  # more stages: a smaller payout a stage
    s = C.apply(s, {"ch": "dropstage", "chs": "0"}, DAY)
    s = C.apply(s, {"ch": "dropstage", "chs": "0"}, DAY)
    assert s["stages"] == 2  # never fewer than the next stage plus one more... or 2
    for _ in range(9):
        s = C.apply(s, {"ch": "addstage", "chs": "0"}, DAY)
    assert s["stages"] == max(C.STAGES)
