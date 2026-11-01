"""The day budget shared over every race's win, place and each-way pick."""

from test_bets import FIELD, make_model

from melbcup.bets import build_picks
from melbcup.bets.allocate import RACE_CAP, allocate, race_picks

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
