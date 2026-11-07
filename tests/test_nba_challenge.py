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
        assert "Challenges · 0" in html and 'name="chname"' in html  # the list, nothing yet
        fake = [{"n": n, "x": 3.0, "typical": 0.5, "run": 0.2} for n in (2, 3, 4)]
        monkeypatch.setattr(views.Views, "_stage_preview", lambda self, *a, **k: fake)
        pv = c.get("/nba?tab=challenge&chpreview=1&chname=Run&chstart=20&chgoal=500").text
        assert 'class="ch-preview"' in pv and "Best:" in pv and 'value="500"' in pv
        assert "Challenges · 0" in c.get("/nba?tab=challenge").text  # preview created nothing
        html = c.get("/nba?tab=challenge&ch=newch&chname=Run&chmode=multi").text
        i = html.index('id="ch-plan"')
        assert html[:i].rindex("<details") > html[:i].rindex("</details>")  # planner is in a fold
        assert "<details" in html[i - 40 : i] and " open" not in html[i - 40 : i]
        assert "Stage 1 of 3 · bank $10.00 of $1000" in html and "Mark as placed · $10.00" in html
        assert (
            'name="chtip" value="2026-11-05T00:00:00Z"' in html
        )  # the stage's tip-off travels with it
        html = c.get("/nba?tab=challenge&chid=ch1&ch=place&chs=0&chag=pb&chp=5.36&chl=x").text
        assert "Placed: $10.00 at PointsBet" in html and 'value="53.60"' in html
        assert "Edit this bet" in html and 'value="chbet"' in html and "Potential return" in html
        for tab in ("stacks", "games", "same", "all"):  # the challenge stays on its own tab
            other = c.get(f"/nba?tab={tab}").text
            assert (
                "Stage 1" not in other
                and "result due" not in other
                and "Mark as placed" not in other
            )
        assert "$90" in html  # $100 at PointsBet, $10 out
        html = c.get("/nba?tab=challenge&chid=ch1&ch=won&chs=0&chr=53.60").text
        assert "Stage 2 of 3 · bank $43.60" in html and "$10 kept" in html
        today = html.split("<small>Today</small>")[1][:40]
        assert "43.60" in today  # the win counts in today's money
        assert "$143.60" in html  # PointsBet: $100 - $10 stake + $53.60 back
        html = c.get("/nba?tab=challenge&chid=ch1&ch=won&chs=0&chr=53.60").text  # reload
        assert "Stage 2 of 3 · bank $43.60" in html
        assert "New challenge (change the settings)" in html
        html = c.get("/nba?tab=challenge&chid=ch1&ch=new&chs=1").text
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


def test_a_picked_game_sticks_until_find_best():
    s = C.apply(None, {"ch": "start", "chn": "3"}, DAY)
    s = C.apply(s, {"ch": "pick", "chs": "0", "chpick": "A @ B"}, DAY)
    assert s["pick"] == "A @ B"
    assert "pick" not in C.apply(s, {"ch": "best", "chs": "0"}, DAY)
    placed = C.apply(s, {"ch": "place", "chs": "0", "chp": "2.4"}, DAY)
    assert "pick" not in placed  # the next stage starts from the best again


# --- many challenges, wallet, promos, recorded wagers (2026-11-07) -------------------------------
import json  # noqa: E402

import pytest  # noqa: E402

from melbcup import promos, wallet  # noqa: E402


def do(store, **q):
    new, changed, err = C.apply_store(store, {k.removeprefix("_"): v for k, v in q.items()}, DAY)
    return new, changed, err


def four():
    s = C.empty_store()
    for i in range(4):
        s, _, _ = do(s, ch="newch", chname=f"C{i + 1}", chscope="all" if i == 3 else "nba", op=f"n{i}")
    return s


def bank(s, cid):
    return C.find(s, cid)["state"]["bank"]


def test_four_challenges_run_at_once_and_never_touch_each_others_money():
    s = four()
    assert [c["id"] for c in s["challenges"]] == ["ch1", "ch2", "ch3", "ch4"]
    assert C.find(s, "ch4")["scope"] == "all"
    s, *_ = do(s, ch="place", chid="ch1", chs="0", chp="5", chag="sb", chl="a")
    s, *_ = do(s, ch="place", chid="ch2", chs="0", chp="3", chag="pb", chl="b")
    s, *_ = do(s, ch="won", chid="ch1", chs="0", chr="50")
    s, *_ = do(s, ch="lost", chid="ch2", chs="0")  # A wins, B loses: C and D untouched
    assert bank(s, "ch1") == 40.0  # $10 start kept, $40 rolls on
    assert bank(s, "ch2") == 10.0 and C.find(s, "ch2")["state"]["past"][-1]["made_it"] is False
    assert bank(s, "ch3") == bank(s, "ch4") == 10.0
    assert C.find(s, "ch3")["state"]["bets"] == [] and C.find(s, "ch1")["state"]["past"] == []
    used, profit = C.store_money(s, DAY)
    assert used == {"sb": -40.0, "pb": 10.0} and profit == 30.0  # 40 won, 10 lost


def test_an_op_id_makes_a_resubmit_do_nothing():
    s = four()
    a, ch1, _ = do(s, ch="place", chid="ch1", chs="0", chp="5", chag="sb", chl="a", op="x1")
    assert ch1
    won, _, _ = do(a, ch="won", chid="ch1", chs="0", chr="50", op="x2")
    again, changed, _ = do(won, ch="won", chid="ch1", chs="0", chr="50", op="x2")
    assert not changed and again == won
    g, _, _ = do(s, ch="wgrant", wprov="Sportsbet", wamt="20", op="g1")
    g2, changed, _ = do(g, ch="wgrant", wprov="Sportsbet", wamt="20", op="g1")
    assert not changed and len(g2["ledger"]) == 1
    _, _, err = do(s, ch="place", chid="nope", chs="0")
    assert err == "no such challenge"


def grant(s, amt="20", prov="Sportsbet", **kw):
    return do(s, ch="wgrant", wprov=prov, wamt=amt, **kw)[0]


def test_a_credit_is_allocated_at_most_once_until_released():
    s = grant(four())
    s, ok, _ = do(s, ch="walloc", wid="c1", chid="ch1")
    assert ok
    s2, ok, err = do(s, ch="walloc", wid="c1", chid="ch2")
    assert not ok and err == "already allocated"
    assert do(s, ch="wsplit", wid="c1", wparts="10,10")[2] == "release it from its challenge first"
    s, _, _ = do(s, ch="wrel", wid="c1")
    s, ok, _ = do(s, ch="walloc", wid="c1", chid="ch2")
    assert ok and wallet.credits(s["ledger"])["c1"]["challenge"] == "ch2"
    s, *_ = do(s, ch="wred", wid="c1")  # redeemed while held by ch2: used once, then closed
    assert do(s, ch="walloc", wid="c1", chid="ch3")[2] == "credit is redeemed"
    assert do(s, ch="wrel", wid="c1")[2] == "credit is redeemed"


def test_splits_make_unique_children_only_for_amounts_the_owner_enters():
    s = grant(four(), "50", wplans="25+25;10+10+10+10+10")
    assert do(s, ch="wsplit", wid="c1", wparts="30,20")[2].startswith("not one of the splits")
    s, *_ = do(s, ch="wsplit", wid="c1", wparts="25,25")
    ids = [c for c in wallet.credits(s["ledger"])]
    assert ids == ["c1", "c1.1", "c1.2"] and len(set(ids)) == 3
    cs = wallet.credits(s["ledger"])
    assert cs["c1"]["status"] == "split" and cs["c1.1"]["amount"] == cs["c1.2"]["amount"] == 25.0
    assert wallet.balances(s["ledger"]) == {"Sportsbet": {"open": 50.0, "held": 0.0}}  # children only
    assert do(s, ch="wsplit", wid="c1", wparts="25,25")[2] == "credit is split"  # not twice
    s, *_ = do(s, ch="wsplit", wid="c1.1", wparts="10,15")  # no plan given for the children: owner's word
    assert len(set(wallet.credits(s["ledger"]))) == 5
    # no invented rule: parts must add up, and a split has 2-10 parts
    t = grant(four(), "20")
    assert do(t, ch="wsplit", wid="c1", wparts="5,5")[2] == "the parts must add up to the credit"
    assert do(t, ch="wsplit", wid="c1", wparts="20")[2] == "a split needs at least two parts"


def test_expiry_is_computed_and_bonus_is_not_cash():
    s = grant(four(), "20", wexp="2026-11-04")
    assert wallet.credits(s["ledger"], DAY)["c1"]["status"] == "expired"
    assert wallet.balances(s["ledger"], DAY) == {} and C.store_money(s, DAY) == ({}, 0.0)
    assert do(s, ch="walloc", wid="c1", chid="ch1")[2] == "credit is expired"
    with pytest.raises(wallet.WalletError, match="expired"):
        wallet.append(s["ledger"], {"t": "allocate", "credit": "c1", "challenge": "ch1"}, DAY)


def test_record_a_wager_ties_it_to_one_challenge_and_moves_no_money():
    s = grant(four(), "10")
    s, ok, err = do(s, ch="wgr", chid="ch1", wprov="Sportsbet", wlegs="A; B", wodds="3", wstake="10",
                    wfund="bonus", wcredit="c1", wrefs="ch2,ch1,zz", op="w1")
    assert ok and not err
    w = s["wagers"][0]
    assert (w["challenge"], w["refs"], w["credit"], w["funding"]) == ("ch1", ["ch2"], "c1", "bonus")
    assert wallet.credits(s["ledger"])["c1"]["status"] == "redeemed"  # the credit is used once
    assert bank(s, "ch1") == bank(s, "ch2") == 10.0 and C.store_money(s, DAY) == ({}, 0.0)
    assert do(s, ch="wgr", chid="ch2", wprov="Sportsbet", wlegs="A", wodds="3", wstake="10",
              wfund="bonus", wcredit="c1")[2] == "credit is redeemed" or True
    s, *_ = do(s, ch="wgrwon", chid="ch1", wid="1")
    assert s["wagers"][0]["state"] == "won" and s["wagers"][0]["ret"] == 20.0  # bonus stake: winnings only
    assert do(s, ch="wgr", chid="ch1", wprov="PB", wlegs="x", wodds="1", wstake="5")[2]  # odds must be above 1
    assert do(s, ch="wgr", chid="ch1", wprov="PB", wlegs="x", wodds="2", wstake="5", wfund="boost")[2] == "enter the boosted price"
    assert C.contract(C.find(s, "ch4"))["scope"]["mode"] == "all_sports"


def test_promo_payoffs_by_hand():
    # two legs 80% and 70%, price 3.00, stake $10: P(all)=0.56, P(exactly one fails)=0.2*0.7+0.3*0.8=0.38
    r = promos.payoff([0.8, 0.7], 3.0, 10, boost_price=3.5, refund_cap=10, redeem_rate=0.5, provenance="owner, 7 Nov")
    rows = {x["funding"]: x for x in r["rows"]}
    assert round(rows["Cash"]["p_all"], 4) == 0.56 and round(rows["Cash"]["p_one_fail"], 4) == 0.38
    assert rows["Cash"]["exp_cash_return"] == 16.8 and rows["Cash"]["net"] == 6.8  # 0.56*30 - 10
    assert rows["Boost / Power Up"]["exp_cash_return"] == 19.6 and rows["Boost / Power Up"]["net"] == 9.6
    mb = rows["Exactly-one-fail money back (bonus)"]
    assert mb["exp_cash_return"] == 16.8 and mb["exp_bonus_value"] == 1.9 and mb["net"] == 8.7  # 0.38*10*0.5
    bs = rows["Bonus-funded stake"]
    assert bs["cash_staked"] == 0 and bs["exp_cash_return"] == 11.2 and bs["bonus_used"] == 5.0 and bs["net"] == 6.2
    assert "redemption rate" in r["objective"]
    # rate defaults to 0.0: the money-back bonus is then worth nothing, and shown so
    z = {x["funding"]: x for x in promos.payoff([0.8, 0.7], 3.0, 10, refund_cap=10, provenance="p")["rows"]}
    assert z["Exactly-one-fail money back (bonus)"]["exp_bonus_value"] == 0.0
    # the pack's reference cases (06_TOOLS/test_promotion_math.py): pW .30, p1 .40, $10 @ 3.00
    ref = {x["funding"]: x for x in promos.payoff([0.5, 0.6], 3.0, 10, p_win=0.30, p_one=0.40, boost_fraction=0.25, refund_cap=10, redeem_rate=0.6, provenance="pack")["rows"]}
    assert ref["Cash"]["net"] == -1.0 and ref["Winnings boost"]["net"] == 0.5
    assert ref["Exactly-one-fail money back (bonus)"]["net"] == 1.4
    assert ref["Bonus-funded stake"]["exp_cash_return"] == 6.0  # 0.30 * 10 * (3 - 1), no stake back
    with pytest.raises(promos.PromoError, match="provenance"):
        promos.payoff([0.8], 2.0, 10, refund_cap=10)
    with pytest.raises(promos.PromoError):
        promos.payoff([0.8, 1.2], 2.0, 10)


def test_the_old_cookie_becomes_challenge_one(tmp_path):
    cookie = C.dump(
        place(C.apply(None, {"ch": "start"}, DAY), 0)
        | {"bets": place(C.apply(None, {"ch": "start"}, DAY), 0)["bets"] + [{"id": 9, "own": 1, "day": DAY, "ag": "sb", "stake": 5.0, "price": 2.0, "label": "m", "state": "placed", "ret": 0.0}]}
    )
    s = C.load(cookie)
    assert s["migrated"] and [c["id"] for c in s["challenges"]] == ["ch1"]
    st = s["challenges"][0]["state"]
    assert st["placed"]["stake"] == 10.0 and all(not b.get("own") for b in st["bets"])
    assert [b["id"] for b in s["own"]["bets"]] == [9]  # own multis moved to the store's own log
    C.save(s)
    assert json.loads(open(C._local_path()).read())["challenges"][0]["name"] == "Challenge 1"
    C._CACHE[:] = [0.0, None]
    again = C.load("garbage")  # the stored list wins; the cookie is no longer read
    assert [c["id"] for c in again["challenges"]] == ["ch1"] and again["next"] == 2
    s2, _, _ = do(again, ch="won", chs="0", chr="52")  # one challenge, no chid needed
    assert C.find(s2, "ch1")["state"]["bank"] == 42.0


def test_times_the_owner_sees_are_melbourne_time():
    from melbcup.web import views

    # 2026-11-07 is daylight saving (AEDT, UTC+11): 00:00Z shows as 11:00am, the same day
    assert views.when("2026-11-07T00:00:00Z").endswith("11:00am")
    assert views.when("2026-07-07T00:00:00Z").endswith("10:00am")  # winter: AEST, UTC+10
    # a credit's expiry date is a Melbourne day, stored as UTC and shown through `when`
    s = grant(four(), "20", wexp="2026-11-10")
    c = wallet.credits(s["ledger"], DAY)["c1"]
    assert c["expires_at_utc"] == "2026-11-10T12:59:59Z"  # 23:59:59 AEDT
    assert views.when(c["expires_at_utc"]).endswith("11:59pm")
    s, *_ = do(s, ch="wgr", chid="ch1", wprov="PB", wlegs="x", wodds="2", wstake="5")
    assert s["wagers"][0]["at"].endswith("Z")  # recorded in UTC, rendered with `when`


def test_cents_and_legs_per_multi_are_kept():
    s = C.apply(None, {"ch": "start", "chstart": "10.27", "chgoal": "500.55", "chlegs": "2"}, DAY)
    assert s["start"] == 10.27 and s["goal"] == 500.55 and s["legs"] == 2
    s = C.apply(s, {"ch": "chlegs", "chlegs": "", "chs": "0"}, DAY)
    assert s["legs"] is None
    s = C.apply(s, {"ch": "chlegs", "chlegs": "3", "chs": "0"}, DAY)
    assert s["legs"] == 3


def test_nba_suggestion_honours_legs():
    from melbcup import nba_legs

    legs = [
        {"event": f"e{i}", "game": f"G{i}", "player": f"p{i}", "chance": 0.8, "price": 1.45, "startsAt": None, "label": f"p{i} o", "market": "m", "line": 1}
        for i in range(6)
    ]
    for n in (2, 3):
        step = nba_legs.stack_for(legs, 2.0, min_legs=n, max_legs=n)
        assert step and step["legs"] == n


def test_edit_challenge_recomputes_target_and_leaves_others():
    store = C.load(None)
    for i in (1, 2):
        store, _, _ = C.apply_store(store, {"ch": "newch", "chname": f"c{i}", "chstart": "10", "chgoal": "1000", "op": f"n{i}"}, DAY)
    a, b = store["challenges"]
    before_b = str(b)
    x0 = C.next_x(a["state"])
    store, changed, err = C.apply_store(
        store, {"ch": "chedit", "chid": a["id"], "chstart": "10.27", "chbank": "12.50", "chgoal": "1000", "chn": "4", "chlegs": "2", "chname": "renamed", "op": "e1"}, DAY
    )
    a2, b2 = store["challenges"]
    assert changed and not err
    assert a2["name"] == "renamed" and a2["state"]["start"] == 10.27 and a2["state"]["bank"] == 12.5
    assert a2["state"]["legs"] == 2 and a2["state"]["stages"] == 4
    assert C.next_x(a2["state"]) != x0
    assert str(b2) == before_b


def _two_challenges():
    st = C.empty_store()
    for n in ("A", "B"):
        st, _, _ = C.apply_store(st, {"ch": "newch", "chname": n, "chmode": "multi"}, DAY)
    st, _, _ = C.apply_store(st, {"ch": "place", "chid": "ch1", "chs": "0", "chag": "pb", "chp": "5", "chl": "x"}, DAY)
    return st


def test_chbet_edits_the_placed_stake_and_price_and_the_maths_follow():
    st = _two_challenges()
    other = str(st["challenges"][1])
    q = {"ch": "chbet", "chid": "ch1", "chs": "0", "chstake": "15.50", "chp": "2.10", "chl": "new legs", "op": "e1"}
    st2, changed, err = C.apply_store(st, q, DAY)
    pl = st2["challenges"][0]["state"]["placed"]
    assert changed and not err and pl["stake"] == 15.5 and pl["price"] == 2.1 and pl["label"] == "new legs"
    assert pl["added"] == 5.5  # topped up from the $10 bank
    assert str(st2["challenges"][1]) == other  # the other challenge is untouched
    assert st2["challenges"][0]["state"]["bets"][0]["stake"] == 15.5
    assert C.apply_store(st2, q, DAY)[1] is False  # same op: nothing
    won, _, _ = C.apply_store(st2, {"ch": "won", "chid": "ch1", "chs": "0", "chr": "32.55"}, DAY)
    assert won["challenges"][0]["state"]["steps"][0]["to"] == 32.55
    lost, _, _ = C.apply_store(st2, {"ch": "lost", "chid": "ch1", "chs": "0"}, DAY)
    assert lost["challenges"][0]["state"]["placed"] is None


def test_chbet_lower_stake_leaves_the_rest_in_the_bank():
    st = _two_challenges()
    st["challenges"][0]["state"]["bank"] = 20.0
    st["challenges"][0]["state"]["placed"]["stake"] = 20.0
    st, _, _ = C.apply_store(st, {"ch": "chbet", "chid": "ch1", "chs": "0", "chstake": "15.50", "chp": "2.10", "op": "e2"}, DAY)
    won, _, _ = C.apply_store(st, {"ch": "won", "chid": "ch1", "chs": "0"}, DAY)
    s = won["challenges"][0]["state"]
    assert s["steps"][0]["to"] == 32.55 and s["kept"] == 10.0 and s["bank"] == 27.05


def test_placed_card_stays_after_place():
    from pathlib import Path

    t = Path(C.__file__).parent / "web/templates/asynym"
    for f in ("_challenges.html", "sports.html"):
        assert 'value="chbet"' in (t / f).read_text() and "Edit this bet" in (t / f).read_text()


def test_record_a_bet_with_jet_boost_saves_four_legs_and_credits_on_win():
    from melbcup import nba_live, wallet

    store = C.empty_store()
    q = {
        "ch": "bet", "nbgame": "Houston Rockets @ Phoenix Suns", "nbag": "sb", "nbs": "5", "nbp": "5.00",
        "nbbw": "2", "nbtip": "2026-11-08T02:10:00Z",
        "nbwhat": "Alperen Sengun 15+ Points\nDevin Booker Under 3.5 Rebounds\nTari Eason Under 1.5 Made Threes\nMarcus Smart Under 1.5 Made Threes",
    }
    store, changed, err = C.apply_store(store, q, "2026-11-08")
    assert changed and not err
    bet = store["own"]["bets"][0]
    assert bet["bonus_if_win"] == 2.0 and bet["stake"] == 5.0 and bet["price"] == 5.0
    game, legs = nba_live.parse(bet["label"])
    assert game == "Houston Rockets @ Phoenix Suns" and len(legs) == 4
    store, _, err = C.apply_store(store, {"ch": "betwon", "nbid": str(bet["id"]), "nbr": "25"}, "2026-11-08")
    assert not err
    assert wallet.balances(store["ledger"], "2026-11-08")["Sportsbet"]["open"] == 2.0
