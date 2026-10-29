from datetime import date

import httpx
import pytest
from conftest import RACE_DATE, VENUE, Router, load_fixture

from melbcup.bets import build_picks
from melbcup.bets.exotics import Exotic
from melbcup.bets.grade import _exotic, _single, grade_day
from melbcup.bets.singles import Single
from melbcup.domain import RaceResult
from melbcup.model.probability import assess
from melbcup.sources import apply_market, apply_result, load_card
from melbcup.sources.formfav import FormFavClient
from melbcup.sources.puntersedge import PuntersEdgeClient, parse_results


def result(finish: dict[int, int], **kw) -> RaceResult:
    return RaceResult(
        "final",
        finish,
        kw.get("sp", {}),
        {n: f"H{n}" for n in finish},
        kw.get("place", {}),
        kw.get("exotics", {}),
    )


def single(kind: str, number: int, price: float | None, place_price: float | None = None):
    return Single(
        kind, 1, number, f"H{number}", 0.3, price, place_price, "tab", None, 0.1, 3.0, True, []
    )


def test_vendor_results_example():
    res = parse_results(load_fixture("pe_results"), "kalgoorlie", date(2026, 9, 6))
    r = res[8]
    assert r.status == "final" and r.finish[8] == 1 and r.sp[8] == 4.6
    assert r.place_dividend[15] == 17.0
    assert r.exotics["TF"] == ((8, 15, 1), 4868.5)
    assert r.placegetters(3) == [8, 15, 1]


def test_single_grading():
    res = result({1: 1, 2: 2, 3: 3, 4: 4}, place={1: 1.5, 2: 2.0, 3: 2.5})
    assert _single(single("win", 1, 3.0), res, 3).returned == 3.0
    assert _single(single("win", 2, 4.0), res, 3).returned == 0.0
    assert _single(single("place", 2, 1.8, 1.8), res, 3).returned == 1.8
    assert _single(single("place", 3, None), res, 3).returned == 2.5  # official place dividend
    assert _single(single("place", 4, 2.0, 2.0), res, 3).returned == 0.0
    ew = _single(single("each_way", 1, 3.0, 1.4), res, 3)
    assert ew.hit and ew.returned == pytest.approx(0.5 * 3.0 + 0.5 * 1.4)
    assert _single(single("each_way", 2, 4.0, 1.8), res, 3).returned == pytest.approx(0.9)


def test_exotic_grading_is_flexi():
    res = result({5: 1, 2: 2, 7: 3}, exotics={"TF": ((5, 2, 7), 120.0)})
    box = Exotic("trifecta", "Box", [[2, 5, 7, 9]] * 3, ["Box 2, 5, 7, 9"], 24, 0.1, [1])
    g = _exotic(box, res, "TF", 3)
    assert g.hit and g.returned == pytest.approx(120.0 / 24)
    miss = Exotic("trifecta", "Straight", [[2], [5], [7]], ["2", "5", "7"], 1, 0.01, [1])
    assert _exotic(miss, res, "TF", 3).returned == 0.0


def test_grade_a_priced_card_end_to_end():
    router = Router()
    t = httpx.MockTransport(router)
    pe, ff = PuntersEdgeClient("k", transport=t), FormFavClient("k", transport=t)
    card = load_card(pe, ff, RACE_DATE, VENUE)
    snaps = pe.card_prices(RACE_DATE, VENUE)
    results = pe.results(RACE_DATE, VENUE)
    for race in card.races:
        apply_market(race, snaps[race.number])
        apply_result(race, results[race.number])
    day = build_picks([assess(r) for r in card.races])
    grade = grade_day(day)
    assert grade.graded == 2
    cup = next(g for g in grade.races if g.race == 2)
    assert cup.placings[0][:3] == (1, 1, "Grand Tempo")
    assert cup.top_pick == 1 and cup.top_rank_of_winner == 1
    assert grade.top_pick_wins >= 1
    assert all(not race.priced_from_sp for race in card.races)  # pre-race prices kept
    labels = {g.label for g in cup.lines}
    assert {"Win", "Place", "Each way", "Trifecta", "First Four"} <= labels


def test_unpriced_race_is_judged_at_starting_prices():
    router = Router()
    t = httpx.MockTransport(router)
    pe, ff = PuntersEdgeClient("k", transport=t), FormFavClient("k", transport=t)
    card = load_card(pe, ff, RACE_DATE, VENUE)
    race = card.race(1)
    apply_result(race, pe.results(RACE_DATE, VENUE)[1])
    assert race.priced_from_sp and race.prices[1].best_win.bookmaker == "SP"
    assert sum(p.consensus_prob for p in race.prices.values()) == pytest.approx(1.0)
    assert "market" in assess(race).sources
