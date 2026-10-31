import math

import httpx
import pytest
from conftest import RACE_DATE, VENUE, Router

from melbcup.domain import PastRun, Race, Runner, RunnerPrices, StatLine
from melbcup.model import probability
from melbcup.model.features import raw_factors, recent_form, runs_since_spell
from melbcup.model.probability import (
    assess,
    blend,
    model_probs,
    order_probs,
    top_k_probs,
)
from melbcup.sources import apply_market, load_card
from melbcup.sources.formfav import FormFavClient
from melbcup.sources.racingcom import RacingComClient


def run(pos, field=12, margin=None):
    return PastRun(RACE_DATE, "Caulfield", 1600, "Good 4", pos, field, margin, 5.0, 57, "J", None)


def simple_race(**overrides) -> Race:
    race = Race(venue=VENUE, race_date=RACE_DATE, number=1, distance_m=1600)
    race.runners = [
        Runner(
            1,
            "Good One",
            hcp_rating=90,
            runs=[run(1, margin=0), run(2, margin=0.5)],
            career=StatLine(10, 4, 7),
            weight_kg=57,
        ),
        Runner(
            2,
            "Middling",
            hcp_rating=80,
            runs=[run(5, margin=3), run(4, margin=2)],
            career=StatLine(10, 2, 4),
            weight_kg=57,
        ),
        Runner(
            3,
            "Out Of Form",
            hcp_rating=70,
            runs=[run(11, margin=12), run(10, margin=9)],
            career=StatLine(10, 0, 1),
            weight_kg=57,
        ),
    ]
    for k, v in overrides.items():
        setattr(race, k, v)
    return race


def test_runs_since_spell():
    assert runs_since_spell(Runner(1, "a", last10="231x")) == 0
    assert runs_since_spell(Runner(1, "a", last10="23x1")) == 1
    assert runs_since_spell(Runner(1, "a", last10="2341")) is None


def test_recent_form_prefers_runs_then_figures():
    race = simple_race()
    assert recent_form(race.runners[0], race) > recent_form(race.runners[2], race)
    figs_only = Runner(9, "figs", last10="x11")
    assert recent_form(figs_only, race) == pytest.approx(1.0)
    assert recent_form(Runner(9, "none"), race) is None


def test_model_ranks_the_better_horse_first_and_sums_to_one():
    probs, contrib = model_probs(simple_race())
    assert sum(probs.values()) == pytest.approx(1.0)
    assert probs[1] > probs[2] > probs[3]
    assert contrib[1]["form"] > 0 > contrib[3]["form"]


def test_scratched_and_emergency_runners_are_excluded():
    race = simple_race()
    race.runners[2].scratched = True
    race.runners.append(Runner(4, "Emergency", emergency=True))
    assert set(raw_factors(race)) == {1, 2}


def test_blend_reweights_over_available_sources():
    market = {1: 0.5, 2: 0.3, 3: 0.2}
    assert blend({"market": market, "feed": {}, "model": {}}) == pytest.approx(market)
    both = blend({"market": market, "model": {1: 0.2, 2: 0.3, 3: 0.5}})
    assert sum(both.values()) == pytest.approx(1.0)
    assert both[1] < 0.5 and both[3] > 0.2


def test_order_probs_first_place_equals_win_and_totals_one():
    win = {1: 0.5, 2: 0.3, 3: 0.15, 4: 0.05}
    orders = order_probs(win, 3)
    assert sum(orders.values()) == pytest.approx(1.0)
    first = {n: sum(p for c, p in orders.items() if c[0] == n) for n in win}
    assert first == pytest.approx(win)


def test_discount_lifts_favourites_in_minor_places():
    win = {1: 0.6, 2: 0.2, 3: 0.1, 4: 0.1}
    discounted = order_probs(win, 2)
    harville_2nd_given_4_won = 0.6 / 0.9
    assert discounted[(4, 1)] / win[4] < harville_2nd_given_4_won


def test_top_k_exact_and_simulated_agree(monkeypatch):
    win = {n: p for n, p in enumerate([0.3, 0.2, 0.15, 0.1, 0.1, 0.08, 0.07], start=1)}
    exact = top_k_probs(win, 3)
    assert sum(exact.values()) == pytest.approx(3.0)
    monkeypatch.setattr(probability, "EXACT_LIMIT", 1)
    sim = top_k_probs(win, 3)
    for n in win:
        assert sim[n] == pytest.approx(exact[n], abs=0.015)


def test_top_k_whole_field_is_certain():
    assert top_k_probs({1: 0.6, 2: 0.4}, 3) == {1: 1.0, 2: 1.0}


def test_priced_chances_are_the_margin_free_market_alone():
    t = httpx.MockTransport(Router())
    rc, ff = RacingComClient(transport=t), FormFavClient("k", transport=t)
    card = load_card(rc, ff, RACE_DATE, VENUE)
    race = card.race(2)
    apply_market(race, rc.card_prices(RACE_DATE, VENUE, [1, 2])[2])
    m = assess(race)
    assert m.sources == ["market"]  # the form model does not move priced chances
    market = {n: p.consensus_prob for n, p in race.prices.items() if n in m.runners}
    total = sum(market.values())
    assert all(m.runners[n].win == pytest.approx(v / total) for n, v in market.items())
    assert sum(a.win for a in m.runners.values()) == pytest.approx(1.0)
    assert sum(a.place for a in m.runners.values()) == pytest.approx(3.0)
    top = m.ranked()[0]
    assert top.number == 1  # favourite in market, feed and form
    assert top.reasons_for and all(isinstance(x, str) for x in top.reasons_for)
    assert all(0 < a.place <= 1 for a in m.runners.values())


def test_assess_without_prices_or_feed_falls_back_to_model():
    m = assess(simple_race())
    assert m.sources == ["form model (experimental)"]
    assert m.ranked()[0].number == 1


def test_partial_market_is_ignored_rather_than_mixed():
    race = simple_race(prices={1: RunnerPrices(1, consensus_prob=0.9)})
    assert assess(race).sources == ["form model (experimental)"]


def test_assess_empty_race():
    m = assess(Race(venue=VENUE, race_date=RACE_DATE, number=9))
    assert m.runners == {} and m.sources == []
    assert not math.isnan(sum(a.win for a in m.runners.values()))


def test_lone_source_is_not_sharpened():
    market = {1: 0.5, 2: 0.3, 3: 0.2}
    assert blend({"market": market}) == pytest.approx(market)
    model = {1: 0.4, 2: 0.4, 3: 0.2}
    assert blend({"model": model}) == pytest.approx(model)
