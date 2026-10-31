import httpx
import pytest
from conftest import RACE_DATE, VENUE, Router

from melbcup.bets import build_picks
from melbcup.bets.exotics import Exotic
from melbcup.bets.grade import _exotic, _single, grade_day
from melbcup.bets.singles import Single
from melbcup.domain import RaceResult
from melbcup.model.probability import assess
from melbcup.sources import apply_market, apply_result, load_card
from melbcup.sources.formfav import FormFavClient
from melbcup.sources.racingcom import RacingComClient


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
    g = _exotic(box, res, "trifecta", 3)
    assert g.hit and g.returned == pytest.approx(120.0 / 24)
    miss = Exotic("trifecta", "Straight", [[2], [5], [7]], ["2", "5", "7"], 1, 0.01, [1])
    assert _exotic(miss, res, "trifecta", 3).returned == 0.0


def test_grade_a_priced_card_end_to_end():
    router = Router()
    t = httpx.MockTransport(router)
    rc, ff = RacingComClient(transport=t), FormFavClient("k", transport=t)
    card = load_card(rc, ff, RACE_DATE, VENUE)
    snaps = rc.card_prices(RACE_DATE, VENUE, [1, 2])
    results = rc.results(RACE_DATE, VENUE, [1, 2])
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
    kinds = {g.kind for g in cup.lines}
    assert {"top_win", "top_place", "trifecta", "first_four"} <= kinds
    assert all(g.value for g in cup.lines if g.kind in ("win", "place", "each_way"))
    assert next(g for g in cup.lines if g.kind == "top_win").label == "Most likely win"


def test_unpriced_race_is_judged_at_starting_prices():
    router = Router()
    t = httpx.MockTransport(router)
    rc, ff = RacingComClient(transport=t), FormFavClient("k", transport=t)
    card = load_card(rc, ff, RACE_DATE, VENUE)
    race = card.race(1)
    apply_result(race, rc.results(RACE_DATE, VENUE, [1, 2])[1])
    assert race.priced_from_sp and race.prices[1].best_win.bookmaker == "SP"
    assert sum(p.consensus_prob for p in race.prices.values()) == pytest.approx(1.0)
    assert "market" in assess(race).sources


def test_a_losing_pick_returns_nothing_even_without_a_price():
    res = result({1: 1, 2: 2, 3: 3, 4: 4})
    assert _single(single("win", 4, None), res, 3).returned == 0.0
    assert _single(single("win", 1, None), res, 3).returned is None  # won, price unknown
    assert _single(single("each_way", 4, None, None), res, 3).returned == 0.0
