"""Bookmaker promos as real bets, behind PROMOS=1 (melbcup/bets/promos.py).

Off (the default) the app is as it was: same page, same allocation, no "Promo" text. On, a promo
that beats the race's plain Win pick (worst-case EV, offers.py) is that race's Win bet: staked,
routed to its bookmaker and labelled.
"""

import re
from datetime import datetime, timedelta

import pytest
from test_offers import model_of
from test_racecard import FakeBoard

from melbcup.bets import build_picks
from melbcup.bets.allocate import allocate_accounts
from melbcup.bets.offers import (
    MIN_EV_BUFFER,
    MoneyBack,
    PaysAsWinner,
    check_offer,
    ev_per_dollar,
    leg_chances,
    position_probs,
)
from melbcup.bets.promos import PB_MAX_STAKE, PROMOS, SB_MAX_STAKE
from melbcup.config import MELBOURNE, load_settings
from melbcup.web.views import Views

WIN = [0.30, 0.22, 0.15, 0.12, 0.09, 0.07, 0.05]
PB_SHOWN = "Promo: Run 2nd, You Win"
SB_SHOWN = "Promo: bonus back 2nd-3rd"


def race_model(number, name=None, *, boost=None):
    """A market-priced race at Sportsbet paying 90% of fair; PointsBet pays 25% more. ``boost``
    {runner: Betfair price} makes a plain Win pick that is better than any promo."""
    m = model_of(WIN, [round(0.9 / p, 2) for p in WIN], number=number)
    m.race.name = name or f"Race {number} Stakes"
    m.race.start_time = datetime(2026, 11, 3, 11, 45, tzinfo=MELBOURNE) + timedelta(
        minutes=35 * number
    )
    for p in m.race.prices.values():
        p.pointsbet_win = round(p.sportsbet_win * 1.25, 2)
    for n, price in (boost or {}).items():
        m.race.prices[n].betfair_win = price
    return m


def day_models(**boost):
    return [
        race_model(1, boost=boost.get("r1")),
        race_model(2, boost=boost.get("r2")),
        race_model(3),
        race_model(7, "Lexus Melbourne Cup"),
    ]


def picks(promos=PROMOS, pointsbet=True, **boost):
    return build_picks(day_models(**boost), 200, pointsbet, promos)


def wins(routed):
    return {r.pick.race: r for r in routed if r.pick.kind == "win"}


def summary(routed):
    return [(r.pick.race, r.pick.kind, r.account, r.pick.stake, r.price) for r in routed]


def views(env):
    return Views(load_settings({"APP_PASSWORD": "x"} | env), FakeBoard(day_models()))


def no_clock(html):
    return re.sub(r"in \d+ h \d+ min|in \d+ min", "", html)


# -- the switch ---------------------------------------------------------------------------------


def test_switch_is_off_unless_promos_is_1():
    assert load_settings({}).promos is False
    assert load_settings({"PROMOS": "0"}).promos is False
    assert load_settings({"PROMOS": "true"}).promos is False
    assert load_settings({"PROMOS": " 1 "}).promos is True


@pytest.mark.parametrize("pointsbet", [False, True])
def test_off_page_and_allocation_are_unchanged(pointsbet):
    off = picks(promos=None, pointsbet=pointsbet)
    assert all(rp.promo is None for rp in off.races)
    empty = picks(promos=(), pointsbet=pointsbet)
    pb = 50 if pointsbet else None
    assert summary(allocate_accounts(off, 100, 20, pointsbet_budget=pb)) == summary(
        allocate_accounts(empty, 100, 20, pointsbet_budget=pb)
    )
    env = {"POINTSBET": "1"} if pointsbet else {}
    for path in ("/", "/race/1", "/race/2", "/race/7"):
        page = views(env).page(path, {"sb": "100", "bf": "20", "pb": "50"}, {})
        assert "Promo" not in page and "bonus back" not in page
        assert no_clock(page) == no_clock(
            views(env | {"PROMOS": "0"}).page(path, {"sb": "100", "bf": "20", "pb": "50"}, {})
        )


# -- bets ---------------------------------------------------------------------------------------


def test_cup_win_bet_is_the_pointsbet_promo_at_the_pointsbet_price():
    d = picks()
    cup = d.races[3]
    assert cup.promo is not None and cup.promo.promo.promo.key == "pb_run_2nd"
    r = wins(allocate_accounts(d, 100, 20, pointsbet_budget=50))[7]
    assert r.account == "pointsbet" and r.pick.good_price
    pb_price = cup.model.race.prices[r.pick.single.number].pointsbet_win
    assert r.price == pb_price and r.pick.single.price == pb_price
    assert 0 < r.pick.stake <= PB_MAX_STAKE


def test_promo_beats_plain_pick_in_races_1_and_2_and_goes_to_sportsbet():
    off = wins(allocate_accounts(picks(promos=None), 100, 20, pointsbet_budget=50))
    on = wins(allocate_accounts(picks(), 100, 20, pointsbet_budget=50))
    for n in (1, 2):
        r = on[n]
        assert r.account == "sportsbet" and r.pick.single.promo is not None
        assert r.pick.good_price and 0 < r.pick.stake <= SB_MAX_STAKE
        assert r.price == r.pick.single.sportsbet
        assert off[n].pick.single.promo is None
    assert on[3].pick.single.promo is None


def test_promo_replaces_a_different_plain_runner():
    """Race 1's plain Win pick is runner 3 (Betfair pays a little over fair); the promo is
    better value on runner 1, so runner 1 becomes the Win bet."""
    plain = picks(promos=None, pointsbet=False, r1={3: 7.5})
    assert wins(allocate_accounts(plain, 100, 20))[1].pick.single.number == 3
    on = wins(allocate_accounts(picks(pointsbet=False, r1={3: 7.5}), 100, 20))[1]
    assert on.pick.single.number == 1 and on.account == "sportsbet"
    assert on.pick.single.promo is not None


def test_plain_pick_stays_when_it_is_better_than_the_promo():
    d = picks(r2={2: 8.0})  # Betfair 8.0 for runner 2: plain EV +64%, far above any promo
    assert d.races[1].promo is None
    plain = wins(allocate_accounts(picks(promos=None, r2={2: 8.0}), 500, 100, pointsbet_budget=200))
    on = wins(allocate_accounts(d, 500, 100, pointsbet_budget=200))  # money to spare: same stake
    assert (on[2].pick.single.number, on[2].account, on[2].pick.stake, on[2].price) == (
        plain[2].pick.single.number,
        plain[2].account,
        plain[2].pick.stake,
        plain[2].price,
    )
    assert on[2].pick.single.promo is None


def test_pointsbet_promo_needs_the_pointsbet_account():
    d = picks(pointsbet=False)
    assert d.races[3].promo is None and d.races[0].promo is not None
    routed = allocate_accounts(d, 100, 20)  # the two-account path
    assert wins(routed)[1].account == "sportsbet"
    assert wins(routed)[7].account != "pointsbet"


def test_promo_never_goes_to_betfair_even_when_betfair_pays_more():
    d = picks(r1={1: 9.0})  # Betfair far above Sportsbet on the promo runner
    r = wins(allocate_accounts(d, 100, 100, pointsbet_budget=50))
    for n in (1, 7):
        if r[n].pick.single.promo is not None:
            assert r[n].account != "betfair"


@pytest.mark.parametrize("sb,bf,pb", [(100, 20, 50), (8, 0, 2), (3, 0, 0.0), (500, 0, 500)])
def test_stakes_never_exceed_the_promo_maximum_or_the_account(sb, bf, pb):
    d = picks()
    routed = allocate_accounts(d, sb, bf, pointsbet_budget=pb)
    spent = {"sportsbet": 0, "betfair": 0, "pointsbet": 0}
    for r in routed:
        spent[r.account] += r.pick.stake
        promo = getattr(r.pick.single, "promo", None)
        if promo is not None:
            assert r.account == promo.account
            assert r.pick.stake <= promo.promo.max_stake
    assert spent["sportsbet"] <= sb and spent["pointsbet"] <= pb and spent["betfair"] <= bf


def test_placed_promo_bet_keeps_its_stake_account_and_price():
    from melbcup.bets.allocate import Placed

    d = picks()
    number = d.races[3].promo.number
    routed = allocate_accounts(
        d, 100, 20, [Placed(7, "win", number, "pointsbet", 4)], pointsbet_budget=50
    )
    held = wins(routed)[7]
    assert held.placed and held.account == "pointsbet" and held.pick.stake == 4
    assert held.pick.single.promo is not None and held.pick.good_price


# -- the page -----------------------------------------------------------------------------------


def test_on_page_labels_the_promo_bets():
    v = views({"POINTSBET": "1", "PROMOS": "1"})
    q = {"sb": "100", "bf": "20", "pb": "50"}
    for n in (1, 2):
        page = v.page(f"/race/{n}", q, {})
        assert page.count(SB_SHOWN) == 1 and PB_SHOWN not in page
        assert "per $1 in the worst case" in page and "Sportsbet</small>" in page
    cup = v.page("/race/7", q, {})
    assert cup.count(PB_SHOWN) == 1 and "PointsBet</small>" in cup
    assert "A note only" not in cup  # the Win bet is the promo bet: no separate note
    assert "Promo:" not in v.page("/race/3", q, {})


def test_on_without_a_pointsbet_amount_still_shows_the_sportsbet_promo():
    v = views({"PROMOS": "1"})
    assert v.page("/race/2", {"sb": "100", "bf": "20"}, {}).count(SB_SHOWN) == 1
    assert PB_SHOWN not in v.page("/race/7", {"sb": "100", "bf": "20"}, {})


# -- PaysAsWinner -------------------------------------------------------------------------------


def test_pays_as_winner_ev_is_top_two_chance_times_price_less_one():
    win = {n: p for n, p in enumerate(WIN, 1)}
    pos = position_probs(win)
    offer = PaysAsWinner(5.0)
    for runner in (1, 4, 7):
        c = leg_chances(offer, pos, runner)
        top2 = pos.top(runner, 2)
        assert c["win"] + c["also_paid"] == pytest.approx(top2)
        assert ev_per_dollar(offer, c) == pytest.approx(top2 * 5.0 - 1.0)
        assert ev_per_dollar(offer, c, 37.0) == pytest.approx(top2 * 5.0 - 1.0)  # not capped


def test_pays_as_winner_paying_only_on_a_win_is_a_plain_bet():
    offer = PaysAsWinner(4.0, frozenset({1}))
    assert [leg.name for leg in offer.legs()] == ["win"]
    assert ev_per_dollar(offer, {"win": 0.3}) == pytest.approx(0.3 * 4.0 - 1.0)


def test_pays_as_winner_rejects_bad_terms():
    for bad in ({}, {2}, {1, 6}):
        with pytest.raises(ValueError):
            PaysAsWinner(3.0, frozenset(bad))
    with pytest.raises(ValueError):
        PaysAsWinner(1.0)


def test_pays_as_winner_check_offer_bets_only_above_the_buffer():
    m = model_of(WIN, [round(0.9 / p, 2) for p in WIN])
    good = check_offer(m, 7, PaysAsWinner(m.race.prices[7].sportsbet_win), 200)
    assert good.verdict == "bet" and good.stake > 0 and good.min_ev >= MIN_EV_BUFFER
    short = check_offer(m, 1, PaysAsWinner(1.5), 200)  # 30% to win, 1.5: top two ~ 0.5 x 1.5 < 1
    assert short.verdict == "hold" and short.stake == 0 and short.min_ev < MIN_EV_BUFFER


def test_sportsbet_promo_is_the_offers_money_back():
    promo = next(p for p in PROMOS if p.bookmaker == "sportsbet")
    offer = promo.offer(3.0)
    assert offer == MoneyBack(3.0, frozenset({2, 3}), 50, 0.75)
    assert promo.races == (1, 2)
