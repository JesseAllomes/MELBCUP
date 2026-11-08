"""NFL player-prop model: chance, blend, same-game correlation; NBA behaviour unchanged."""

from __future__ import annotations

import math

import pytest

from melbcup import nba_legs as N
from melbcup import nfl_legs, nfl_model as M

MEANS = {
    "qb one": {"name": "QB One", "team": "AAA", "pos": "QB", "mu": {"passingYards": 250.0, "passingTouchdowns": 1.6}},
    "wr one": {"name": "WR One", "team": "AAA", "pos": "WR", "mu": {"receivingYards": 70.0, "receptions": 5.0, "touchdowns": 0.4}},
    "wr two": {"name": "WR Two", "team": "BBB", "pos": "WR", "mu": {"receivingYards": 60.0}},
}


@pytest.fixture(autouse=True)
def means(monkeypatch):
    monkeypatch.setattr(M, "_means", dict(MEANS))
    nfl_legs._cache.update(at=0.0, legs=[])


def leg(player, stat, k, under=False, team="", chance=0.5):
    return {"player": player, "stat": stat, "line": k, "under": under, "team": team, "chance": chance,
            "price": 1.9, "event": "e1", "period": "full", "sport": "nfl"}


def test_chance_is_sane_and_monotone():
    cs = [M.mean_chance(250.0, "passingYards", k) for k in (150, 200, 250, 300, 350)]
    assert all(0 < c < 1 for c in cs) and cs == sorted(cs, reverse=True)
    assert 0.3 < M.mean_chance(250.0, "passingYards", 251) < 0.7
    assert M.mean_chance(0.4, "touchdowns", 1) < M.mean_chance(1.0, "touchdowns", 1)
    assert M.mean_chance(3.0, "nosuchstat", 1) is None


def test_under_is_complement():
    over, _ = M.model_chance("QB One", "passingYards", 246)
    under, _ = M.model_chance("QB One", "passingYards", 246, under=True)
    assert over + under == pytest.approx(1.0)
    assert M.model_chance("Nobody", "passingYards", 246) is None


def test_blend_weights():
    assert M.blend(0.7, None) == 0.7
    assert M.blend(0.5, 0.5) == pytest.approx(0.5)
    b = M.blend(0.7, 0.5)
    assert 0.5 < b < 0.7 and b == pytest.approx(N.blend(0.7, 0.5, M.BLEND_W))
    assert M.BLEND_W == 0.25
    assert N.BLEND_W == 0.0  # NBA keeps the market


def test_rho_sign_flips_for_unders_and_needs_teams():
    a, b = leg("QB One", "passingYards", 250, team="AAA"), leg("WR One", "receivingYards", 70, team="AAA")
    r = M.rho(a, b)
    assert r > 0.2
    assert M.rho(a, b | {"under": True}) == pytest.approx(-r)
    assert M.rho(a | {"under": True}, b | {"under": True}) == pytest.approx(r)
    assert M.rho(a, b | {"team": ""}) == 0.0
    assert M.rho(a, leg("WR Two", "receivingYards", 60, team="BBB")) != r  # an opponent: another relation


def test_same_game_chance_differs_from_independent_product():
    a = leg("QB One", "passingYards", 250, team="AAA", chance=0.5)
    b = leg("WR One", "receivingYards", 70, team="AAA", chance=0.5)
    assert N.joint_chance([a, b]) > 0.5 * 0.5 + 0.02  # stacked overs: positively correlated
    assert N.joint_chance([a, b | {"under": True}]) < 0.25 - 0.02
    c = b | {"team": ""}  # unknown team: independent, exactly the product
    assert N.joint_chance([a, c]) == pytest.approx(0.25)


def test_legs_from_rows_uses_model_and_market():
    def row(who, fam, side, line, price):
        return {"market_family": fam, "price_decimal": price, "participant_name": who, "side": side,
                "line_numeric": line, "line_raw": str(line), "market_name_raw": "x", "event_id": 1,
                "event_name": "A @ B", "event_start_utc": "2099-01-01T00:00:00Z", "market_subtype": "over_under"}

    rows = [row("QB One", "player_passing_yards", s, 249.5, 1.9) for s in ("over", "under")]
    rows += [row("Unknown Guy", "player_passing_yards", s, 249.5, 1.9) for s in ("over", "under")]
    legs = nfl_legs.legs_from_rows(rows)
    known = next(g for g in legs if g["player"] == "QB One" and not g["under"])
    other = next(g for g in legs if g["player"] == "Unknown Guy" and not g["under"])
    assert known["model"] is not None and known["team"] == "AAA" and known["market"] is not None
    assert other["model"] is None and other["team"] == ""


def test_nba_unchanged():
    a = {"player": "P", "team": "X", "stat": "points", "under": False}
    b = {"player": "P", "team": "X", "stat": "reboundsTotal", "under": False}
    assert N._rho(a, b) == N.CORR[("self", "pts", "reb")]
    assert N._rho(a, b | {"under": True}) == -N.CORR[("self", "pts", "reb")]
    legs = [{"model": 0.8, "under": False, "price": 1.5, "chance": 0.7, "stat": "points", "line": 20,
             "player": "P", "team": "X", "event": "e", "period": "full"}]
    N.apply_market(legs, {N.bet_key(legs[0]): 0.6})
    assert legs[0]["market"] == 0.6
    assert math.isclose(legs[0]["raw"], 0.6, abs_tol=1e-3)  # BLEND_W 0: the market, as before
