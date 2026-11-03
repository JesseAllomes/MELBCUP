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

PARAMS = {s: {"phi": 1.2, "ca": 1.0, "cb": 0.0} for s in ("points", "rebounds", "assists", "threes")}


def player(name, team, pts):
    return {"name": name, "team": team, "minutes": 32.0, "mu": {"points": pts, "rebounds": 6.0, "assists": 4.0, "threes": 2.0}}


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
    return {"event": key, "name": name, "markets": [{"group": "Player Points Markets", "outcomes": outcomes}]}


EVENTS = [
    event("1", "Philadelphia 76ers @ Detroit Pistons", [out("Joel Embiid To Score 10+ Points", 1.20), out("Cade Cunningham To Score 10+ Points", 1.01)]),
    event("2", "Charlotte Hornets @ Brooklyn Nets", [out("L. Ball To Score 10+ Points", 1.20)]),
    event("3", "Dallas Mavericks @ San Antonio Spurs", [out("Victor Wembanyama To Score 10+ Points", 1.20), out("S. Gilgeous-Alexander To Score 10+ Points", 1.5)]),
]


def test_parses_lines_matches_initials_and_guards_team():
    legs, unmatched = L.legs_from(EVENTS, BOARD)
    labels = {g["label"]: g for g in legs}
    assert labels["L. Ball To Score 10+ Points"]["player"] == "LaMelo Ball"  # initial + surname, same game
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
    assert m["returns"] == round(10 * 1.2 ** 3, 2)  # $10 on three $1.20 legs
    assert len({p.split(" To ")[0] for p in m["picks"]}) == 3
    assert same == []  # no game has 3 value legs


def test_nothing_worth_taking_when_prices_are_short():
    short = [event("1", "Philadelphia 76ers @ Detroit Pistons", [out("Joel Embiid To Score 10+ Points", 1.01)])]
    legs, _ = L.legs_from(short, BOARD)
    ok, cross, same = L.build(legs, 0.75, 10.0, 0.03)
    assert ok == [] and cross == [] and same == []


def test_settle_won_lost_void():
    legs = [
        {"player": "Joel Embiid", "stat": "points", "line": 20},
        {"player": "Cade Cunningham", "stat": "points", "line": 30},
        {"player": "LaMelo Ball", "stat": "points", "line": 10},
    ]
    rows = {
        "joel embiid": {"min": 30, "points": 24},
        "cade cunningham": {"min": 34, "points": 29},
    }
    res = [x["result"] for x in S.settle(legs, rows)]
    assert res == ["won", "lost", "void"]
