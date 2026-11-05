# ruff: noqa: E501
"""NBA legs, multis and settling (tools/nba/legs.py, tools/nba/settle.py)."""

import os
import sys

import pytest

pytest.importorskip("numpy")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "nba"))
pytest.importorskip("scipy")

import legs as L  # noqa: E402
import settle as S  # noqa: E402

PARAMS = {
    s: {"phi": 1.2, "ca": 1.0, "cb": 0.0}
    for s in ("points", "reboundsTotal", "assists", "threePointersMade")
}


def player(name, team, pts):
    return {
        "name": name,
        "team": team,
        "minutes": 32.0,
        "mu": {"points": pts, "reboundsTotal": 6.0, "assists": 4.0, "threePointersMade": 2.0},
    }


BOARD = {
    "day": "20261104",
    "params": PARAMS,
    "games": [
        {"name": "Philadelphia 76ers at Detroit Pistons", "teams": {"home": "DET", "away": "PHI"}},
        {"name": "Charlotte Hornets at Brooklyn Nets", "teams": {"home": "BKN", "away": "CHA"}},
        {"name": "Dallas Mavericks at San Antonio Spurs", "teams": {"home": "SA", "away": "DAL"}},
    ],
    "players": [
        player("Joel Embiid", "PHI", 26.0),
        player("Cade Cunningham", "DET", 24.0),
        player("LaMelo Ball", "CHA", 22.0),
        player("Shai Gilgeous-Alexander", "OKC", 31.0),
        player("Victor Wembanyama", "SA", 25.0),
    ],
}


def out(name, price, unit="Points"):
    return {"name": name, "price": price, "unitType": unit, "isOpenForBetting": True}


def event(key, name, outcomes):
    return {
        "event": key,
        "name": name,
        "markets": [{"group": "Player Points Markets", "outcomes": outcomes}],
    }


EVENTS = [
    event(
        "1",
        "Philadelphia 76ers @ Detroit Pistons",
        [
            out("Joel Embiid To Score 10+ Points", 1.20),
            out("Cade Cunningham To Score 10+ Points", 1.01),
        ],
    ),
    event("2", "Charlotte Hornets @ Brooklyn Nets", [out("L. Ball To Score 10+ Points", 1.20)]),
    event(
        "3",
        "Dallas Mavericks @ San Antonio Spurs",
        [
            out("Victor Wembanyama To Score 10+ Points", 1.20),
            out("S. Gilgeous-Alexander To Score 10+ Points", 1.5),
        ],
    ),
]


def test_parses_lines_matches_initials_and_guards_team():
    legs, unmatched = L.legs_from(EVENTS, BOARD)
    labels = {g["label"]: g for g in legs}
    assert (
        labels["L. Ball To Score 10+ Points"]["player"] == "LaMelo Ball"
    )  # initial + surname, same game
    assert "S. Gilgeous-Alexander" in unmatched  # OKC is not in that game: never priced
    g = labels["Joel Embiid To Score 10+ Points"]
    assert g["line"] == 10 and g["stat"] == "points"
    assert g["fair"] == round(1 / g["chance"], 2) and g["ev"] == round(g["chance"] * 1.20 - 1, 4)


def test_value_needs_likely_and_above_fair_and_cross_multi_is_one_leg_per_game():
    legs, _ = L.legs_from(EVENTS, BOARD)
    ok, cross, same = L.build(legs, 0.75, 10.0, 0.03)
    names = {g["label"] for g in ok}
    assert "Cade Cunningham To Score 10+ Points" not in names  # $1.01 is below fair
    assert all(g["chance"] >= 0.75 and g["ev"] >= 0.03 for g in ok)
    assert len(cross) == 1 and cross[0]["legs"] == 3
    m = cross[0]
    assert m["returns"] == round(10 * 1.2**3, 2)  # $10 on three $1.20 legs
    assert len({p.split(" To ")[0] for p in m["picks"]}) == 3
    assert same == []  # no game has 3 value legs


def test_nothing_worth_taking_when_prices_are_short():
    short = [
        event(
            "1",
            "Philadelphia 76ers @ Detroit Pistons",
            [out("Joel Embiid To Score 10+ Points", 1.01)],
        )
    ]
    legs, _ = L.legs_from(short, BOARD)
    ok, cross, same = L.build(legs, 0.75, 10.0, 0.03)
    assert ok == [] and cross == [] and same == []


def test_settle_won_lost_void():
    legs = [
        {"player": "Joel Embiid", "stat": "points", "line": 20},
        {"player": "Cade Cunningham", "stat": "reboundsTotal", "line": 10},
        {"player": "LaMelo Ball", "stat": "points", "line": 10},
    ]
    rows = {
        "joel embiid": {"min": 30, "points": 24},
        "cade cunningham": {"min": 34, "points": 29, "reboundsTotal": 6},
    }
    res = [x["result"] for x in S.settle(legs, rows)]
    assert res == ["won", "lost", "void"]


def test_best_stack_is_the_most_likely_combination_that_pays_the_target():
    import itertools
    import math
    import random

    rnd = random.Random(7)
    for _ in range(30):
        groups = []
        for gi in range(5):
            legs = []
            for _li in range(4):
                c = rnd.uniform(0.3, 0.97)
                legs.append(
                    {
                        "chance": c,
                        "price": round(max(1.01, rnd.uniform(0.8, 1.2) / c), 2),
                        "game": str(gi),
                    }
                )
            groups.append(L.frontier(legs))
        target = rnd.choice([2.0, 3.0, 5.0])
        got = L.best_stack(groups, target)
        best = 0.0
        for k in range(3, 6):
            for gs in itertools.combinations(groups, k):
                for pick in itertools.product(*gs):
                    if math.prod(g["price"] for g in pick) >= target:
                        best = max(best, math.prod(g["chance"] for g in pick))
        if got is None:
            assert best == 0.0
            continue
        assert len({g["game"] for g in got}) == len(got) >= 3  # one leg per game
        assert math.prod(g["price"] for g in got) >= target - 1e-9
        assert (
            math.prod(g["chance"] for g in got) >= best - 1e-9
        )  # nothing likelier reaches the target


def test_frontier_drops_a_leg_that_pays_less_and_is_no_more_likely():
    a = {"chance": 0.9, "price": 1.2}
    b = {"chance": 0.85, "price": 1.15}  # pays less and is less likely: gone
    c = {"chance": 0.6, "price": 1.8}
    assert L.frontier([a, b, c]) == [c, a]


def test_stacks_reach_each_payout_with_three_games():
    legs = [
        {
            "event": e,
            "game": e,
            "player": f"{e}{i}",
            "label": f"{e}{i}",
            "team": "T",
            "chance": c,
            "price": p,
        }
        for e in "ABC"
        for i, (c, p) in enumerate([(0.9, 1.15), (0.7, 1.5), (0.62, 1.9)])
    ]
    cross, same = L.stacks(legs)
    assert [m["target"] for m in cross] == [2.0, 3.0, 5.0]  # 1.9 x 1.9 x 1.9 = 6.86: no $100
    for m in cross:
        assert m["legs"] == 3 and m["price"] >= m["target"]
    # $20 on $10: 0.9 x 0.9 x 0.7 at $1.15 x $1.15 x $1.5 = $1.98 falls just short; the likeliest
    # stack that pays is 0.9 x 0.9 x 0.62 ($2.51), ahead of 0.9 x 0.7 x 0.7 ($2.59)
    assert cross[0]["chance"] == round(0.9 * 0.9 * 0.62, 4)
    assert [m["target"] for m in same] == [
        2.0,
        3.0,
    ]  # one game: 3 players, at most $1.15 x $1.5 x $1.9


def test_by_game_shows_each_players_surest_line_that_still_pays():
    legs = [
        {"event": "1", "game": "G", "player": "A", "label": "A 5+", "chance": 0.97, "price": 1.03},
        {"event": "1", "game": "G", "player": "A", "label": "A 10+", "chance": 0.85, "price": 1.25},
        {"event": "1", "game": "G", "player": "A", "label": "A 15+", "chance": 0.6, "price": 1.8},
        {"event": "1", "game": "G", "player": "B", "label": "B 8+", "chance": 0.9, "price": 1.2},
    ]
    (game,) = L.by_game(legs)
    assert [g["label"] for g in game["legs"]] == ["B 8+", "A 10+"]  # A 5+ pays too little


@pytest.mark.parametrize(
    "label,unit,stat",
    [
        ("Joel Embiid To Get 8+ Rebounds", "Rebounds", "reboundsTotal"),
        ("Joel Embiid To Get 5+ Assists", "Assists", "assists"),
        ("Joel Embiid To Make 2+ Threes", "Threes", "threePointersMade"),
        ("Joel Embiid To Score 20+ Points", "Points", "points"),
    ],
)
def test_every_stat_is_priced_with_the_boards_names(label, unit, stat):
    ev = [event("1", "Philadelphia 76ers @ Detroit Pistons", [out(label, 1.5, unit)])]
    legs, unmatched = L.legs_from(ev, BOARD)
    assert unmatched == [] and [g["stat"] for g in legs] == [stat]


def test_sportsbet_lines_parse_with_unders_and_settle_both_ways():
    import json
    from pathlib import Path

    f = json.loads((Path(__file__).parent / "fixtures" / "sportsbet_nba_sample.json").read_text())
    ev = L.sportsbet_events(f["competition"], f["markets"])
    assert len(ev) == 1 and ev[0]["name"] == "Philadelphia 76ers @ Detroit Pistons"
    assert ev[0]["startsAt"] == "2026-11-05T00:10:00Z"
    outs = ev[0]["markets"][0]["outcomes"]
    assert not any("Pts" in o["name"] for o in outs)  # combined stats (Pts + Reb) left out
    ou = [
        o
        for o in outs
        if o["name"].startswith("Joel Embiid")
        and "Points" in o["name"]
        and ("Over" in o["name"] or "Under" in o["name"])
    ]
    assert {(o["k"], o["under"]) for o in ou} == {
        (20, False),
        (20, True),
    }  # Over/Under 19.5 -> the 20 line
    board = {
        "day": "20261104",
        "params": PARAMS,
        "games": [
            {
                "name": "Philadelphia 76ers at Detroit Pistons",
                "teams": {"home": "DET", "away": "PHI"},
            }
        ],
        "players": [player("Joel Embiid", "PHI", 24.0)],
    }
    legs, _ = L.legs_from(ev, board)
    over = next(g for g in legs if g["label"] == "Joel Embiid Over 19.5 Points")
    under = next(g for g in legs if g["label"] == "Joel Embiid Under 19.5 Points")
    assert abs(over["chance"] + under["chance"] - 1) < 1e-3 and under["under"] and not over["under"]
    rows = {"joel embiid": {"min": 30, "points": 19}}
    assert [x["result"] for x in S.settle([over, under], rows)] == [
        "lost",
        "won",
    ]  # 19 points: the under wins


def _leg(player_, line, under, price, model=0.5):
    return {
        "player": player_,
        "stat": "points",
        "line": line,
        "under": under,
        "price": price,
        "model": model,
    }


def test_devig_of_a_pair():
    m = L.feed_market([_leg("A", 20, False, 1.8), _leg("A", 20, True, 2.0)])
    assert m[("A", "points", 20, False)] == pytest.approx((1 / 1.8) / (1 / 1.8 + 0.5))
    assert sum(m.values()) == pytest.approx(1.0)


def test_ladder_uses_the_feeds_overround():
    legs = [_leg("A", 20, False, 1.9), _leg("A", 20, True, 1.9), _leg("A", 25, False, 4.0)]
    m = L.feed_market(legs)
    assert m[("A", "points", 25, False)] == pytest.approx(0.25 / (2 / 1.9))
    only = L.feed_market([_leg("B", 25, False, 4.0)])  # no pairs: the 1.07 default
    assert only[("B", "points", 25, False)] == pytest.approx(0.25 / 1.07)


def test_market_is_averaged_over_agencies():
    m = L.market_probs({"pb": [_leg("A", 25, False, 4.0)], "sb": [_leg("A", 25, False, 5.0)]})
    assert m[("A", "points", 25, False)] == pytest.approx((0.25 + 0.2) / 2 / 1.07)


def test_blend_math_and_no_market_fallback():
    assert L.blend(0.7, 0.7) == pytest.approx(0.7)
    assert L.blend(0.7, 0.4, w=1.0) == pytest.approx(0.7)
    assert L.blend(0.7, 0.4, w=0.0) == pytest.approx(0.4)
    assert 0.5 < L.blend(0.8, 0.5, w=0.5) < 0.8
    legs = [_leg("A", 25, False, 4.0, model=0.3), _leg("B", 10, False, 1.5, model=0.8)]
    L.apply_market(legs, {("A", "points", 25, False): 0.2})
    assert legs[0]["market"] == 0.2 and legs[0]["model"] == 0.3 and legs[0]["chance"] < 0.3
    assert legs[1]["market"] is None and legs[1]["chance"] == 0.8
    assert legs[1]["ev"] == pytest.approx(0.8 * 1.5 - 1)


def _cleg(player, team, stat, chance, price=1.5, under=False):
    return {
        "event": "1",
        "game": "G",
        "player": player,
        "team": team,
        "stat": stat,
        "line": 10,
        "under": under,
        "label": f"{player} {stat}",
        "chance": chance,
        "price": price,
    }


def test_copula_with_no_correlation_is_the_product(monkeypatch):
    from melbcup import nba_legs as N

    monkeypatch.setattr(N, "CORR", {})
    legs = [
        _cleg("A", "X", "points", 0.7),
        _cleg("B", "X", "assists", 0.8),
        _cleg("C", "Y", "points", 0.6),
    ]
    assert N.joint_chance(legs) == pytest.approx(0.7 * 0.8 * 0.6)
    monkeypatch.setattr(
        N, "CORR", {("team", "pts", "ast"): 1e-9}
    )  # forces the draws: still the product
    assert N.joint_chance(legs) == pytest.approx(0.7 * 0.8 * 0.6, abs=0.03)


def test_correlation_moves_the_joint_chance_the_right_way(monkeypatch):
    from melbcup import nba_legs as N

    legs = [_cleg("A", "X", "points", 0.7), _cleg("A", "X", "reboundsTotal", 0.7)]
    monkeypatch.setattr(N, "CORR", {("self", "pts", "reb"): 0.6})
    assert N.joint_chance(legs) > 0.49 + 0.05
    over_under = [legs[0], _cleg("A", "X", "reboundsTotal", 0.7, under=True)]
    assert N.joint_chance(over_under) < 0.49  # an under moves against an over
    monkeypatch.setattr(N, "CORR", {("self", "pts", "reb"): -0.6})
    assert N.joint_chance(legs) < 0.49 - 0.05


def test_joint_chance_is_deterministic_and_a_single_leg_keeps_its_chance(monkeypatch):
    from melbcup import nba_legs as N

    monkeypatch.setattr(N, "CORR", {("team", "pts", "pts"): 0.3, ("opp", "pts", "pts"): 0.2})
    legs = [
        _cleg("A", "X", "points", 0.75),
        _cleg("B", "X", "points", 0.65),
        _cleg("C", "Y", "points", 0.7),
    ]
    first = N.joint_chance(legs)
    assert N.joint_chance(list(reversed(legs))) == first == N.joint_chance(legs)
    assert N.joint_chance(legs[:1]) == 0.75
    assert first > 0.75 * 0.65 * 0.7


def test_same_game_multi_chance_is_the_joint_chance(monkeypatch):
    from melbcup import nba_legs as N

    monkeypatch.setattr(N, "CORR", {("team", "pts", "pts"): 0.5})
    legs = [
        _cleg(p, "X", "points", c, 1.6) for p, c in (("A", 0.8), ("B", 0.75), ("C", 0.7), ("D", 0.7))
    ]
    (found,) = N.same_game_many(legs, [3.0])[3.0]
    independent = 1.0
    for g in found["detail"]:
        independent *= g["chance"]
    assert found["chance"] > independent + 0.02
    assert found["chance"] == round(
        N.joint_chance([g for g in legs if g["label"] in found["picks"]]), 4
    )


def test_market_only_books_sharpen_the_chance_but_get_no_tab():
    board = {"day": "20261106", "params": {}, "games": [], "players": []}
    ev = lambda price, k: [{"event": "1", "name": "A @ B", "startsAt": "2026-11-06T02:00:00Z", "markets": [{"group": "g", "outcomes": [  # noqa: E731
        {"name": f"P Over {k}", "player": "P", "stat": "points", "k": 20, "under": False, "price": price},
        {"name": f"P Under {k}", "player": "P", "stat": "points", "k": 20, "under": True, "price": 1.9}]}]}]
    plain = L.view(board, {"pb": ev(1.9, 19.5)})
    sharp = L.view(board, {"pb": ev(1.9, 19.5)}, market_only={"dk": ev(1.5, 19.5)})
    assert list(sharp["agencies"]) == ["pb"]  # a US book is no bettable tab
    over = lambda v: next(g for g in v["agencies"]["pb"]["report"]["all_legs"] if not g["under"])  # noqa: E731
    assert over(plain)["chance"] == pytest.approx(0.5, abs=0.01) and over(sharp)["chance"] > 0.52  # averaged with the US book


def test_overs_are_shaded_down_and_unders_up_most_at_even_money():
    assert L.shade(0.5, False) == pytest.approx(0.5 - L.OVER_SHADE, abs=0.001)
    assert L.shade(0.5, True) == pytest.approx(0.5 + L.OVER_SHADE, abs=0.001)
    assert 0 < 0.9 - L.shade(0.9, False) < 0.006  # a short leg barely moves
    legs = [_leg("A", 20, False, 1.9, model=0.5), _leg("A", 20, True, 1.9, model=0.5)]
    L.apply_market(legs, {("A", "points", 20, False): 0.5, ("A", "points", 20, True): 0.5})
    assert legs[0]["chance"] < 0.5 < legs[1]["chance"] and legs[0]["raw"] == 0.5
