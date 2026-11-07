"""Cleaning and model code for tools/sports/nba."""

import sys

import numpy as np

sys.path.insert(0, "tools/sports/nba")
for _m in ("build", "model", "test", "common", "fetch"):
    sys.modules.pop(_m, None)  # another sport's tools load modules with these names
import build  # noqa: E402
import model as M  # noqa: E402


def row(date, rot, vh, team, final, op, cl, ml):
    cells = [date, rot, vh, team, 0, 0, 0, 0, final, op, cl, ml, 0]
    return "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"


def test_parse_page_pairs_rows_and_finds_spread_and_total():
    page = (
        row(1019, 501, "V", "Brooklyn", 104, 240.5, 233.5, 105)
        + row(1019, 502, "H", "Milwaukee", 127, "pk", 1.5, -125)
        + row(103, 503, "V", "Utah", 90, 4, 3.5, 140)
        + row(103, 504, "H", "Boston", 95, 210, 208.5, -160)
    )
    g = build.parse_page(page, "2021-22")
    assert len(g) == 2
    a, b = g
    assert a["date"] == "2021-10-19" and a["total_close"] == 233.5 and a["total_open"] == 240.5
    assert a["spread_home_close"] == -1.5  # home Milwaukee favoured
    assert b["date"] == "2022-01-03" and b["spread_home_close"] == 3.5  # away Utah favoured


def test_devig_and_prices():
    assert abs(M.devig(-110, -110) - 0.5) < 1e-9
    assert abs(M.devig(-200, 170) + M.devig(170, -200) - 1) < 1e-9
    assert abs(M.decimal_from_american(100) - 2.0) < 1e-9
    assert abs(M.decimal_from_american(-200) - 1.5) < 1e-9


def test_wilson_range_contains_rate_and_shrinks():
    lo, hi = M.wilson(50, 100)
    lo2, hi2 = M.wilson(500, 1000)
    assert lo < 0.5 < hi and (hi2 - lo2) < (hi - lo)


def test_fit_logit_recovers_slope():
    rng = np.random.default_rng(1)
    x = rng.normal(size=5000)
    y = (rng.random(5000) < M.sigmoid(0.3 + 1.5 * x)).astype(float)
    w = M.fit_logit(x[:, None], y)
    assert abs(w[0] - 0.3) < 0.15 and abs(w[1] - 1.5) < 0.2


def test_elo_prefers_winner_and_regresses_between_seasons():
    e = Elo = M.Elo()
    e.new_season("a")
    for _ in range(10):
        e.update("X", "Y", 110, 90)
    assert e.diff("X", "Y") > 100
    before = e.r["X"]
    e.new_season("b")
    assert abs(e.r["X"] - 1500) < abs(before - 1500) and Elo is e
