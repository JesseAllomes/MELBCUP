# ruff: noqa: E501
"""Best multis across sports: exact for its pool, one leg per game, honest exclusions."""

import itertools
import math
from datetime import UTC, datetime, timedelta

from melbcup import discover as D

NOW = datetime(2026, 11, 7, 10, tzinfo=UTC)


def row(ev, price, p, sport="football", fam="line", start_h=3, seen_min=5, **kw):
    return {
        "market_prob": p,
        "price_decimal": price,
        "event_id": ev,
        "market_family": fam,
        "event_start_utc": (NOW + timedelta(hours=start_h)).isoformat(),
        "quote_observed_at_utc": (NOW - timedelta(minutes=seen_min)).isoformat(),
        "participant_name": f"team{ev}",
        "market_name_raw": fam,
        "key": f"{ev}-{price}",
        **kw,
    }


def legs(rows, sport="football"):
    return [g for r in rows if (g := D.leg_of(r, sport, NOW))]


def test_exclusions():
    assert D.leg_of(row("1", 1.5, 0.6), "nba", NOW) is not None
    assert D.leg_of(row("1", 1.5, 0.6, fam="h2h"), "nba", NOW) is None  # owner's NBA H2H policy
    assert D.leg_of(row("1", 1.5, 0.6, fam="h2h"), "nhl", NOW) is None  # every sport (owner, 2026-11-09)
    assert D.leg_of(row("1", 1.5, 0.6, seen_min=4 * 60), "nhl", NOW) is None  # stale price
    assert D.leg_of(row("1", 1.5, None), "nhl", NOW) is None  # no fair chance: never invented
    assert D.leg_of(row("1", 1.5, 0.6, start_h=-1), "nhl", NOW) is None  # started
    assert D.leg_of(row("1", 1.5, 0.6, suspended=True), "nhl", NOW) is None


def test_matches_brute_force_and_one_leg_per_game():
    rows = [
        row(str(e), pr, p)
        for e, pr, p in [
            (1, 1.30, 0.74),
            (1, 1.80, 0.53),
            (2, 1.45, 0.66),
            (2, 2.10, 0.45),
            (3, 1.20, 0.80),
            (4, 1.60, 0.60),
            (4, 2.50, 0.38),
            (5, 1.10, 0.88),
            (6, 3.20, 0.29),
            (6, 1.35, 0.70),
        ]
    ]
    L = legs(rows)
    got = D.best_multis(D.pool(L), bands=((2.0, 3.0), (3.0, 5.0)))
    for res, (lo, hi) in zip(got, ((2.0, 3.0), (3.0, 5.0)), strict=True):
        best = None
        for k in range(2, 7):
            for combo in itertools.combinations(L, k):
                if len({g["event_id"] for g in combo}) < k:
                    continue
                price = math.prod(g["price"] for g in combo)
                if lo <= price < hi:
                    lp = sum(math.log(g["p"]) for g in combo)
                    best = lp if best is None or lp > best else best
        pick = res["pick"]
        assert pick is not None
        assert len({g["event_id"] for g in pick["legs"]}) == len(pick["legs"])
        assert lo <= pick["price"] < hi
        assert abs(math.log(pick["p_all"]) - best) < 0.02  # log-price bins: within rounding


def test_empty_range_says_so():
    res = D.best_multis(
        D.pool(legs([row("1", 1.2, 0.8), row("2", 1.2, 0.8)])), bands=((10.0, 20.0),)
    )
    assert res[0]["pick"] is None and "right now" in res[0]["reason"]


def test_one_fail_chance_is_exact_for_independent_legs():
    L = legs([row("1", 1.5, 0.6), row("2", 1.6, 0.55), row("3", 1.4, 0.7)])
    res = D.best_multis(D.pool(L), bands=((3.0, 4.0),))[0]["pick"]
    ps = [g["p"] for g in res["legs"]]
    brute = sum(
        math.prod(ps[j] if j != i else 1 - ps[i] for j in range(len(ps))) for i in range(len(ps))
    )
    assert abs(res["p_one_fail"] - brute) < 1e-9


def test_review_23_equal_price_higher_chance_survives_pruning():
    worse = [row("1", 2.0, 0.40 + i / 1000) for i in range(8)]
    good = row("1", 2.0, 0.50)
    group = D.pool(legs(worse + [good]))[0]
    assert max(g["p"] for g in group) == 0.50


def test_review_24_boundary_multi_is_found():
    L = legs([row("A", 1.500, 0.62), row("A", 1.505, 0.61), row("B", 1.332, 0.70)])
    pick = D.best_multis(D.pool(L), bands=((2.0, 3.0),))[0]["pick"]
    assert pick is not None and abs(pick["price"] - 2.00) < 0.01
    assert abs(math.prod(g["price"] for g in pick["legs"]) - 1.505 * 1.332) < 1e-9


def test_review_25_matches_brute_force_on_random_slates():
    import random

    rnd = random.Random(7)
    bands = ((1.5, 2.0), (2.0, 3.0), (3.0, 5.0), (5.0, 10.0))
    for _ in range(25):
        rows = []
        for e in range(6):
            for _ in range(rnd.randint(1, 4)):
                price = round(rnd.uniform(1.05, 3.2), 3)
                p = min(0.97, max(0.31, 1 / price * rnd.uniform(0.88, 0.99)))
                rows.append(row(str(e), price, round(p, 4)))
        L = legs(rows)
        got = D.best_multis(D.pool(L), bands=bands)
        for res, (lo, hi) in zip(got, bands, strict=True):
            best = None
            for k in range(2, 7):
                for combo in itertools.combinations(L, k):
                    if len({g["event_id"] for g in combo}) < k:
                        continue
                    if lo <= math.prod(g["price"] for g in combo) < hi:
                        lp = sum(math.log(g["p"]) for g in combo)
                        best = lp if best is None or lp > best else best
            if best is None:
                assert res["pick"] is None
            else:
                assert res["pick"] is not None, (lo, hi)
                assert math.log(res["pick"]["p_all"]) >= best - 1e-9, (lo, hi)


def test_research_upper_limit_counterexample():
    """Further research 7 Nov: A1 1.50/.60, A2 1.58/.62, B1 1.35/.70 in [2.00, 2.10) -> 2.025."""
    L = legs([row("A", 1.50, 0.60), row("A", 1.58, 0.62), row("B", 1.35, 0.70)])
    pick = D.best_multis(D.pool(L), bands=((2.00, 2.10),))[0]["pick"]
    assert pick is not None and abs(pick["price"] - 2.025) < 0.01


def test_narrow_ranges_match_brute_force():
    import random

    rnd = random.Random(11)
    misses = 0
    for _ in range(300):
        rows = []
        for e in range(5):
            for _ in range(rnd.randint(1, 4)):
                price = round(rnd.uniform(1.05, 2.6), 2)
                rows.append(
                    row(str(e), price, round(min(0.97, 1 / price * rnd.uniform(0.9, 0.99)), 4))
                )
        L = legs(rows)
        lo = round(rnd.uniform(1.6, 6.0), 2)
        band = (lo, round(lo * 1.05, 2))
        res = D.best_multis(D.pool(L), bands=(band,))[0]
        best = None
        for k in range(2, 6):
            for combo in itertools.combinations(L, k):
                if (
                    len({g["event_id"] for g in combo}) == k
                    and band[0] <= math.prod(g["price"] for g in combo) < band[1]
                ):
                    lp = sum(math.log(g["p"]) for g in combo)
                    best = lp if best is None or lp > best else best
        if best is not None and (
            res["pick"] is None or math.log(res["pick"]["p_all"]) < best - 1e-9
        ):
            misses += 1
    assert misses == 0, misses


def test_legs_filter_and_by_legs_agree():
    groups = [[{**g, "event": str(i)} for g in legs([row(str(i), 1.5, 0.6)])] for i in range(5)]
    for n in (2, 3):
        got = D.best_multis(groups, ((2.0, 20.0),), legs=n)[0]["pick"]
        assert got and len(got["legs"]) == n
        assert D.best_multis_by_legs(groups, ((2.0, 20.0),), (n,))[n][0]["pick"]["price"] == got["price"]


def test_first_refresh_starts_on_a_fresh_container(monkeypatch):
    """A container younger than REFRESH_S must still compute its first result (it waited 10 min)."""
    calls = []
    monkeypatch.setattr(D, "_refresh", lambda: calls.append(1))
    monkeypatch.setattr(D.time, "monotonic", lambda: 30.0)  # 30 s after boot
    monkeypatch.setitem(D._state, "result", None)
    monkeypatch.setitem(D._state, "at", 0.0)
    monkeypatch.setitem(D._state, "busy", False)
    D.latest(wait=True)
    assert calls == [1]
