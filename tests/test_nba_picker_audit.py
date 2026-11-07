# ruff: noqa: E501
"""NBA multi picker, 2026-11-07 audits (Fable AUDIT.md (a)/(c); deep-edge investigation s3-6 and
acceptance list 14; patch spec P0/P1 and QA gates). One test per acceptance item."""

import json
import math
import os

import pytest

from melbcup import nba_legs as N
from melbcup import promos, ranker

HERE = os.path.dirname(__file__)
G1, G2 = "Philadelphia 76ers @ Cleveland Cavaliers", "Cleveland Cavaliers @ Oklahoma City Thunder"
T1, T2 = "2026-11-05T00:00:00Z", "2026-11-06T00:30:00Z"


def mk(game, start, player, stat, line, under, price, src="ou", team="T", ev=None, **kw):
    return {
        "game": game,
        "startsAt": start,
        "event": ev or game,
        "player": player,
        "team": team,
        "stat": stat,
        "line": line,
        "under": under,
        "price": price,
        "src": src,
        "period": "full",
        "label": f"{player} {'U' if under else 'O'}{line} {stat}",
        "model": None,
        **kw,
    }


def priced(legs, market=None):
    N.apply_market(legs, market if market is not None else N.market_probs({"x": legs}))
    return legs


# 1/3: event-aware identity -------------------------------------------------------------------
def test_same_player_in_two_games_never_shares_a_key_or_a_price():
    a = mk(G1, T1, "Donovan Mitchell", "points", 32, False, 4.75, "alt")
    b = mk(G2, T2, "Donovan Mitchell", "points", 32, False, 9.00, "alt")
    assert N.bet_key(a) != N.bet_key(b)
    m = N.feed_market([a, b])
    assert len(m) == 2 and m[N.bet_key(a)] > 1.5 * m[N.bet_key(b)]
    assert N.market_probs({"pb": [a], "sb": [b]})[N.bet_key(a)] == pytest.approx(m[N.bet_key(a)])
    assert N.better_elsewhere(a, {N.bet_key(b): 9.0}, "sb") is None  # another game: not the bet


def test_same_game_matches_across_agencies_despite_ids_and_a_ten_minute_start_offset():
    pb = mk(G1, "2026-11-05T00:00:00Z", "A", "points", 20, False, 2.0, ev="2968005")
    sb = mk(
        G1.replace("Philadelphia 76ers", "Philadelphia 76ers"),
        "2026-11-05T00:10:00Z",
        "A",
        "points",
        20,
        False,
        2.1,
        ev="sb77",
    )
    assert N.bet_key(pb) == N.bet_key(sb)
    assert N.better_elsewhere(pb, {N.bet_key(sb): 2.1}, "sb") == {"code": "sb", "diff": 0.1}
    # game date is the US Eastern one: 00:30Z on the 6th is still the 5th in New York
    assert N.event_id(mk(G1, "2026-11-06T00:30:00Z", "A", "points", 1, False, 2))[2] == "2026-11-05"
    other = mk("Philadelphia 76ers @ Boston Celtics", T1, "A", "points", 20, False, 2.0)
    assert N.bet_key(other) != N.bet_key(pb)  # different opponent: never the same bet


# 4/5/11: same-outcome equivalence ---------------------------------------------------------------
def test_over_5_5_and_6_plus_are_one_predicate_best_price_kept_and_period_blocks_it():
    ou = mk(G1, T1, "Durant", "reboundsTotal", 6, False, 2.15, "ou")  # Over 5.5
    alt = mk(G1, T1, "Durant", "reboundsTotal", 6, False, 2.23, "alt")  # 6+
    assert N.bet_key(ou) == N.bet_key(alt)
    legs = priced([ou, alt])
    kept = N.dedupe(legs)
    assert (
        len(kept) == 1
        and kept[0]["price"] == 2.23
        and kept[0]["same_as"] == [{"price": 2.15, "src": "ou"}]
    )
    half = dict(alt, period="1h")
    assert N.bet_key(half) != N.bet_key(ou)
    assert len(N.dedupe([ou, half])) == 2


def test_equivalent_quote_never_puts_one_outcome_in_a_multi_twice():
    legs = priced(
        [
            mk(G1, T1, "Durant", "reboundsTotal", 6, False, 2.15, "ou", ev="1"),
            mk(G1, T1, "Durant", "reboundsTotal", 6, False, 2.23, "alt", ev="1"),
            mk(G1, T1, "Reaves", "assists", 3, False, 1.5, "alt", ev="1"),
            mk(G2, T2, "Mitchell", "points", 15, False, 1.6, "alt", ev="2"),
        ]
    )
    cross, same = N.stacks(legs, floor=0.0)
    for m in cross + same:
        assert len({d["player"] for d in m["detail"]}) == len(m["detail"])
        assert not any(d["price"] == 2.15 for d in m["detail"])  # the better quote stands in


# 2/6: margin only within the native pair; rung margin table -----------------------------------------
def test_alternate_over_is_not_the_counterpart_of_a_main_under():
    over = mk(G1, T1, "A", "points", 20, False, 1.9)
    under = mk(G1, T1, "A", "points", 20, True, 1.9)
    alt = mk(G1, T1, "A", "points", 20, False, 2.4, "alt")
    base = N.feed_market([over, under])
    both = N.feed_market([over, under, alt])
    assert both[N.bet_key(over)] == pytest.approx(base[N.bet_key(over)]) == pytest.approx(0.5)
    lone = N.feed_market(
        [under, alt]
    )  # no main over: the under is single-sided, never paired with alt
    assert lone[N.bet_key(under)] == pytest.approx(math.exp(-0.076) / 1.9)
    assert lone[N.bet_key(alt)] == pytest.approx(math.exp(-0.063) / 2.4)


@pytest.mark.parametrize(
    "price,m", [(1.25, 0.067), (1.3, 0.067), (1.8, 0.076), (2.5, 0.063), (3.0, 0.10), (6.0, 0.10)]
)
def test_single_sided_margin_bands(price, m):
    assert N.rung_margin(price) == m
    assert N.single_chance(price) == pytest.approx(math.exp(-m) / price)


# 3: PointsBet Over/Under enters the pool, both sides ------------------------------------------------
def test_pointsbet_over_under_markets_enter_the_pool_both_sides():
    d = json.load(open(os.path.join(HERE, "fixtures", "pointsbet_nba_event.json")))
    det = d["detail"]
    ms = (det.get("fixedOddsMarkets") or []) + (det.get("specialFixedOddsMarkets") or [])
    ev = {
        "event": d["listing"]["key"],
        "name": d["listing"]["name"],
        "startsAt": d["listing"]["startsAt"],
        "markets": [{"group": m.get("groupName"), "outcomes": m.get("outcomes") or []} for m in ms],
    }
    board = {"day": "20261107", "params": {}, "games": [], "players": []}
    legs, _ = N.legs_from([ev], board)
    ou = [g for g in legs if g["src"] == "ou"]
    assert any(g["under"] for g in ou) and any(not g["under"] for g in ou)
    gordon = {(g["stat"], g["line"], g["under"]) for g in ou if g["player"] == "Aaron Gordon"}
    assert ("points", 13, False) in gordon and ("points", 13, True) in gordon  # Over/Under 12.5
    assert not any("+" in g["label"] and g["src"] == "ou" for g in legs)
    assert {g["stat"] for g in ou} == set(N.PB_OU_GROUP.values())  # no combined-stat legs
    rung = next(
        g
        for g in legs
        if g["player"] == "Aaron Gordon"
        and g["stat"] == "points"
        and g["line"] == 13
        and g["src"] == "alt"
    )
    over = next(
        g
        for g in ou
        if g["player"] == "Aaron Gordon"
        and g["stat"] == "points"
        and g["line"] == 13
        and not g["under"]
    )
    assert N.bet_key(rung) == N.bet_key(over)  # Over 12.5 is 13+


# 5: monotone ladders -------------------------------------------------------------------------------------
def test_ladder_probabilities_never_rise_and_a_big_conflict_is_flagged_and_left_out():
    g = lambda k, price: mk(G1, T1, "Scoot Henderson", "points", k, False, price, "alt")  # noqa: E731
    l19, l20 = g(19, 8.0), g(20, 10.0)
    # the app's 11.16% / 19+ vs 14.88% / 20+: a 3.72-point inversion
    mkt = N.monotone({N.bet_key(l19): 0.1116, N.bet_key(l20): 0.1488})
    assert mkt[N.bet_key(l20)] <= mkt[N.bet_key(l19)] + 1e-12
    assert mkt.flagged == {N.bet_key(l19), N.bet_key(l20)}
    legs = [l19, l20, mk(G2, T2, "Other", "points", 10, False, 1.5, "alt", chance=0.7)]
    N.apply_market(legs, mkt)
    assert legs[0]["conflict"] and legs[1]["conflict"] and not legs[2]["conflict"]
    assert all(not x["conflict"] for x in N._auto(legs)) and len(N._auto(legs)) == 1
    small = N.monotone({N.bet_key(l19): 0.30, N.bet_key(l20): 0.31})  # 1 point: adjusted, kept
    assert small.flagged == frozenset() and small[N.bet_key(l20)] <= small[N.bet_key(l19)] + 1e-12


def test_every_adjacent_rung_is_ordered_after_the_fit():
    rows = {}
    for k, p in [(10, 0.9), (15, 0.55), (20, 0.57), (25, 0.2), (30, 0.21), (35, 0.05)]:
        rows[N.bet_key(mk(G1, T1, "P", "points", k, False, 2))] = p
    out = N.monotone(rows)
    ps = [out[k] for k in sorted(out, key=lambda k: k[3])]
    assert all(a >= b - 1e-12 for a, b in zip(ps, ps[1:], strict=False))
    unders = N.monotone(
        {
            N.bet_key(mk(G1, T1, "P", "points", k, True, 2)): p
            for k, p in [(10, 0.2), (15, 0.19), (20, 0.6)]
        }
    )
    ups = [unders[k] for k in sorted(unders, key=lambda k: k[3])]
    assert ups == sorted(ups)


# 6/9/10: leg counts ---------------------------------------------------------------------------------------
def _pool():
    out = []
    for i, (c, p) in enumerate([(0.55, 2.0), (0.86, 1.15), (0.9, 1.12), (0.8, 1.3)]):
        out.append(
            {
                "event": f"e{i}",
                "game": f"g{i}",
                "player": f"P{i}",
                "label": f"P{i}",
                "team": "T",
                "chance": c,
                "price": p,
            }
        )
    return out


def test_two_legs_compete_with_three_and_the_default_floor_is_two():
    import inspect

    for f in (N.top_stacks, N.best_stacks, N.best_stack, N.best_same_game):
        assert inspect.signature(f).parameters["min_legs"].default == 2
    groups = [[g] for g in _pool()]
    best = N.best_stack(groups, 2.0)
    assert len(best) >= 2
    three = N.best_stack(groups, 2.0, min_legs=3)
    c = lambda s: math.prod(g["chance"] for g in s)  # noqa: E731
    assert c(best) >= c(three) - 1e-12


def test_promo_minimum_legs_bind_only_the_promo_product():
    legs = [
        {
            "game": f"g{i}",
            "player": f"P{i}",
            "stat": "points",
            "label": f"P{i}",
            "chance": c,
            "price": p,
        }
        for i, (c, p) in enumerate(
            [(0.62, 1.6), (0.62, 1.6), (0.7, 1.4), (0.75, 1.3), (0.8, 1.25), (0.85, 1.2)]
        )
    ]
    plain = ranker.rank(legs, 2.5, objective="chance", min_leg_price=1.0)
    assert plain["pick"] is not None and len(plain["pick"]["legs"]) == 2
    pay = lambda pa, p1, price: pa * price + 0.5 * p1  # noqa: E731
    for need in (3, 4):
        r = ranker.rank(
            legs, 2.5, objective="promo", payoff=pay, promo_min_legs=need, min_leg_price=1.0
        )
        assert r["pick"] is not None and len(r["pick"]["legs"]) >= need
        assert all(len(t["legs"]) >= need for t in r["top"])
    r = ranker.rank(
        legs, 2.5, objective="promo", payoff=pay, promo_min_leg_price=1.3, min_leg_price=1.0
    )
    assert all(leg["price"] >= 1.3 for t in r["top"] for leg in t["legs"])


def test_promos_payoff_enforces_its_own_minimums_only_on_promo_rows():
    ok = promos.payoff(
        [0.7, 0.7, 0.7], 2.5, 10, refund_cap=10, redeem_rate=0.8, provenance="x", min_legs=3
    )
    assert any("money back" in r["funding"] for r in ok["rows"]) and ok["skipped"] == []
    two = promos.payoff(
        [0.7, 0.7], 2.5, 10, refund_cap=10, redeem_rate=0.8, provenance="x", min_legs=3
    )
    assert [r["funding"] for r in two["rows"]] == ["Cash"] and "3+ legs" in two["skipped"][0]
    cheap = promos.payoff(
        [0.7, 0.7, 0.7],
        2.5,
        10,
        refund_cap=10,
        provenance="x",
        min_leg_price=1.3,
        leg_prices=[1.3, 1.2, 1.4],
    )
    assert [r["funding"] for r in cheap["rows"]] == ["Cash"]
    plain = promos.payoff([0.7, 0.7], 2.5, 10)  # an ordinary 2-leg multi is untouched
    assert plain["skipped"] == [] and plain["rows"][0]["funding"] == "Cash"


# 7: the under lean is unchanged -----------------------------------------------------------------------------
def test_over_shade_is_unchanged():
    assert N.OVER_SHADE == 0.013 and N.shade(0.5, True) > 0.5 > N.shade(0.5, False)


# 8/12/13: same-player dependence --------------------------------------------------------------------------------
def _same_player(c1=0.6, c2=0.5):
    a = mk(G1, T1, "Star", "points", 25, False, 1 / c1, team="A", chance=c1)
    b = mk(G1, T1, "Star", "threePointersMade", 3, False, 1 / c2, team="A", chance=c2)
    return a, b


def test_same_player_points_and_threes_use_the_copula_for_both_win_and_one_fail():
    a, b = _same_player()
    both = N.joint_chance([a, b])
    assert both / (a["chance"] * b["chance"]) >= 1.2  # audits: 1.2-1.27x the product, at least
    one_fail = ranker.p_exactly_one_fail([a, b])
    indep = a["chance"] * (1 - b["chance"]) + b["chance"] * (1 - a["chance"])
    assert one_fail < indep - 0.05
    assert one_fail == pytest.approx(a["chance"] + b["chance"] - 2 * both, abs=0.02)


def test_same_player_pairs_stay_out_of_automatic_multis_unless_a_quote_allows_them():
    a, b = _same_player(0.7, 0.7)
    a["price"], b["price"] = 1.5, 1.5
    r = ranker.rank([a, b], 2.2, min_leg_price=1.0, min_leg_chance=0.3)
    assert r["pick"] is None  # the only 2.25 stack is the same player twice
    r = ranker.rank([a, b], 2.2, min_leg_price=1.0, min_leg_chance=0.3, allow_same_player=True)
    assert r["pick"] is not None
    games = N.same_game_many(priced([a, b]), [2.0])
    assert games[2.0] == []  # the same-game search takes one leg per player


def test_nested_thresholds_on_one_player_are_not_independent():
    lo = mk(G1, T1, "P", "points", 20, False, 1.4, chance=0.7)
    hi = mk(G1, T1, "P", "points", 25, False, 2.5, chance=0.4)
    assert N.joint_chance([lo, hi]) == pytest.approx(0.4)  # 25+ implies 20+: min, not 0.28
    band = mk(G1, T1, "P", "points", 26, True, 1.5, chance=0.9)  # under 25.5
    assert N.joint_chance([lo, band]) == pytest.approx(0.6)  # 20..25
    top = mk(G1, T1, "P", "points", 26, False, 3.0, chance=0.3)  # 26+ against under 25.5
    assert N.joint_chance([top, band]) == 0.0  # cannot both win


# 2/6 regression on a saved day ---------------------------------------------------------------------------------
def _day():
    """A small realistic slate: 5 games, 3 players each, PointsBet main O/U pairs plus alternate
    rungs (rung prices carry about 7% margin). Chances in 'before' are the old code's."""
    legs = []
    rnd = __import__("random").Random(11)
    for gi in range(5):
        game, start = f"Away{gi} @ Home{gi}", f"2026-11-0{5 + gi % 2}T0{gi}:00:00Z"
        for pi in range(3):
            who, stat = f"G{gi}P{pi}", "points"
            mu = rnd.uniform(12, 26)
            main = round(mu) + 0.5
            p_over = rnd.uniform(0.45, 0.55)
            mkc = 1.045
            legs += [
                mk(
                    game,
                    start,
                    who,
                    stat,
                    int(main) + 1,
                    False,
                    round(1 / (p_over * mkc), 2),
                    "ou",
                    ev=str(gi),
                ),
                mk(
                    game,
                    start,
                    who,
                    stat,
                    int(main) + 1,
                    True,
                    round(1 / ((1 - p_over) * mkc), 2),
                    "ou",
                    ev=str(gi),
                ),
            ]
            for k, c in ((int(main) - 8, 0.9), (int(main) - 4, 0.75), (int(main) + 4, 0.3)):
                legs.append(
                    mk(
                        game,
                        start,
                        who,
                        stat,
                        k,
                        False,
                        round(1 / (c * 1.07), 2),
                        "alt",
                        ev=str(gi),
                    )
                )
    return legs


def _old_market(legs):
    """What nba_legs.feed_market did before: key without the game, ladder rungs de-vigged by the
    pairs' mean overround, and an alternate over paired with the main under."""
    sides = {}
    for g in legs:
        sides.setdefault((g["player"], g["stat"], g["line"]), {})[g["under"]] = g["price"]
    books = [1 / v[False] + 1 / v[True] for v in sides.values() if len(v) == 2]
    over = sum(books) / len(books)
    out = {}
    for key, v in sides.items():
        for under, price in v.items():
            out[(*key, under)] = (1 / price) / (
                sum(1 / x for x in v.values()) if len(v) == 2 else over
            )
    return out


def test_regression_day_log_before_and_after_pick_chance_at_2_and_3(capsys):
    legs = _day()
    old = _old_market(legs)
    before = [
        dict(
            g,
            chance=N.shade(
                min(old[(g["player"], g["stat"], g["line"], g["under"])], 0.999), g["under"]
            ),
        )
        for g in legs
    ]
    after = priced([dict(g) for g in legs])
    rep = {}
    for tag, pool, ml in (("before", before, 3), ("after", after, 2)):
        cross, _ = N.stacks(pool, floor=0.5, min_legs=ml)
        rep[tag] = {m["target"]: (m["chance"], m["legs"], m["price"]) for m in cross}
    print("before (min 3 legs, old margins):", rep["before"])
    print("after  (min 2 legs, new margins):", rep["after"])
    for t in (2.0, 3.0):
        assert rep["before"][t][1] >= 3 and rep["after"][t][2] >= t
    # the rung chances the old code overstated are lower now
    rungs_b = [g["chance"] for g in before if g["src"] == "alt" and g["price"] >= 2.2]
    rungs_a = [g["chance"] for g in after if g["src"] == "alt" and g["price"] >= 2.2]
    assert sum(rungs_a) < sum(rungs_b)
    # picks are honest: re-score the old picks with the new chances; the new pick is not worse at $2
    old_pick, _ = N.stacks(before, floor=0.5, min_legs=3)
    by_label = {g["label"]: g for g in after}
    re_scored = math.prod(by_label[d["label"]]["chance"] for d in old_pick[0]["detail"])
    assert rep["after"][2.0][0] >= re_scored - 1e-9
