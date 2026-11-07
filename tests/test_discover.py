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
    assert D.leg_of(row("1", 1.5, 0.6, fam="h2h"), "nhl", NOW) is not None
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
