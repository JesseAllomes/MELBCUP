"""Cleaning and model code for tools/sports/nhl."""

import importlib.util
import os
import sys

import numpy as np

D = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools/sports/nhl")


def _load(name):
    sys.path.insert(0, D)  # test.py imports `model` by that name
    spec = importlib.util.spec_from_file_location(f"nhl_{name}", os.path.join(D, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


build, M = _load("build"), _load("model")


def tr(cells):
    return "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"


def old(date, vh, team, final, op, cl, ou_o, ou_c, ou_odds_o, ou_odds_c):
    return tr([date, 1, vh, team, 0, 0, 0, final, op, cl, ou_o, ou_odds_o, ou_c, ou_odds_c])


def new(date, vh, team, final, op, cl, pl, pl_odds, ou_o, ou_c, odds_o, odds_c):
    return tr([date, 1, vh, team, 0, 0, 0, final, op, cl, pl, pl_odds, ou_o, odds_o, ou_c, odds_c])


def test_parse_old_format_no_puck_line():
    page = (old(1006, "V", "Philadelphia", 2, 120, 110, 5.5, 5.5, -105, 110)
            + old(1006, "H", "Boston", 1, -140, -130, 5.5, 5.5, -115, -130))
    (g,) = build.parse_page(page, "2011-12")
    assert (g["away"], g["home"], g["date"]) == ("PHI", "BOS", "2011-10-06")
    assert g["ml_away"] == 110 and g["ml_home"] == -130 and g["pl_home"] == ""
    assert g["total"] == 5.5 and g["over_odds"] == 110 and g["under_odds"] == -130


def test_parse_new_format_puck_line_and_prices():
    page = (new(1012, "V", "Pittsburgh", 6, 120, 220, 1.5, -120, 6, 5.5, -120, -130)
            + new(1012, "H", "TampaBay", 2, -140, -250, -1.5, 100, 6, 5.5, 100, 110))
    (g,) = build.parse_page(page, "2021-22")
    assert g["pl_home"] == -1.5 and g["pl_home_odds"] == 100 and g["pl_away_odds"] == -120
    assert g["total_open"] == 6 and g["total"] == 5.5
    assert g["over_odds"] == -130 and g["under_odds"] == 110


def test_date_rules_and_team_names():
    assert build.iso("2007-08", 929) == "2007-09-29"
    assert build.iso("2007-08", 604) == "2008-06-04"
    assert build.iso("2019-20", 920) == "2020-09-20"  # bubble final
    assert build.iso("2020-21", 113) == "2021-01-13"
    assert build.team("St.Louis") == "STL" and build.team("Phoenix") == build.team("Arizona")
    assert build.team("SeattleKraken") == "SEA" and build.team("Nowhere") is None
    assert build.canon("ATL") == "WPG"


def test_unparseable_rows_are_dropped():
    page = (old(1006, "V", "Boston", "x", 1, 1, 5, 5, 1, 1)
            + old(1006, "H", "Dallas", 1, 1, 1, 5, 5, 1, 1))
    assert build.parse_page(page, "2011-12") == []


def test_devig_and_overround():
    assert abs(M.devig(-110, -110) - 0.5) < 1e-12
    assert abs(M.devig(150, -180) + M.devig(-180, 150) - 1) < 1e-12
    assert 1.04 < M.overround(-110, -110) < 1.05
    assert M.valid_pair(-110, -110) and not M.valid_pair(-110, None)
    assert not M.valid_pair(120, 120)  # margin below zero: a typing error
    assert not M.valid_pair(-500, -500)


def test_wilson_and_decimal():
    lo, hi = M.wilson(50, 100)
    assert lo < 0.5 < hi and hi - lo < 0.21
    assert M.wilson(0, 0) == (0.0, 1.0)
    assert M.decimal_from_american(-200) == 1.5 and M.decimal_from_american(150) == 2.5


def test_logistic_recovers_calibration():
    rng = np.random.default_rng(1)
    z = rng.normal(0, 1, 20000)
    y = (rng.random(20000) < M.sigmoid(0.2 + 1.3 * z)).astype(float)
    a, w = M.fit_logistic(z[:, None], y)
    assert abs(a - 0.2) < 0.06 and abs(w[0] - 1.3) < 0.08


def g(date, home, away, hg, ag, season="2021-22", **kw):
    base = {"season": season, "date": date, "home": home, "away": away, "home_g": hg, "away_g": ag,
            "ml_home": -120.0, "ml_away": 100.0, "pl_home": None, "pl_home_odds": None,
            "pl_away_odds": None, "total": 6.0, "over_odds": -110.0, "under_odds": -110.0}
    base.update(kw)
    return base


def test_state_is_causal_and_updates_elo():
    st = M.State(k=10)
    f0 = st.features(g("2021-10-12", "BOS", "TOR", 3, 1))
    assert f0["elo"] == 0.0 and f0["b2b"] == 0.0
    st.update(g("2021-10-12", "BOS", "TOR", 3, 1))
    assert st.elo["BOS"] > 1500 > st.elo["TOR"]
    f1 = st.features(g("2021-10-13", "BOS", "MTL", 0, 0))
    assert f1["elo"] > 0 and f1["b2b"] == 1.0  # BOS played the day before, MTL did not


def test_market_rows_drop_pushes_and_bad_prices():
    games = [
        g("2021-10-12", "BOS", "TOR", 4, 2),  # total 6 = push: no total row
        g("2021-10-13", "BOS", "MTL", 4, 3, pl_home=-1.5, pl_home_odds=150.0,
              pl_away_odds=-180.0),
        g("2021-10-14", "BOS", "OTT", 2, 1, ml_home=120.0, ml_away=120.0),  # bad pair
    ]
    recs, _ = M.market_rows(games)
    assert [r["y"] for r in recs["tot"]] == [1.0, 0.0]  # push (6 = line) dropped
    assert len(recs["ml"]) == 2 and recs["ml"][0]["y"] == 1.0
    assert len(recs["pl"]) == 1 and recs["pl"][0]["y"] == 0.0  # won by 1, -1.5 not covered


def test_variant_prediction_market_is_identity_and_calibrated_fits():
    rec = [{"p": p, "elo": 0.0, "b2b": 0.0, "b2b_sum": 0.0, "dproj": 0.0}
           for p in (0.3, 0.5, 0.7)]
    assert list(M.predict_variant(None, rec, "ml", "market")) == [0.3, 0.5, 0.7]
    X = M.design(rec, "ml", "elo_rest")
    assert X.shape == (3, 3)
    assert M.design(rec, "tot", "elo_rest").shape == (3, 3)
