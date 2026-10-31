"""Offers check: closed forms, robustness, Kelly, the Cup-like research sanity, the endpoint."""

import math
from dataclasses import replace
from datetime import date

import pytest
from conftest import Router
from fastapi.testclient import TestClient
from test_live_web import AUTH, ENV, START, Clock, board_with

from melbcup.bets import offers
from melbcup.bets.offers import (
    MIN_EV_BUFFER,
    EachWay,
    MoneyBack,
    OddsBoost,
    PlaceOnly,
    break_even_c,
    check_offer,
    ev_per_dollar,
    growth_stake,
    leg_chances,
    position_probs,
    size_stake,
)
from melbcup.config import load_settings
from melbcup.domain import Race, Runner, RunnerPrices
from melbcup.model import probability
from melbcup.model.probability import (
    DISCOUNT,
    Assessment,
    RaceModel,
    order_probs,
    simulate_positions,
)
from melbcup.web import offer_api
from melbcup.web.app import create_app

SB = "sportsbet"


def model_of(win, sportsbet=None, sources=("market",), number=1) -> RaceModel:
    """A priced race: ``win`` are consensus chances, ``sportsbet`` the prices (default: fair)."""
    race = Race("Flemington", date(2026, 11, 3), number, places_paid=4)
    total = sum(win)
    for i, p in enumerate(win, 1):
        race.runners.append(Runner(i, f"Horse {i}"))
        price = sportsbet[i - 1] if sportsbet else total / p
        race.prices[i] = RunnerPrices(i, sportsbet_win=price, consensus_prob=p / total)
    runners = {i: Assessment(i, p / total, 0.0, p, None, None) for i, p in enumerate(win, 1)}
    return RaceModel(race, runners, list(sources))


def hand_second(win: dict[int, float], runner: int) -> float:
    """P(runner 2nd), written out from the formula: the winner j, then the runner against the
    others at the 2nd-place exponent."""
    e = DISCOUNT[1]
    return sum(
        p * win[runner] ** e / sum(q**e for m, q in win.items() if m != j)
        for j, p in win.items()
        if j != runner
    )


# --- position probabilities -----------------------------------------------------------------


def test_places_sum_to_one_per_runner_and_top_k_sums_to_k():
    win = {n: p for n, p in enumerate([0.3, 0.2, 0.15, 0.12, 0.1, 0.08, 0.05], 1)}
    pos = position_probs(win)
    assert pos.method == "exact" and not pos.simulated and pos.draws == 0
    for k in range(1, 6):  # each place is filled by exactly one runner
        assert sum(pos.by_place[k].values()) == pytest.approx(1.0, abs=1e-12)
        assert sum(pos.top(n, k) for n in win) == pytest.approx(k, abs=1e-12)
    assert pos.by_place[1] == pytest.approx(win)
    assert all(pos.se(n, range(1, 6)) == 0.0 for n in win)


def test_toy_race_places_match_a_hand_calculation():
    win = {1: 0.5, 2: 0.3, 3: 0.2}
    pos = position_probs(win)
    for n in win:
        assert pos.by_place[2][n] == pytest.approx(hand_second(win, n), abs=1e-12)
    assert pos.top(2, 3) == pytest.approx(1.0)  # three runners, three places
    assert pos.chance(2, [4, 5]) == 0.0  # nobody finishes 4th in a 3-runner race


def test_a_runner_with_no_chance_never_places_and_does_not_break_the_enumeration():
    pos = position_probs({1: 0.6, 2: 0.4, 3: 0.0})
    assert pos.top(3, 5) == 0.0 and pos.top(1, 2) == pytest.approx(1.0)


def test_simulation_agrees_with_enumeration_and_reports_a_standard_error(monkeypatch):
    win = {n: p for n, p in enumerate([0.3, 0.2, 0.15, 0.12, 0.1, 0.08, 0.05], 1)}
    exact = position_probs(win)
    monkeypatch.setattr(probability, "EXACT_LIMIT", 1)  # force simulation
    sim = position_probs(win)
    assert sim.simulated == frozenset(range(1, 6)) and sim.draws >= 200_000
    assert "Monte Carlo" in sim.method
    for k in range(1, 6):
        assert sum(sim.by_place[k].values()) == pytest.approx(1.0, abs=1e-9)
        for n in win:
            se = sim.se(n, [k])
            assert se > 0
            assert abs(sim.by_place[k][n] - exact.by_place[k][n]) < 4.5 * se
    assert position_probs(win).by_place == sim.by_place  # seeded: the same every time


def test_simulation_matches_order_probs_marginals_directly():
    win = {1: 0.5, 2: 0.3, 3: 0.2}
    counts = simulate_positions(win, 3, sims=200_000, seed=3)
    exact = order_probs(win, 3)
    for k in range(3):
        for n in win:
            p = sum(v for combo, v in exact.items() if combo[k] == n)
            assert counts[k][n] / 200_000 == pytest.approx(p, abs=0.006)


# --- offer formulas -------------------------------------------------------------------------


def test_each_way_ev_equals_the_hand_value_on_a_three_runner_race():
    win = {1: 0.5, 2: 0.3, 3: 0.2}
    m = model_of([0.5, 0.3, 0.2], sportsbet=[2.2, 3.8, 5.5])
    o, f = 3.8, 0.25
    p1 = 0.3
    top2 = p1 + hand_second(win, 2)
    two = 0.5 * (p1 * o + top2 * (1 + (o - 1) * f)) - 1
    three = 0.5 * (p1 * o + 1.0 * (1 + (o - 1) * f)) - 1  # three runners, three places: always
    for places, hand in ((2, two), (3, three)):
        r = check_offer(m, 2, EachWay(o, f, places), budget=200)
        got = next(s.ev for s in r.scenarios if s.key == "consensus")
        assert got == pytest.approx(hand, abs=1e-9), places
    assert "exact" == r.positions_used["method"]


def test_place_only_ev_is_the_place_half():
    chances = {"placed": 0.55}
    assert ev_per_dollar(PlaceOnly(6.0, 0.25, 3), chances) == pytest.approx(
        0.55 * (1 + 5 * 0.25) - 1
    )
    ew = EachWay(6.0, 0.25, 3)
    c = {"win": 0.2, "placed": 0.35}  # top-3 = 0.55
    assert ev_per_dollar(ew, c) == pytest.approx(0.5 * (0.2 * 6.0 + 0.55 * (1 + 5 * 0.25)) - 1)


def test_odds_boost_ev_is_p_times_price_minus_one():
    m = model_of([0.4, 0.3, 0.2, 0.1])
    r = check_offer(m, 3, OddsBoost(6.0), budget=200)
    assert next(s.ev for s in r.scenarios if s.key == "consensus") == pytest.approx(0.2 * 6 - 1)
    assert ev_per_dollar(OddsBoost(7.0), {"win": 0.2}) == pytest.approx(0.4)


def test_money_back_at_zero_bonus_value_is_the_plain_win_ev():
    m = model_of([0.4, 0.3, 0.2, 0.1])
    for positions in ({2}, {2, 3}):
        r = check_offer(m, 2, MoneyBack(4.0, positions, 50.0, bonus_value=0.0), budget=200)
        assert next(s.ev for s in r.scenarios if s.key == "consensus") == pytest.approx(0.3 * 4 - 1)
    assert MoneyBack(4.0, {2}, 50.0).bonus_value == 0.70  # the default, and a parameter


def test_money_back_ev_and_the_break_even_bonus_value():
    chances = {"win": 0.2, "refund": 0.3}
    offer = MoneyBack(4.0, {2, 3}, cap=50.0, bonus_value=0.7)
    assert ev_per_dollar(offer, chances) == pytest.approx(0.2 * 4 + 0.7 * 0.3 - 1)
    c = break_even_c(offer, chances)
    assert c == pytest.approx((1 - 0.2 * 4) / 0.3) and 0 < c < 1
    assert ev_per_dollar(replace(offer, bonus_value=c), chances) == pytest.approx(0.0, abs=1e-12)
    assert break_even_c(offer, {"win": 0.2, "refund": 0.0}) is None
    assert (
        break_even_c(offer, {"win": 0.3, "refund": 0.2}) < 0
    )  # +EV even if a bonus bet is worthless


def test_break_even_c_accounts_for_the_cap_at_the_stake_placed():
    chances = {"win": 0.24, "refund": 0.3}
    offer = MoneyBack(4.0, {2, 3}, cap=10.0)
    small, big = break_even_c(offer, chances, 5.0), break_even_c(offer, chances, 20.0)
    assert big == pytest.approx(small * 2)  # half of a $20 stake comes back
    assert ev_per_dollar(replace(offer, bonus_value=big), chances, 20.0) == pytest.approx(
        0.0, abs=1e-12
    )


def test_money_back_result_carries_the_break_even_in_every_scenario():
    m = model_of([0.4, 0.3, 0.2, 0.1], sportsbet=[2.3, 3.4, 5.0, 9.0])
    r = check_offer(m, 2, MoneyBack(3.4, {2}, 50.0), budget=200).as_dict()
    assert r["break_even_c"] == max(s["break_even_c"] for s in r["scenarios"])
    assert "Break-even bonus value" in r["reason"]


@pytest.mark.parametrize(
    "make",
    [
        lambda: EachWay(1.0, 0.25, 3),
        lambda: EachWay(5.0, 0.0, 3),
        lambda: EachWay(5.0, 0.25, 0),
        lambda: PlaceOnly(5.0, 0.25, 6),
        lambda: OddsBoost(float("nan")),
        lambda: MoneyBack(5.0, {1}, 10.0),
        lambda: MoneyBack(5.0, set(), 10.0),
        lambda: MoneyBack(5.0, {2}, -1.0),
        lambda: MoneyBack(5.0, {2}, 10.0, bonus_value=1.5),
    ],
)
def test_bad_offers_are_refused(make):
    with pytest.raises(ValueError):
        make()


# --- robustness -----------------------------------------------------------------------------


def test_every_scenario_is_exposed_and_the_decision_uses_the_minimum():
    m = model_of(
        [0.3, 0.25, 0.2, 0.1, 0.08, 0.05, 0.02], sportsbet=[3.0, 3.6, 4.5, 8.5, 11, 18, 41]
    )
    r = check_offer(m, 4, EachWay(8.5, 0.25, 3), budget=200)
    keys = {s.key for s in r.scenarios}
    assert keys == {
        "consensus",
        "flb_1_14",
        "sportsbet_only",
        "discount_low",
        "discount_high",
        "mc_2se",
    }
    evs = {s.key: s.ev for s in r.scenarios}
    assert r.min_ev == min(evs.values()) and evs[r.binding] == r.min_ev
    assert len(set(round(v, 6) for v in evs.values())) > 1  # the scenarios really differ
    assert r.as_dict()["ev"] == {k: round(v, 5) for k, v in evs.items()}


def test_positive_in_one_scenario_but_negative_in_another_is_a_hold():
    win = [0.4, 0.3, 0.2, 0.07, 0.03]
    m = model_of(win)
    flb = {s.key: s for s in offers.scenarios(m)}["flb_1_14"].win[5]
    # a price that pays on the plain 3% chance but not on the corrected, smaller chance
    price = (1.10 / 0.03 + 1 / flb) / 2
    assert 0.03 * price - 1 > MIN_EV_BUFFER and flb * price - 1 < 0
    r = check_offer(m, 5, OddsBoost(price), budget=10_000)
    evs = {s.key: s.ev for s in r.scenarios}
    assert evs["consensus"] > MIN_EV_BUFFER and evs["flb_1_14"] < 0
    assert r.verdict == "hold" and r.stake == 0 and r.binding == "flb_1_14"
    assert r.min_ev == pytest.approx(flb * price - 1)
    assert "below" in r.reason


def test_a_bet_needs_the_worst_case_to_clear_the_buffer():
    m = model_of([0.4, 0.3, 0.2, 0.1])
    fair = m.runners[3].win
    thin = check_offer(m, 3, OddsBoost(1.01 / fair), budget=10_000)  # +1% on consensus
    assert thin.min_ev < MIN_EV_BUFFER and thin.verdict == "hold"
    rich = check_offer(m, 3, OddsBoost(2.0 / fair), budget=10_000)  # +100% in every scenario
    assert rich.min_ev >= MIN_EV_BUFFER and rich.verdict == "bet" and rich.stake > 0
    assert MIN_EV_BUFFER == 0.02


def test_monte_carlo_error_is_subtracted_only_when_places_are_simulated(monkeypatch):
    win = [0.3, 0.2, 0.15, 0.12, 0.1, 0.08, 0.05]
    m = model_of(win, sportsbet=[3.5, 5.5, 7.5, 9.0, 11.0, 13.0, 26.0])
    exact = check_offer(m, 4, PlaceOnly(9.0, 0.25, 4), budget=200)
    evs = {s.key: s.ev for s in exact.scenarios}
    assert evs["mc_2se"] == pytest.approx(evs["consensus"])  # exact: no error to subtract
    monkeypatch.setattr(probability, "EXACT_LIMIT", 1)
    sim = check_offer(m, 4, PlaceOnly(9.0, 0.25, 4), budget=200)
    s = {x.key: x.ev for x in sim.scenarios}
    assert s["mc_2se"] < s["consensus"]
    assert sim.positions_used["se"][3] > 0 and "Monte Carlo" in sim.positions_used["method"]
    assert s["consensus"] == pytest.approx(evs["consensus"], abs=0.02)


def test_missing_prices_or_chances_hold_with_a_reason():
    m = model_of([0.4, 0.3, 0.2, 0.1])
    m.race.prices[2].sportsbet_win = None
    r = check_offer(m, 2, OddsBoost(9.0), budget=200)
    assert r.verdict == "hold" and "no Sportsbet price" in r.reason
    m = model_of([0.4, 0.3, 0.2, 0.1])
    m.race.prices[2].consensus_prob = None
    assert "no consensus" in check_offer(m, 2, OddsBoost(9.0), budget=200).reason
    assert (
        "not from bookmaker prices"
        in check_offer(
            model_of([0.4, 0.6], sources=("form model (experimental)",)), 1, OddsBoost(9.0), 200
        ).reason
    )
    assert "not a starter" in check_offer(model_of([0.5, 0.5]), 7, OddsBoost(9.0), 200).reason


def test_without_a_sportsbet_price_for_every_runner_the_check_cannot_run_so_it_holds():
    m = model_of([0.4, 0.3, 0.2, 0.1])
    m.race.prices[4].sportsbet_win = None  # the runner asked about is priced; another is not
    r = check_offer(m, 2, OddsBoost(100.0), budget=10_000)  # absurdly generous
    assert r.verdict == "hold" and r.stake == 0 and "Sportsbet-only" in r.reason
    assert next(s for s in r.scenarios if s.key == "sportsbet_only").ev is None


# --- Kelly ----------------------------------------------------------------------------------


def test_single_outcome_stake_is_closed_form_quarter_kelly():
    p, price, budget = 0.2, 5.5, 10_000.0
    full = budget * (p * price - 1) / (price - 1)  # f* = edge / (price - 1)
    assert growth_stake(OddsBoost(price), {"win": p}, budget) == pytest.approx(full, rel=1e-6)
    expected = int(0.25 * full)
    assert 0.25 * full < 0.05 * budget  # below the cap, so the cap is not what is tested
    assert size_stake(OddsBoost(price), {"win": p}, budget) == expected


def test_stake_is_capped_at_five_percent_and_never_negative():
    assert size_stake(OddsBoost(20.0), {"win": 0.5}, 1_000) == 50  # huge edge: the 5% cap
    for p in (0.01, 0.05, 0.2, 0.5):
        for price in (1.2, 2.0, 5.0, 30.0):
            for kind in (OddsBoost(price), PlaceOnly(price, 0.25, 4), EachWay(price, 0.25, 3)):
                c = {leg.name: p / len(kind.legs()) for leg in kind.legs()}
                s = size_stake(kind, c, 200)
                assert s >= 0 and s <= 10
    assert size_stake(OddsBoost(3.0), {"win": 0.3}, 1_000) == 0  # EV < 0
    assert size_stake(OddsBoost(3.0), {"win": 0.5}, 0) == 0


def test_each_way_stake_is_an_even_number_so_the_halves_match():
    for budget in (150, 333, 1_000, 7_777):
        s = size_stake(EachWay(11.0, 0.25, 4), {"win": 0.15, "placed": 0.3}, budget)
        assert s % 2 == 0


def test_multi_outcome_stake_maximises_log_growth_over_the_joint_outcomes():
    offer, chances, budget = EachWay(9.0, 0.25, 4), {"win": 0.14, "placed": 0.30}, 1_000.0

    def growth(s):
        lose = 1 - 0.44
        return lose * math.log(1 - s / budget) + sum(
            chances[leg.name] * math.log(1 + leg.net(s) / budget) for leg in offer.legs()
        )

    best = growth_stake(offer, chances, budget)
    assert 0 < best < budget
    assert growth(best) >= max(growth(best * f) for f in (0.5, 0.8, 0.95, 1.05, 1.2, 2.0)) - 1e-12


def test_money_back_stake_is_reduced_by_the_cap():
    chances = {"win": 0.25, "refund": 0.2}
    free = growth_stake(MoneyBack(4.4, {2}, None), chances, 1_000.0)
    capped = growth_stake(MoneyBack(4.4, {2}, 5.0), chances, 1_000.0)
    assert 0 < capped < free


def test_a_zero_stake_is_a_hold_never_a_bet_without_dollars():
    m = model_of([0.4, 0.3, 0.2, 0.1])
    r = check_offer(m, 3, OddsBoost(1.5 / m.runners[3].win), budget=10)  # real edge, $10 budget
    assert r.min_ev > MIN_EV_BUFFER and r.stake == 1 and r.verdict == "bet"  # lifted to $1
    for p in (0.2, 0.5):
        r = check_offer(m, 3, OddsBoost(9.0), budget=200 * p)
        assert (r.verdict == "bet") == (r.stake > 0)


# --- research sanity: a 24-runner Cup-like field --------------------------------------------

CUP = [
    5.5,
    7,
    8,
    9,
    11,
    13,
    15,
    17,
    19,
    21,
    26,
    31,
    34,
    41,
    51,
    61,
    71,
    81,
    101,
    126,
    151,
    201,
    251,
    301,
]


@pytest.fixture(scope="module")
def cup():
    return model_of([1 / x for x in CUP], sportsbet=CUP)


def test_quarter_odds_four_places_place_half_is_positive_for_mid_priced_runners(cup):
    mid = [i for i, x in enumerate(CUP, 1) if 21 <= x <= 101]
    assert len(mid) >= 8
    for i in mid:
        r = check_offer(cup, i, PlaceOnly(CUP[i - 1], 0.25, 4), budget=5_000)
        assert all(s.ev > 0 for s in r.scenarios), (CUP[i - 1], r.as_dict()["ev"])
        assert r.min_ev >= MIN_EV_BUFFER
    big = check_offer(cup, 15, PlaceOnly(51.0, 0.25, 4), budget=5_000)  # $51 runner
    assert big.verdict == "bet" and 1 <= big.stake <= 250
    three = check_offer(cup, 15, PlaceOnly(51.0, 0.25, 3), budget=5_000)
    assert three.min_ev < big.min_ev  # the 4th place is worth a lot


def test_quarter_odds_three_places_each_way_is_negative_at_every_price(cup):
    for i, price in enumerate(CUP, 1):
        r = check_offer(cup, i, EachWay(price, 0.25, 3), budget=5_000)
        evs = {s.key: s.ev for s in r.scenarios}
        assert r.min_ev < 0 and r.verdict == "hold" and r.stake == 0, (price, evs)
        assert evs["flb_1_14"] < 0, price  # once the long-shot bias is taken out
        assert evs["flb_1_14"] > -0.30, price  # and no worse than the research range (-8% to -26%)


def test_four_places_lifts_each_way_towards_break_even(cup):
    for i, price in enumerate(CUP, 1):
        three = check_offer(cup, i, EachWay(price, 0.25, 3), budget=200).min_ev
        four = check_offer(cup, i, EachWay(price, 0.25, 4), budget=200).min_ev
        assert four > three
    fifth = check_offer(cup, 10, EachWay(21.0, 0.2, 4), budget=200).min_ev
    quarter = check_offer(cup, 10, EachWay(21.0, 0.25, 4), budget=200).min_ev
    assert fifth < quarter  # 1/5 odds is worth less than 1/4 odds


def test_cup_field_uses_exact_for_early_places_and_simulation_beyond():
    pos = position_probs({i: 1 / x / sum(1 / y for y in CUP) for i, x in enumerate(CUP, 1)})
    assert pos.simulated == frozenset({4, 5}) and pos.draws >= 200_000
    assert pos.method.startswith("places 1-3 exact")


# --- the endpoint ---------------------------------------------------------------------------


@pytest.fixture
def client():
    board = board_with(Router(), Clock(START))
    board.load_card_now(wait=True)
    app = create_app(load_settings(ENV), board, start_background=False)
    with TestClient(app) as c:
        yield c


def get(client, query: str, **kw):
    return client.get(f"/api/offer?{query}", auth=AUTH, **kw)


TYPES = {
    "each_way": "type=each_way&fraction=1/4&places=4",
    "place_only": "type=place_only&fraction=1/4&places=4",
    "money_back": "type=money_back&positions=2,3&cap=50",
    "odds_boost": "type=odds_boost&boosted_price=4.5",
}
KEYS = {"verdict", "stake", "reason", "ev", "min_ev", "scenarios", "positions_used", "budget"}


@pytest.mark.parametrize("kind", TYPES)
def test_endpoint_returns_the_json_shape(client, kind):
    r = get(client, f"race=2&runner=4&{TYPES[kind]}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert KEYS <= set(body) and body["verdict"] in ("bet", "hold")
    assert isinstance(body["stake"], int) and (body["verdict"] == "bet") == (body["stake"] > 0)
    assert set(body["ev"]) == {
        "consensus",
        "flb_1_14",
        "sportsbet_only",
        "discount_low",
        "discount_high",
        "mc_2se",
    }
    assert body["min_ev"] == min(body["ev"].values())
    assert body["budget"] == 200 and isinstance(body["reason"], str) and "\n" not in body["reason"]
    used = body["positions_used"]
    assert len(used["finish"]) == len(used["top"]) == len(used["se"]) == 5
    assert used["method"] == "exact"  # 8 runners: every finishing order can be enumerated
    assert body["race"] == 2 and body["runner_name"] == "Night Patrol"
    assert body["prices_as_at"] and "UTC" not in body["prices_as_at"]
    assert (body["break_even_c"] is not None) == (kind == "money_back")


def test_endpoint_price_defaults_to_the_live_sportsbet_price(client):
    body = get(client, f"race=2&runner=4&{TYPES['each_way']}").json()
    assert body["offer"]["price"] == 3.9 == body["sportsbet_price"]
    body = get(client, f"race=2&runner=4&{TYPES['each_way']}&price=4.2").json()
    assert body["offer"]["price"] == 4.2


def test_endpoint_budget_comes_from_the_query_then_the_cookie_then_200(client):
    q = f"race=2&runner=4&{TYPES['odds_boost']}"
    assert get(client, q).json()["budget"] == 200
    client.cookies.set("budget", "350")
    assert get(client, q).json()["budget"] == 350
    assert get(client, q + "&budget=$75").json()["budget"] == 75
    client.cookies.clear()


def test_endpoint_a_boost_that_pays_gets_a_bet_with_dollars(client):
    body = get(client, "race=2&runner=8&type=odds_boost&boosted_price=40&budget=2000").json()
    assert body["verdict"] == "bet" and body["stake"] >= 1 and "BET $" in body["reason"]
    assert body["min_ev"] >= MIN_EV_BUFFER
    poor = get(client, "race=2&runner=1&type=odds_boost&boosted_price=2.0&budget=2000").json()
    assert poor["verdict"] == "hold" and poor["stake"] == 0


@pytest.mark.parametrize(
    "query, fragment",
    [
        ("race=2&runner=4&type=lay&price=3", "type must be one of"),
        ("race=2&runner=4", "type must be one of"),
        ("race=2&type=odds_boost&boosted_price=4", "runner is required"),
        ("runner=4&type=odds_boost&boosted_price=4", "race is required"),
        ("race=two&runner=4&type=odds_boost&boosted_price=4", "race must be a whole number"),
        ("race=2&runner=99&type=odds_boost&boosted_price=4", "not a starter"),
        ("race=2&runner=4&type=odds_boost", "boosted_price is required"),
        ("race=2&runner=4&type=odds_boost&boosted_price=1", "above 1"),
        ("race=2&runner=4&type=odds_boost&boosted_price=nan", "finite"),
        ("race=2&runner=4&type=each_way&places=4", "fraction is required"),
        ("race=2&runner=4&type=each_way&fraction=1/4", "places is required"),
        ("race=2&runner=4&type=each_way&fraction=2&places=4", "fraction must"),
        ("race=2&runner=4&type=each_way&fraction=1/0&places=4", "fraction must"),
        ("race=2&runner=4&type=place_only&fraction=1/4&places=9", "places must be"),
        ("race=2&runner=4&type=place_only&fraction=1/4&places=4&price=0.5", "above 1"),
        ("race=2&runner=4&type=money_back&cap=50", "positions is required"),
        ("race=2&runner=4&type=money_back&positions=1&cap=50", "positions must be"),
        ("race=2&runner=4&type=money_back&positions=2", "cap is required"),
        ("race=2&runner=4&type=money_back&positions=2&cap=0", "cap must be above"),
        ("race=2&runner=4&type=money_back&positions=2&cap=50&c=2", "c (bonus bet"),
        (
            "race=2&runner=4&type=odds_boost&boosted_price=4&fraction=1/4",
            "not valid for odds_boost",
        ),
        ("race=2&runner=4&type=odds_boost&boosted_price=4&bonus=1", "not valid for odds_boost"),
        ("race=2&race=2&runner=4&type=odds_boost&boosted_price=4", "once"),
        ("race=2&runner=4&type=odds_boost&boosted_price=4&budget=lots", "budget must be"),
        ("race=2&runner=4&type=odds_boost&boosted_price=4&budget=0", "budget must be"),
    ],
)
def test_endpoint_rejects_bad_requests_with_a_clear_message(client, query, fragment):
    r = get(client, query)
    assert r.status_code == 400, r.text
    assert fragment in r.json()["detail"]


def test_endpoint_race_not_on_the_card_is_404_and_a_finished_race_is_400(client, monkeypatch):
    assert get(client, "race=9&runner=1&type=odds_boost&boosted_price=4").status_code == 404
    monkeypatch.setattr(offer_api, "betting_open", lambda race: False)
    r = get(client, "race=2&runner=4&type=odds_boost&boosted_price=4")
    assert r.status_code == 400 and "already run" in r.json()["detail"]


def test_endpoint_sits_behind_the_same_password_as_the_pages(client):
    assert (
        client.get("/api/offer?race=2&runner=4&type=odds_boost&boosted_price=4").status_code == 401
    )


def test_leg_chances_floor_at_zero(monkeypatch):
    monkeypatch.setattr(probability, "EXACT_LIMIT", 1)
    pos = position_probs({1: 0.5, 2: 0.3, 3: 0.2})
    assert leg_chances(OddsBoost(3.0), pos, 1, se_multiple=1000.0) == {"win": 0.0}


def test_small_positive_stake_is_lifted_to_one_dollar(cup):
    """Owner: a +EV offer whose quarter-Kelly stake rounds to $0 on a small budget bets $1."""
    i = next(i for i, x in enumerate(CUP, 1) if x == 21)
    r = check_offer(cup, i, PlaceOnly(21.0, 0.25, 4), budget=200)
    assert r.min_ev >= MIN_EV_BUFFER and r.verdict == "bet" and r.stake == 1
    neg = check_offer(cup, i, EachWay(21.0, 0.25, 3), budget=200)
    assert neg.verdict == "hold" and neg.stake == 0
