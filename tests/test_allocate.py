"""The day budget shared over every race's win, place and each-way pick."""

from test_bets import FIELD, make_model

from melbcup.bets import build_picks
from melbcup.bets.allocate import (
    RACE_CAP,
    SPORTSBET_ONLY,
    Placed,
    allocate,
    allocate_accounts,
    race_picks,
)

PRICES = [3.5, 3.0, 6.0, 10.0, 13.0, 15.0]
PLACES = [1.4, 1.5, 2.0, 2.5, 3.0, 3.5]
SHORT = [2.4, 3.2, 5.5, 9.0, 11.0, 13.0]  # nothing is value here


def day(prices, n=8, budget=200):
    return build_picks([make_model(i, FIELD, prices, PLACES) for i in range(1, n + 1)], budget)


def total(picks, d):
    fixed = sum(e.outlay or 0 for rp in d.races for e in rp.first_fours + rp.trifectas
                if e.recommended)
    fixed += sum(q.outlay or 0 for q in d.quaddies if q.recommended)
    return sum(p.stake for p in picks) + fixed


def test_every_race_gets_its_three_picks_and_the_day_stays_in_budget():
    d = day(SHORT)
    picks = allocate(d, 200)
    assert {p.race for p in picks} == set(range(1, 9))
    assert all(p.stake > 0 for p in picks)
    assert 190 <= total(picks, d) <= 200


def test_likelier_bets_get_more():
    picks = [p for p in allocate(day(SHORT), 200) if p.race == 1]
    by = {p.kind: p for p in picks}
    assert by["place"].chance > by["win"].chance and by["place"].stake > by["win"].stake


def test_no_race_takes_more_than_the_cap():
    d = day(SHORT, n=2)
    picks = allocate(d, 200)
    for race in (1, 2):
        race_total = sum(p.stake for p in picks if p.race == race)
        race_total += sum(e.outlay or 0 for e in d.races[race - 1].first_fours
                          + d.races[race - 1].trifectas if e.recommended)
        assert race_total <= RACE_CAP * 200 + 0.01


def test_good_price_keeps_the_model_stake_and_each_way_is_even():
    d = day(PRICES)
    picks = allocate(d, 200)
    good = [p for p in picks if p.good_price]
    assert good and all(p.stake == p.single.stake for p in good)
    assert all(p.stake % 2 == 0 for p in picks if p.kind == "each_way" and not p.good_price)


def test_place_pick_is_the_likeliest_placer():
    rp = day(SHORT, n=1).races[0]
    assert race_picks(rp)["place"].number == max(rp.model.ranked(), key=lambda a: a.place).number


def _betfair_better(d, factor=1.3):
    """Give every runner a Betfair price well above Sportsbet's and rebuild the picks."""
    for rp in d.races:
        for p in rp.model.race.prices.values():
            p.betfair_win = p.sportsbet_win * factor if p.sportsbet_win else None
            p.betfair_place = p.sportsbet_place * factor if p.sportsbet_place else None
    return build_picks([rp.model for rp in d.races], d.budget)


def test_betfair_gets_only_bets_of_five_dollars_or_more_within_its_money():
    d = _betfair_better(day(SHORT))
    routed = allocate_accounts(d, 150, 50)
    bf = [r for r in routed if r.account == "betfair"]
    assert bf, "some bets should go to Betfair"
    assert all(r.pick.stake >= (10 if r.pick.kind == "each_way" else 5) for r in bf)
    assert sum(r.pick.stake for r in bf) <= 50
    # First Four and quaddies come back routed to Sportsbet with their outlay
    sb_total = sum(r.pick.stake for r in routed if r.account == "sportsbet")
    assert sb_total <= 150
    assert all(r.account == "sportsbet" for r in routed if r.pick.kind in SPORTSBET_ONLY)


def test_no_betfair_money_sends_everything_to_sportsbet():
    d = _betfair_better(day(SHORT))
    routed = allocate_accounts(d, 200, 0)
    assert all(r.account == "sportsbet" for r in routed)
    assert all(r.price == r.pick.single.sportsbet for r in routed if r.pick.single)


def test_quinella_and_trifecta_get_a_stake_and_the_dividend_they_need():
    picks = [p for p in allocate(day(SHORT), 200) if p.race == 1]
    by = {p.kind: p for p in picks}
    assert {"quinella", "trifecta"} <= set(by)
    qn = by["quinella"]
    assert qn.stake > 0 and not qn.good_price
    assert qn.needs_dividend == qn.exotic.combos / qn.exotic.prob


# -- the owner's placed bets (wallet bars and Placed ticks) -----------------------------------


def _spent(routed, account):
    return sum(r.pick.stake for r in routed if r.account == account)


def test_a_placed_pick_keeps_its_stake_and_account():
    d = day(SHORT)
    first = {(r.pick.race, r.pick.kind): r for r in allocate_accounts(d, 150, 50)}
    win1 = first[(1, "win")]
    mine = Placed(1, "win", win1.pick.single.number, "betfair", 9)
    routed = allocate_accounts(d, 150, 50, [mine])
    held = [r for r in routed if r.placed]
    assert len(held) == 1 and held[0].account == "betfair" and held[0].pick.stake == 9
    assert held[0].pick.single.number == mine.key
    # the slot is filled: no second win pick in race 1
    assert [r for r in routed if (r.pick.race, r.pick.kind) == (1, "win")] == held


def test_only_the_money_left_is_shared_and_no_account_goes_over():
    d = _betfair_better(day(SHORT))
    placed = [Placed(1, "place", 1, "sportsbet", 40), Placed(2, "win", 1, "betfair", 30)]
    routed = allocate_accounts(d, 150, 50, placed)
    assert _spent(routed, "sportsbet") <= 150
    assert _spent(routed, "betfair") <= 50
    fresh = [r for r in routed if not r.placed]
    assert sum(r.pick.stake for r in fresh if r.account == "sportsbet") <= 110
    assert sum(r.pick.stake for r in fresh if r.account == "betfair") <= 20
    assert all(r.pick.stake > 0 for r in fresh)


def test_an_account_used_up_gets_nothing_more():
    d = day(SHORT)
    placed = [Placed(1, "place", 1, "sportsbet", 150)]
    routed = allocate_accounts(d, 150, 0, placed)
    assert [r for r in routed if not r.placed] == []
    assert _spent(routed, "sportsbet") == 150


def test_placed_bets_in_races_that_have_run_still_count_but_get_no_new_picks():
    d = day(SHORT, n=3)
    placed = [Placed(1, "win", 1, "sportsbet", 20)]
    routed = allocate_accounts(d, 150, 50, placed, races={2, 3})
    assert {r.pick.race for r in routed if not r.placed} <= {2, 3}
    assert _spent(routed, "sportsbet") <= 150 and _spent(routed, "betfair") <= 50


def test_a_placed_exotic_is_sportsbet_and_keeps_its_stake():
    d = day(SHORT)
    routed = allocate_accounts(d, 150, 50, [Placed(3, "trifecta", 0, "sportsbet", 4)])
    tri = [r for r in routed if (r.pick.race, r.pick.kind) == (3, "trifecta")]
    assert len(tri) == 1 and tri[0].placed and tri[0].pick.stake == 4
    assert tri[0].pick.exotic is not None and tri[0].account == "sportsbet"


def test_placed_money_counts_toward_the_race_cap():
    d = day(SHORT, n=2)
    placed = [Placed(1, "win", 1, "sportsbet", int(RACE_CAP * 200))]
    routed = allocate_accounts(d, 150, 50, placed)
    # the race is at its cap: only the model's own stakes and the First Four (fixed) remain
    shared = [r for r in routed if r.pick.race == 1 and not r.placed]
    assert all(r.pick.good_price or r.pick.kind == "first_four" for r in shared)
    assert any(not r.pick.good_price for r in routed if r.pick.race == 2 and not r.placed)
