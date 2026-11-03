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


# the PointsBet and Sportsbet promos these tests were written for (Betfair's is tested below)
BOOKIE_PROMOS = tuple(x for x in PROMOS if x.bookmaker != "betfair")


def picks(promos=BOOKIE_PROMOS, pointsbet=True, **boost):
    return build_picks(day_models(**boost), 200, pointsbet, promos)


def wins(routed):
    return {r.pick.race: r for r in routed if r.pick.kind == "win"}


def summary(routed):
    return [(r.pick.race, r.pick.kind, r.account, r.pick.stake, r.price) for r in routed]


def views(env):
    return Views(load_settings({"APP_PASSWORD": "x"} | env), FakeBoard(day_models()))


def no_clock(html):
    html = re.sub(r'<div class="alertbar".*?id="alert-data">.*?</script>', "", html, flags=re.S)
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


# -- PointsBet daily promos: booster and Pay Back multi (PROMOS=1 + POINTSBET=1 + PB amount) ----

QUERY = {"sb": "100", "bf": "20", "pb": "50"}


def pb_models():
    """The day's races with PointsBet place prices and a different PointsBet price per race."""
    models = day_models()
    for m in models:
        for a in m.runners.values():  # the fixture has no place chances: top three of seven
            a.place = min(0.95, 2.4 * a.win)
        for p in m.race.prices.values():
            p.pointsbet_place = round(1 + (p.pointsbet_win - 1) / 3.5, 2)
            p.pointsbet_win = round(p.pointsbet_win * (1 + 0.02 * m.race.number), 2)
    return models


def pb_views(env, models=None):
    models = models or pb_models()
    return Views(load_settings({"APP_PASSWORD": "x"} | env), FakeBoard(models))


def pb_card(models, pb, promos):
    from melbcup.web.racecard import build_day

    d = build_picks(models, 200, bool(pb), PROMOS)  # the picks are the same either way
    open_races = {rp.model.race.number for rp in d.races}
    return build_day(d, 100, 20, [], open_races, models[0].race.race_date, pb, promos)


@pytest.mark.parametrize(
    "env,query",
    [
        ({"PROMOS": "1"}, QUERY),  # no POINTSBET
        ({"POINTSBET": "1"}, QUERY),  # no PROMOS
        ({"POINTSBET": "1", "PROMOS": "1"}, {"sb": "100", "bf": "20", "pb": "0"}),
    ],
)
def test_pointsbet_daily_promos_need_both_switches_and_an_amount(env, query):
    for path in ("/", "/race/1", "/race/7"):
        page = pb_views(env).page(path, query, {})
        assert "PB booster" not in page and "Pay Back" not in page
    models = pb_models()
    pb = 0.0 if env.get("POINTSBET") and env.get("PROMOS") else None
    card = pb_card(models, pb, bool(env.get("PROMOS")))
    assert card.payback is None
    assert not any(x.booster for rc in card.races for x in rc.board)


def test_off_card_is_identical_to_without_the_daily_promos():
    models = pb_models()
    assert pb_card(models, 50.0, False) == pb_card(models, 50.0, False)
    on = pb_card(models, 50.0, True)
    off = pb_card(models, 50.0, False)
    assert off.payback is None and on.payback is not None
    for a, b in zip(on.races, off.races, strict=True):  # only the booster mark differs
        for x, y in zip(a.board, b.board, strict=True):
            x.booster = x.booster_note = ""
            assert x == y
    assert on.multis == off.multis
    page = pb_views({"POINTSBET": "1"}).page("/", QUERY, {})
    assert "Pay Back" not in page and "PB booster" not in page


def test_booster_marks_the_one_pointsbet_single_with_the_biggest_expected_gain():
    models = pb_models()
    card = pb_card(models, 50.0, True)
    lines = [x for rc in card.races for x in rc.board if x.account == "pointsbet"]
    assert lines
    marked = [x for rc in card.races for x in rc.board if x.booster]
    assert len(marked) == 1 and marked[0].booster == "PB booster: use here"
    assert "racing-singles booster" in marked[0].booster_note and marked[0].account == "pointsbet"
    by_race = {m.race.number: m.race for m in models}

    def gain(x):
        pr = by_race[x.race].prices[x.number]
        price = pr.pointsbet_win if x.kind == "win" else pr.pointsbet_place
        return x.stake * x.chance * (price - 1)

    eligible = [x for x in lines if x.kind in ("win", "place") and x.stake]
    assert marked[0] is max(eligible, key=gain)
    page = pb_views({"POINTSBET": "1", "PROMOS": "1"}).page("/", QUERY, {})
    race_pages = [
        pb_views({"POINTSBET": "1", "PROMOS": "1"}).page(f"/race/{n}", QUERY, {})
        for n in (1, 2, 3, 7)
    ]
    assert sum(p.count("PB booster: use here") for p in race_pages) == 1
    assert "PB booster" not in page  # the day page lists races, not their lines


def test_booster_shows_nothing_when_no_single_goes_to_pointsbet():
    models = pb_models()
    for m in models:  # PointsBet pays less than Sportsbet everywhere: nothing is routed there
        for p in m.race.prices.values():
            p.pointsbet_win, p.pointsbet_place = None, None
    card = pb_card(models, 50.0, True)
    assert not any(x.booster for rc in card.races for x in rc.board)
    assert card.payback is None  # no PointsBet prices, no multi


def brute_payback(models):
    from itertools import combinations, product

    from melbcup.bets.multis import MIN_LEG_PROB

    legs = {}
    for m in models:
        for a in m.ranked():
            pr = m.race.prices[a.number]
            for kind, p, price in (
                ("win", a.win, pr.pointsbet_win),
                ("place", a.place, pr.pointsbet_place),
            ):
                if price and p >= MIN_LEG_PROB:
                    leg = (m.race.number, a.number, kind, p, price)
                    legs.setdefault(m.race.number, []).append(leg)
    best = None
    for size in (2, 3):
        for races in combinations(sorted(legs), size):
            for combo in product(*(legs[r] for r in races)):
                p = price = 1.0
                for leg in combo:
                    p *= leg[3]
                    price *= leg[4]
                if p < 0.25:
                    continue
                ev = p * price + 0.75 * (1 - p) - 1
                if best is None or ev > best[0] + 1e-12:
                    best = (ev, [leg[:3] for leg in combo], p, price)
    return best


def test_payback_multi_is_the_highest_ev_pointsbet_multi_with_chance_at_least_a_quarter():
    from melbcup.bets.promos import PB_PAYBACK_BONUS, PB_PAYBACK_MAX, payback_multi

    assert (PB_PAYBACK_MAX, PB_PAYBACK_BONUS) == (50.0, 0.75)
    models = pb_models()
    m, ev = payback_multi(models)
    want = brute_payback(models)
    assert m.prob >= 0.25 and 2 <= len(m.legs) <= 3
    assert len({leg.race for leg in m.legs}) == len(m.legs)
    assert ev == pytest.approx(want[0]) and m.prob == pytest.approx(want[2])
    assert m.price == pytest.approx(want[3])
    by_race = {x.race.number: x.race for x in models}
    for leg in m.legs:  # PointsBet's prices, not Sportsbet's
        pr = by_race[leg.race].prices[leg.number]
        assert leg.price == (pr.pointsbet_place if leg.kind == "place" else pr.pointsbet_win)
    assert ev == pytest.approx(m.prob * m.price + 0.75 * (1 - m.prob) - 1)


def test_payback_card_is_on_the_day_page_and_takes_no_stake():
    from melbcup.bets.promos import payback_multi

    models = pb_models()
    m, ev = payback_multi(models)
    page = pb_views({"POINTSBET": "1", "PROMOS": "1"}).page("/", QUERY, {})
    assert page.count("PointsBet Pay Back multi") >= 1 and "up to $50 on PointsBet" in page
    assert page.index("Multi picks for the day") < page.index("PointsBet Pay Back multi")
    assert f"{ev:+.2f} per $1 with the pay back" in page
    on = pb_card(models, 50.0, True)
    off = pb_card(models, 50.0, False)
    assert on.payback.stake == 0 and on.total == off.total  # no money taken from the day


def test_payback_multi_is_fast_on_a_ten_race_card():
    import time

    from melbcup.bets.promos import payback_multi

    models = [race_model(n) for n in range(1, 11)]
    for m in models:
        for a in m.runners.values():
            a.place = min(0.95, 2.4 * a.win)
        for p in m.race.prices.values():
            p.pointsbet_place = round(1 + (p.pointsbet_win - 1) / 3.5, 2)
    t = time.perf_counter()
    assert payback_multi(models) is not None
    assert time.perf_counter() - t < 0.2


def test_betfair_cash_back_2nd_is_a_betfair_promo_bet_at_betfairs_price():
    """Betfair cash back if 2nd (cash, after commission): every race, placed on Betfair, at
    least Betfair's $5 minimum, never above its money."""
    from melbcup.bets.allocate import BETFAIR_MIN
    from melbcup.bets.promos import BF_CASHBACK_MAX

    bf_only = tuple(x for x in PROMOS if x.bookmaker == "betfair")
    d = picks(promos=bf_only, pointsbet=False, r1={3: 7.5})
    rp = d.races[0]
    assert rp.promo is not None and rp.promo.promo.promo.key == "bf_cash_back_2nd"
    r = wins(allocate_accounts(d, 100, 20))[1]
    assert r.account == "betfair" and r.pick.single.promo is not None
    assert r.price == rp.model.race.prices[r.pick.single.number].betfair_win
    assert BETFAIR_MIN <= r.pick.stake <= min(BF_CASHBACK_MAX, 20)
    none_left = wins(allocate_accounts(d, 100, 0))[1]
    assert none_left.account != "betfair"
