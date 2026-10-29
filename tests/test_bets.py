import math

import pytest
from conftest import RACE_DATE, VENUE

from melbcup.bets import build_picks
from melbcup.bets.exotics import first_fours, quaddie, quaddies, recommend, seq_prob, trifectas
from melbcup.bets.multis import multis
from melbcup.bets.singles import best, singles
from melbcup.bets.staking import (
    each_way_stake,
    exotic_stake,
    kelly_fraction,
    scale_to_budget,
    stake,
)
from melbcup.domain import Quote, Race, Runner, RunnerPrices
from melbcup.model.probability import Assessment, RaceModel, order_probs, top_k_probs


def make_model(
    number: int,
    win: list[float],
    win_prices: list[float] | None = None,
    place_prices: list[float] | None = None,
    sportsbet: bool = True,
) -> RaceModel:
    race = Race(venue=VENUE, race_date=RACE_DATE, number=number)
    probs = {i + 1: p for i, p in enumerate(win)}
    place = top_k_probs(probs, 3)
    runners = {}
    for n, p in probs.items():
        race.runners.append(Runner(n, f"Horse {number}-{n}"))
        if win_prices:
            wp = win_prices[n - 1]
            pp = place_prices[n - 1] if place_prices else None
            race.prices[n] = RunnerPrices(
                n,
                best_win=Quote(wp, "tab"),
                best_place=Quote(pp, "tab") if pp else None,
                sportsbet_win=wp if sportsbet else None,
            )
        runners[n] = Assessment(n, p, place[n], p, None, None, ["Recent form"], [])
    return RaceModel(race, runners, ["model"])


FIELD = [0.35, 0.25, 0.15, 0.1, 0.08, 0.07]


def test_singles_ev_and_value_flag():
    # Runner 1 priced at 3.5 against a 35% chance: EV = 0.225 -> value.
    m = make_model(1, FIELD, [3.5, 3.0, 6.0, 10.0, 13.0, 15.0], [1.4, 1.5, 2.0, 2.5, 3.0, 3.5])
    sl = singles(m)
    w1 = next(s for s in sl if s.kind == "win" and s.number == 1)
    assert w1.ev == pytest.approx(0.35 * 3.5 - 1)
    assert w1.value and w1.fair_price == pytest.approx(1 / 0.35)
    w2 = next(s for s in sl if s.kind == "win" and s.number == 2)
    assert not w2.value  # 0.25 * 3.0 < 1
    ew1 = next(s for s in sl if s.kind == "each_way" and s.number == 1)
    p1 = next(s for s in sl if s.kind == "place" and s.number == 1)
    assert ew1.ev == pytest.approx(0.5 * (w1.ev + p1.ev))
    assert best(sl, "win").number == 1


def test_most_likely_ignores_price_and_value_needs_an_edge():
    m = make_model(1, FIELD, [2.0, 2.5, 4.0, 6.0, 8.0, 9.0])
    sl = singles(m)
    top = best(sl, "top_win")
    assert top.number == 1 and not top.value  # most likely, though the price is short
    assert top.prob == max(s.prob for s in sl if s.kind == "win")
    assert best(sl, "top_place").prob == max(s.prob for s in sl if s.kind == "place")
    assert best(sl, "win") is None  # no price beats its chance: no value pick


def test_most_likely_exists_without_prices():
    sl = singles(make_model(1, FIELD))
    assert best(sl, "top_win") is not None and best(sl, "top_place") is not None
    assert all(best(sl, k) is None for k in ("win", "place", "each_way"))


def test_singles_without_prices_have_no_ev():
    sl = singles(make_model(1, FIELD))
    assert all(s.ev is None and not s.value for s in sl)


def test_seq_prob_matches_order_probs():
    win = dict(enumerate(FIELD, start=1))
    orders = order_probs(win, 3)
    assert seq_prob(win, (2, 1, 3)) == pytest.approx(orders[(2, 1, 3)])


def test_trifecta_structures():
    tri = trifectas(make_model(1, FIELD))
    titles = [t.title for t in tri]
    assert titles[0].startswith("Straight")
    box = next(t for t in tri if t.title == "Box of top 4")
    assert box.combos == 24
    straight = tri[0]
    assert straight.combos == 1 and straight.legs == [[1], [2], [3]]
    assert box.prob > straight.prob
    standout = next(t for t in tri if t.title == "Standout top pick")
    assert standout.combos == 3 * 4  # 1 / 2,3,4 / 2..6 minus repeats
    assert standout.fair_dividend == pytest.approx(standout.combos / standout.prob)


def test_first_four_structures_and_recommendation():
    ff = first_fours(make_model(1, FIELD))
    assert ff[0].combos == 24
    chosen = recommend(ff, 0.06)
    assert chosen.recommended and chosen.prob >= 0.06
    assert sum(e.recommended for e in ff) == 1


def test_small_fields_skip_exotics():
    assert trifectas(make_model(1, [0.6, 0.4])) == []
    assert first_fours(make_model(1, [0.5, 0.3, 0.2])) == []


def test_quaddie_greedy_respects_budget_and_prefers_open_legs():
    legs = [
        make_model(7, [0.8, 0.1, 0.05, 0.05]),  # banker
        make_model(8, [0.2, 0.2, 0.2, 0.2, 0.2]),  # wide open
        make_model(9, [0.5, 0.3, 0.2]),
        make_model(10, [0.6, 0.3, 0.1]),
    ]
    q = quaddie(legs, "quaddie", "Quaddie", 24)
    assert q.combos <= 24
    assert len(q.legs[0]) <= len(q.legs[1])
    expected = math.prod(
        sum(m.runners[n].win for n in leg) for m, leg in zip(legs, q.legs, strict=True)
    )
    assert q.prob == pytest.approx(expected)
    assert q.races == [7, 8, 9, 10]


def test_quaddies_use_last_four_and_four_before():
    models = [make_model(n, FIELD) for n in range(1, 11)]
    q = quaddies(models)
    main = [e for e in q if e.kind == "quaddie"]
    early = [e for e in q if e.kind == "early_quaddie"]
    assert main and early
    assert main[0].races == [7, 8, 9, 10] and early[0].races == [3, 4, 5, 6]
    assert {e.combos <= 24 for e in q if "24" in e.title} == {True}


def test_quaddies_need_four_races():
    assert quaddies([make_model(n, FIELD) for n in range(1, 4)]) == []


def test_multis_use_sportsbet_and_skip_longshots():
    models = [
        make_model(1, [0.5, 0.3, 0.2], [2.4, 3.0, 5.0]),
        make_model(2, [0.45, 0.35, 0.2], [2.6, 2.8, 5.5]),
        make_model(3, [0.4, 0.4, 0.2], [2.8, 2.5, 6.0]),
        make_model(4, [0.5, 0.5], [2.0, 2.0], sportsbet=False),
    ]
    ms = multis(models)
    assert ms and all(len(m.legs) in (2, 3) for m in ms)
    assert all(leg.race != 4 for m in ms for leg in m.legs)
    assert all(leg.prob >= 0.15 for m in ms for leg in m.legs)
    top2 = next(m for m in ms if len(m.legs) == 2)
    assert top2.price == pytest.approx(math.prod(leg.price for leg in top2.legs))
    assert top2.ev == pytest.approx(top2.prob * top2.price - 1)


def test_kelly_and_stakes():
    assert kelly_fraction(0.5, 2.0) == 0.0
    assert kelly_fraction(0.3, 2.0) == 0.0
    f = kelly_fraction(0.4, 3.0)
    assert f == pytest.approx(min(0.05, 0.25 * 0.2 / 2.0))
    assert stake(1000, 0.4, 3.0) == 25
    assert stake(None, 0.4, 3.0) is None
    assert stake(1000, 0.3, 3.0) is None
    assert each_way_stake(1000, 0.4, 3.0, 0.7, 1.6) % 2 == 0
    assert exotic_stake(500, 24) == (5, 20.8)
    assert exotic_stake(50, 24) is None
    assert scale_to_budget([60, 60], 100) == [50, 50]
    assert scale_to_budget([10, 20], 100) == [10, 20]


def test_build_picks_end_to_end_with_budget():
    prices = [3.5, 3.0, 6.0, 10.0, 13.0, 15.0]
    places = [1.4, 1.5, 2.0, 2.5, 3.0, 3.5]
    models = [make_model(n, FIELD, prices, places) for n in range(1, 11)]
    day = build_picks(models, budget=200)
    assert len(day.races) == 10
    r1 = day.races[0]
    assert r1.best["win"].number == 1 and r1.best["win"].stake
    assert sum(e.recommended for e in r1.trifectas) == 1
    rec = next(e for e in r1.trifectas if e.recommended)
    assert rec.outlay == 2 and rec.flexi_pct == pytest.approx(100 * 2 / rec.combos, abs=0.1)
    assert {e.kind for e in day.quaddies} == {"quaddie", "early_quaddie"}
    total = sum(
        (s.stake or 0)
        for rp in day.races
        for s in {id(x): x for x in rp.best.values() if x is not None}.values()
    )
    total += sum(e.outlay or 0 for rp in day.races for e in rp.trifectas + rp.first_fours)
    total += sum(e.outlay or 0 for e in day.quaddies) + sum(m.stake or 0 for m in day.multis)
    assert total <= 200


def test_build_picks_without_budget_has_no_stakes():
    models = [make_model(n, FIELD, [3.5, 3.0, 6.0, 10.0, 13.0, 15.0]) for n in range(1, 5)]
    day = build_picks(models)
    assert all(s is None or s.stake is None for rp in day.races for s in rp.best.values())
    assert all(e.outlay is None for e in day.quaddies)


def test_required_edge_grows_with_price():
    from melbcup.bets.singles import required_edge

    assert required_edge(2.0) == pytest.approx(0.06)
    assert required_edge(6.0) == pytest.approx(0.10)
    assert required_edge(51.0) == 0.25


def test_longshot_needs_a_bigger_edge_than_a_favourite():
    # Both runners show +15%: fine at $3.50, not enough at $23.
    m = make_model(1, [0.33, 0.05, 0.62], [3.5, 23.0, 1.5])
    sl = singles(m)
    fav = next(s for s in sl if s.kind == "win" and s.number == 1)
    roughie = next(s for s in sl if s.kind == "win" and s.number == 2)
    assert fav.ev == pytest.approx(0.155) and fav.value
    assert roughie.ev == pytest.approx(0.15) and not roughie.value


def test_multi_search_tries_every_qualifying_leg():
    # Best-edge legs (R1 #2, R2 #2) combine under 8%; favourites together clear it.
    models = [
        make_model(1, [0.35, 0.16, 0.49], [3.2, 7.0, 2.5]),
        make_model(2, [0.38, 0.16, 0.46], [2.6, 8.0, 2.4]),
    ]
    ms = multis(models)
    assert ms and all(m.prob >= 0.08 for m in ms)


def test_box_label():
    tri = trifectas(make_model(1, FIELD))
    box = next(t for t in tri if t.title == "Box of top 4")
    assert box.leg_labels == ["Box 1, 2, 3, 4"]


def test_implausible_edges_and_big_prices_are_never_value():
    # 30% at $6 is +80%: the model is more likely wrong than the market. 6% at $26: too long.
    m = make_model(1, [0.30, 0.06, 0.64], [6.0, 26.0, 1.6])
    sl = singles(m)
    huge = next(s for s in sl if s.kind == "win" and s.number == 1)
    long_ = next(s for s in sl if s.kind == "win" and s.number == 2)
    assert huge.ev == pytest.approx(0.8) and not huge.value
    assert long_.ev == pytest.approx(0.56) and not long_.value
    assert not any(s.value for s in sl if s.number == 2)  # place and each-way follow the win price


def test_place_pick_looks_past_a_short_favourite():
    # The favourite almost always places but pays $1.10: the second favourite at $1.35 is the
    # place value, while the favourite stays the most likely placegetter.
    m = make_model(1, [0.5, 0.25, 0.15, 0.1], [2.0, 4.5, 7.0, 11.0], [1.10, 1.35, 1.60, 2.00])
    sl = singles(m)
    assert best(sl, "place").number == 2 and best(sl, "top_place").number == 1


def test_each_way_needs_a_price_where_the_place_half_matters():
    short = make_model(1, [0.5, 0.3, 0.2], [2.0, 3.0, 4.5], [1.2, 1.5, 1.9])
    assert best(singles(short), "each_way") is None  # nobody at $5 or more
    m = make_model(1, FIELD, [3.5, 3.0, 8.0, 10.0, 13.0, 15.0], [1.4, 1.5, 2.2, 2.5, 3.0, 3.5])
    ew = best(singles(m), "each_way")
    assert ew is not None and ew.number == 3 and ew.value and 5.0 <= ew.price <= 21.0


def test_place_price_estimated_only_for_races_judged_at_sp():
    from melbcup.bets.singles import PLACE_MARGIN, estimate_place_price

    assert estimate_place_price(0.5) == pytest.approx(1 / (PLACE_MARGIN * 0.5), abs=0.01)
    assert estimate_place_price(0.95) == 1.01  # never below a dollar
    m = make_model(1, FIELD, [3.5, 3.0, 6.0, 10.0, 13.0, 15.0])
    assert all(s.place_price is None for s in singles(m))  # live race, no place market: no guess
    m.race.priced_from_sp = True
    for n, p in m.race.prices.items():
        p.consensus_prob = FIELD[n - 1]
    assert all(s.estimated and s.place_price for s in singles(m))


def test_history_tally_reports_profit_per_dollar():
    from melbcup.history import tally

    record = [
        {"picks": {"top_win": {"hit": True, "returned": 3.0}}},
        {"picks": {"top_win": {"hit": False, "returned": 0.0}}},
        {"picks": {"trifecta": {"hit": True, "returned": None}}},
    ]
    t = {x.label: x for x in tally(record)}
    assert t["Most likely win"].profit == pytest.approx(0.5)
    assert t["Most likely win"].rate == 0.5
    assert t["Trifecta"].profit is None  # dividend unknown


def test_history_value_rows_count_only_value_picks():
    from melbcup.history import tally

    record = [  # the second was saved before the split, when a fallback filled the slot
        {"picks": {"win": {"hit": True, "returned": 4.0, "value": True}}},
        {"picks": {"win": {"hit": False, "returned": 0.0, "value": False}}},
    ]
    v = {t.label: t for t in tally(record)}
    assert v["Value win"].picks == 1 and v["Value win"].profit == pytest.approx(3.0)


def test_confidence_bands_follow_the_top_picks_chance():
    from melbcup.bets import confidence
    from melbcup.history import by_confidence

    assert [confidence(p) for p in (0.55, 0.40, 0.35, 0.30, 0.12)] == [
        "High",
        "High",
        "Medium",
        "Medium",
        "Low",
    ]
    record = [
        {"picks": {"top_win": {"chance": 0.5, "hit": True, "returned": 2.0}}},
        {"picks": {"top_win": {"chance": 0.45, "hit": False, "returned": 0.0}}},
        {"picks": {"top_win": {"chance": 0.2, "hit": False, "returned": 0.0}}},
    ]
    t = {x.label: x for x in by_confidence(record)}
    assert t["High confidence"].picks == 2 and t["High confidence"].rate == 0.5
    assert t["Low confidence"].picks == 1 and t["Medium confidence"].picks == 0


def test_views_split_flags_strong_disagreement_with_the_odds():
    from melbcup.bets import views_split
    from melbcup.model.probability import Assessment

    def a(model, feed, market):
        return Assessment(1, 0.1, 0.3, model, feed, market)

    assert not views_split(a(0.10, 0.12, 0.10))  # all agree
    assert views_split(a(0.50, None, 0.10))  # form model 5x the odds
    assert views_split(a(0.10, 0.02, 0.10))  # FormFav a fifth of the odds
    assert not views_split(a(0.40, None, None))  # no prices yet: nothing to compare
