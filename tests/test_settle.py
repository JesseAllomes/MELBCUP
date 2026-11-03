"""Settling the owner's recorded bets, and the day profit/loss bar and the lines that show it."""

import json
from datetime import date
from urllib.parse import quote

import pytest
from test_racecard import FakeBoard, _models

from melbcup.bets.allocate import Placed
from melbcup.bets.multis import multi_key
from melbcup.bets.settle import settle_all, settle_bet, signed
from melbcup.config import load_settings
from melbcup.domain import Race, RaceResult, Runner, RunnerPrices
from melbcup.web.views import Views

CUP_DAY = date(2026, 11, 3)


def race(number=1, finish=None, places_paid=3, name="Furphy Sprint", n=9):
    r = Race("Flemington", CUP_DAY, number, name, places_paid=places_paid)
    r.runners = [Runner(i, f"Horse {i}") for i in range(1, n + 1)]
    if finish is not None:
        r.result = RaceResult("final", finish, {}, {})
    return r


def r1():
    """1st Amelia's Affair (6), 2nd Royal Press (1), 3rd La La Lilly (8); 9 runners, 3 paid."""
    r = race(finish={6: 1, 1: 2, 8: 3})
    r.prices[1] = RunnerPrices(1, sportsbet_win=4.6, sportsbet_place=1.62)
    r.prices[2] = RunnerPrices(2, sportsbet_win=2.7, betfair_win=1.97)
    return {1: r}


R1_BETS = [
    Placed(1, "win", 2, "sportsbet", 3, 2.70),
    Placed(1, "each_way", 1, "sportsbet", 8, 4.60),
    Placed(1, "win", 2, "betfair", 5, 1.97),
]


def test_r1_day():
    day = settle_all(R1_BETS, r1())
    assert [(b.status, b.returns, b.profit) for b in day.bets] == [
        ("settled", 0.0, -3.0),
        ("settled", 6.48, -1.52),  # win half lost; $4 place at 1.62
        ("settled", 0.0, -5.0),
    ]
    assert day.profit == -9.52 and day.settled == 3 and day.pending == 0
    assert day.bonus == 0
    assert signed(day.profit) == "-$9.52"


def test_win_and_place_pay_from_the_finish():
    races = r1()
    races[1].prices[6] = RunnerPrices(6, sportsbet_win=5.0, sportsbet_place=1.8)
    won = settle_bet(Placed(1, "win", 6, "sportsbet", 10), races)  # current price
    assert won.returns == 50.0 and won.profit == 40.0
    placed = settle_bet(Placed(1, "place", 8, "sportsbet", 10, 1.5), races)  # price taken
    assert placed.profit == 5.0
    missed = settle_bet(Placed(1, "place", 3, "sportsbet", 10, 1.5), races)
    assert missed.profit == -10.0


def test_each_way_place_price_falls_back_to_a_quarter_odds():
    races = r1()
    races[1].prices[1].sportsbet_place = None
    s = settle_bet(Placed(1, "each_way", 1, "sportsbet", 8, 5.0), races)
    assert s.returns == pytest.approx(4 * (1 + 4.0 / 4))  # $4 at 1 + (5 - 1) / 4 = 2.0


def test_no_result_is_pending_and_exotics_are_not_settled():
    races = {1: race()}
    assert settle_bet(Placed(1, "win", 2, "sportsbet", 5, 3.0), races).status == "pending"
    quin = settle_bet(Placed(1, "quinella", 0, "sportsbet", 5), r1())
    assert quin.status == "manual" and "not settled by the app" in quin.note.lower()
    bets = [Placed(1, "win", 2, "sportsbet", 5, 3.0), Placed(1, "quinella", 0, "sportsbet", 5)]
    day = settle_all(bets, r1())
    assert (day.settled, day.pending) == (1, 1)


def test_betfair_winner_pays_after_commission():
    s = settle_bet(Placed(1, "win", 6, "betfair", 10, 3.0), r1())
    assert s.returns == pytest.approx(10 + 20 * 0.92) and s.profit == pytest.approx(18.4)


def test_betfair_second_gets_cash_back():
    s = settle_bet(Placed(1, "win", 1, "betfair", 10, 4.0), r1())
    assert s.profit == 0.0 and s.returns == 10.0 and s.bonus == 0
    # a bet at another bookmaker gets nothing
    assert settle_bet(Placed(1, "win", 1, "sportsbet", 10, 4.0), r1()).returns == 0.0


def test_sportsbet_early_race_second_or_third_earns_a_bonus_bet_not_cash():
    s = settle_bet(Placed(1, "win", 1, "sportsbet", 80, 4.6), r1())
    assert s.bonus == 50 and s.returns == 0 and s.profit == -80
    assert settle_bet(Placed(1, "win", 8, "sportsbet", 20, 9.0), r1()).bonus == 20
    assert settle_bet(Placed(1, "win", 2, "sportsbet", 20, 9.0), r1()).bonus == 0
    later = {3: race(3, {6: 1, 1: 2, 8: 3})}  # race 3: no promo
    assert settle_bet(Placed(3, "win", 1, "sportsbet", 20, 4.6), later).bonus == 0


def test_pointsbet_cup_second_pays_as_a_winner():
    cup = {7: race(7, {6: 1, 1: 2}, name="Lexus Melbourne Cup")}
    assert settle_bet(Placed(7, "win", 1, "pointsbet", 10, 6.0), cup).profit == 50.0
    other = {7: race(7, {6: 1, 1: 2}, name="Some Stakes")}
    assert settle_bet(Placed(7, "win", 1, "pointsbet", 10, 6.0), other).profit == -10.0


def test_multi_settles_when_every_leg_has_a_result():
    races = {1: race(1, {6: 1}), 2: race(2, {4: 1, 5: 2, 7: 3}, places_paid=3)}
    key = multi_key([(1, 6, "win"), (2, 7, "place")])
    won = settle_bet(Placed(1, "multi", key, "sportsbet", 10, 3.0), races)
    assert won.profit == 20.0
    miss = multi_key([(1, 6, "win"), (2, 9, "place")])
    lost = settle_bet(Placed(1, "multi", miss, "sportsbet", 10, 3.0), races)
    assert lost.profit == -10.0
    del races[2].result
    races[2].result = None
    assert settle_bet(Placed(1, "multi", key, "sportsbet", 10, 3.0), races).status == "pending"


# -- the bar and the lines -------------------------------------------------------------------


def views_with(finish=None):
    models = _models()
    r = models[0].race
    if finish:
        r.result = RaceResult("final", finish, {}, {})
        r.places_paid = 3
    for n in (1, 2, 3):
        r.prices[n].sportsbet_place = 1.62
    return Views(load_settings({"APP_PASSWORD": "x"}), FakeBoard(models))


def jar(*recs):
    return {"placed": quote(json.dumps(list(recs), separators=(",", ":")))}


D = "2026-11-03"


def test_bar_fills_left_for_a_loss_and_right_for_a_profit():
    views = views_with({3: 1, 1: 2, 2: 3})
    both = jar([D, 1, "w", 2, "sb", 3, 2.7], [D, 1, "w", 2, "bf", 5, 1.97])
    loss = views.page("/race/1", {}, both)
    assert "Today -$8.00" in loss and 'class="pnl-fill neg"' in loss
    assert "2 settled, 0 pending" in loss
    assert "LOST −$3.00" in loss and "Your bets this race: <b" in loss and "-$8.00" in loss
    win = views.page("/race/1", {}, jar([D, 1, "w", 3, "sb", 10, 3.0]))
    assert "Today +$20.00" in win and 'class="pnl-fill pos"' in win and "WON +$20.00" in win


def test_bar_shows_pending_and_partial_each_way():
    views = views_with({3: 1, 1: 2, 2: 3})
    recs = jar([D, 1, "e", 1, "sb", 8, 4.6], [D, 2, "w", 1, "sb", 5, 3.0])
    html = views.page("/race/1", {}, recs)
    assert "BACK $6.48 · −$1.52" in html
    assert "1 settled, 1 pending" in html and "Today -$1.52" in html


def test_bar_absent_without_records():
    html = views_with({3: 1, 1: 2, 2: 3}).page("/race/1", {}, {})
    assert "pnl-track" not in html and "Today" not in html


def test_bonus_bet_is_shown_apart_from_profit():
    views = views_with({3: 1, 1: 2, 2: 3})
    html = views.page("/race/1", {}, jar([D, 1, "w", 1, "sb", 10, 4.0]))
    assert "bonus bet $10" in html and "Today -$10.00" in html


def test_each_way_uses_the_place_price_taken():
    """An 8-element record carries each way's place price: Royal Press $8 EW at 4.60/1.62, 2nd."""
    from melbcup.web.racecard import parse_placed

    recs = parse_placed('[["2026-11-03",1,"e",1,"sb",8,4.6,1.62]]', date(2026, 11, 3))
    assert recs and recs[0].price == 4.6 and recs[0].place_price == 1.62
    six = parse_placed('[["2026-11-03",1,"w",2,"sb",3]]', date(2026, 11, 3))
    assert six and six[0].place_price is None


def test_final_picks_from_the_picks_cookie_show_after_the_result():
    views = views_with({3: 1, 1: 2, 2: 3})
    saved = [[D, 1, "w", 3, "sb", 10, 3.0], [D, 1, "w", 1, "sb", 4, 2.0]]
    picks = {"picks": quote(json.dumps(saved))}
    html = views.page("/race/1", {}, picks)
    assert "App's final picks" in html and "WON +$20.00" in html and "LOST −$4.00" in html
    assert "App's picks this race: <b class=\"pos\">+$16.00</b>" in html
    assert "App's final picks" not in views.page("/race/1", {}, {})  # nothing saved: nothing shown
    open_ = views_with()  # no result yet: not shown
    assert "App's final picks" not in open_.page("/race/1", {}, picks)
    assert 'data-pick="' in open_.page("/race/1", {}, {})  # the open card carries what to save


# -- extra bets: hand-recorded multis and other bets ---------------------------------------


def _x_races():
    r1 = race(1, finish={6: 1, 1: 2, 8: 3})
    r2 = race(2, finish={3: 1, 4: 2, 5: 3, 9: 4}, places_paid=3)
    r3 = race(3)  # no result yet
    return {1: r1, 2: r2, 3: r3}


def _mx(legs, stake=5.0, odds=12.4):
    from melbcup.bets.settle import Extra

    return Extra("multi", tuple(legs), "sportsbet", stake, odds)


def test_extra_multi_wins_loses_pending():
    from melbcup.bets.settle import settle_extra

    races = _x_races()
    won = settle_extra(_mx([(1, 6, "win"), (2, 5, "place")]), races)
    assert (won.status, won.returns, won.profit) == ("settled", 62.0, 57.0)
    lost = settle_extra(_mx([(1, 6, "win"), (2, 9, "place"), (3, 1, "win")]), races)
    assert (lost.status, lost.returns, lost.profit) == ("settled", 0.0, -5.0)  # lost early
    wait = settle_extra(_mx([(1, 6, "win"), (3, 1, "win")]), races)
    assert wait.status == "pending" and wait.profit == 0.0
    assert settle_extra(_mx([(1, 6, "win"), (7, 1, "win")]), races).status == "pending"


def test_extra_four_leg_multi_with_place_leg_and_no_commission():
    from melbcup.bets.settle import Extra, settle_extra

    races = _x_races()
    races[3] = race(3, finish={2: 1, 7: 2})
    legs = [(1, 6, "win"), (1 + 1, 4, "place"), (3, 2, "win")]
    four = (*legs, (4, 1, "win"))
    races[4] = race(4, finish={1: 1})
    x = Extra("multi", four, "betfair", 10.0, 8.0)
    s = settle_extra(x, races)
    assert (s.status, s.returns) == ("settled", 80.0)  # no 8% off: a bookmaker multi
    races[4] = race(4, finish={2: 1, 1: 4})
    assert settle_extra(x, races).returns == 0.0


def test_extra_other_bet_settles_on_typed_return():
    from melbcup.bets.settle import Extra, settle_extra

    base = Extra("other", (), "sportsbet", 10.0, 6.0, "Quinella R5 3-7")
    assert settle_extra(base, {}).status == "pending"
    got = settle_extra(Extra("other", (), "sportsbet", 10.0, 6.0, "q", 45.5), {})
    assert (got.status, got.profit) == ("settled", 35.5)
    zero = settle_extra(Extra("other", (), "sportsbet", 10.0, 6.0, "q", 0.0), {})
    assert (zero.status, zero.profit) == ("settled", -10.0)
