import itertools
import json
import math

from melbcup import ranker as R


def leg(player, game, chance, price, stat="points", team="X", under=False, **kw):
    return {
        "player": player,
        "game": game,
        "team": team,
        "stat": stat,
        "line": 10,
        "under": under,
        "label": f"{player} {stat}",
        "price": price,
        "chance": chance,
        "model": None,
        "market": chance,
        **kw,
    }


def pool():
    return [leg(f"P{i}", f"G{i}", 0.6 + 0.01 * i, 1.5 + 0.05 * i) for i in range(8)]


def test_band_respected_and_objective_label():
    r = R.rank(pool(), 3.0)
    assert r["pick"] is not None and r["objective"] == R.OBJ_CHANCE
    for t in r["top"]:
        assert 3.0 <= t["price"] <= 3.0 * 1.15 + 1e-3
        assert t["p_exactly_one_fail"] >= 0
    assert R.rank(pool(), 3.0, objective="ev")["objective"] == R.OBJ_EV


def test_promo_payoff_plugs_in():
    r = R.rank(pool(), 3.0, objective="promo", payoff=lambda pa, p1, price: pa * price + p1)
    assert r["objective"] == R.OBJ_PROMO and r["pick"]["value"] > 0


def test_one_fail_matches_brute_force():
    legs = [
        leg("A", "G1", 0.7, 1.4),
        leg("B", "G2", 0.6, 1.6),
        leg("C", "G3", 0.8, 1.3),
        leg("D", "G4", 0.55, 1.8),
    ]
    brute = 0.0
    for pat in itertools.product([0, 1], repeat=4):
        if sum(pat) == 1:
            brute += math.prod(
                (1 - g["chance"]) if f else g["chance"] for g, f in zip(legs, pat, strict=True)
            )
    assert abs(R.p_exactly_one_fail(legs) - brute) < 1e-12
    assert (
        abs(
            R.p_exactly_one_fail(legs[:3])
            - sum(
                math.prod(
                    (1 - g["chance"]) if f else g["chance"]
                    for g, f in zip(legs[:3], p, strict=True)
                )
                for p in itertools.product([0, 1], repeat=3)
                if sum(p) == 1
            )
        )
        < 1e-12
    )


def test_h2h_excluded_by_default():
    h = leg("T1", "G9", 0.9, 1.2, market_type="h2h")
    base = pool()
    r = R.rank(base + [h], 3.0)
    assert all(x["label"] != h["label"] for x in r["pick"]["legs"])
    assert not R.is_player_leg(h)
    assert R.rank([h, h | {"player": "T2"}], 1.4, include_h2h=True, min_legs=2)["pick"] is not None


def test_empty_result_is_valid():
    r = R.rank(pool(), 500.0)
    assert r["pick"] is None and r["reason"] and r["objective"]
    r = R.rank([leg("A", "G", 0.1, 5.0)], 5.0)
    assert r["pick"] is None


def test_correlation_changes_joint():
    a = leg("A", "G", 0.7, 1.4, team="X")
    b = leg("A", "G", 0.7, 1.4, stat="reboundsTotal", team="X")
    assert R.joint([a, b]) > 0.49 + 0.02  # positively correlated same-player stats
    b_under = dict(b, under=True)
    assert R.joint([a, b_under]) < 0.7 * 0.7
    c = leg("B", "G2", 0.7, 1.4)
    assert abs(R.joint([a, c]) - 0.49) < 1e-9


def test_shadow_and_log_row():
    legs = [
        dict(
            g, model=g["chance"] - 0.1, books={"a": g["chance"], "b": g["chance"] - 0.02}, book="a"
        )
        for g in pool()
    ]
    champ = R.rank(legs, 3.0)
    sh = R.shadow_picks(legs, 3.0)
    assert set(sh) == {"blend_0.25", "blend_0.5", "loo_consensus"}
    row = R.shadow_log_row("2026-11-07T00:00:00Z", 3.0, champ, sh)
    json.dumps(row)
    assert row["champion"] and row["objective"] == R.OBJ_CHANCE


def test_unverified_and_stale_never_recommended():
    legs = pool()
    assert R.quote_status(dict(legs[0], price=None)) == "unverified"
    stale = [dict(g, quoted_at=0) for g in legs]
    r = R.rank(stale, 3.0, as_of=10_000)
    assert r["pick"] is None and r["n_unverified_legs"] == len(legs)
    fresh = [dict(g, quoted_at=9_900) for g in legs]
    p = R.rank(fresh, 3.0, as_of=10_000)["pick"]
    assert p and p["quote_status"] == "estimated_product_price"
