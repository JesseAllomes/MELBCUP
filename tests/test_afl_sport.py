import numpy as np
import pandas as pd

from tools.sports.afl import model as M
from tools.sports.afl.build import clean
from tools.sports.afl.test import calib, roi, wilson


def _raw():
    return pd.DataFrame(
        {
            "Date": pd.to_datetime(["2024-03-14", "2024-03-14", "2024-03-15", "2024-03-21"]),
            "Home Team": ["A", "A", "B", "C"],
            "Away Team": ["B", "B", "C", "A"],
            "Venue": ["v"] * 4,
            "Home Score": [100, 100, 80, 90],
            "Away Score": [80, 80, 80, None],
            "Play Off Game?": [None, None, "Y", None],
            "Home Odds": [1.5, 1.5, 1.0, 2.0],
            "Away Odds": [2.8, 2.8, 3.0, 1.9],
            "Bookmakers Surveyed": [5] * 4,
            "Home Odds Open": [1.5] * 4,
            "Away Odds Open": [2.7] * 4,
            "Home Odds Close": [1.4] * 4,
            "Away Odds Close": [3.0] * 4,
            "Home Line Close": [-10.5] * 4,
            "Home Line Odds Close": [1.9] * 4,
            "Away Line Odds Close": [1.9] * 4,
            "Total Score Close": [170.5] * 4,
            "Total Score Over Close": [1.9] * 4,
            "Total Score Under Close": [1.9] * 4,
        }
    )


def test_clean_drops_dupes_unplayed_and_bad_odds():
    d = clean(_raw())
    assert len(d) == 2  # duplicate game and the unplayed (no score) row removed
    assert d.loc[d.home == "B", "h_avg"].isna().all()  # odds of 1.0 are invalid
    assert d.loc[d.home == "B", "home_win"].iloc[0] == 0.5  # draw
    assert d.loc[d.home == "B", "finals"].iloc[0] == 1
    assert d.loc[d.home == "A", "margin"].iloc[0] == 20


def test_devig_sums_to_one_and_power_shrinks_longshot():
    p = M.devig(1.5, 3.0)
    assert abs(p + M.devig(3.0, 1.5) - 1) < 1e-12
    assert M.devig(1.5, 3.0, 1.2) > p  # favourite gets more under k>1
    assert abs(M.overround(1.9, 1.9) - (2 / 1.9 - 1)) < 1e-12


def test_elo_is_pre_game_and_season_regresses():
    d = clean(_raw()).iloc[:1].copy()
    d = pd.concat([d, d.assign(date=pd.Timestamp("2025-03-14"), season=2025)], ignore_index=True)
    rh, ra, final = M.elo_run(d)
    assert rh[0] == 1500 and ra[0] == 1500  # nothing leaks from the game itself
    assert rh[1] > 1500 > ra[1]  # winner rated higher next game
    assert abs(rh[1] - 1500) < abs(final["A"] - 1500) + 100  # carry-over shrinks toward 1500


def test_fit_logit_recovers_slope():
    rng = np.random.default_rng(1)
    x = rng.normal(size=4000)
    y = (rng.random(4000) < M.expit(0.2 + 0.8 * x)).astype(float)
    w = M.fit_logit(x.reshape(-1, 1), y)
    assert abs(w[0] - 0.2) < 0.15 and abs(w[1] - 0.8) < 0.15


def test_rest_cap_and_fit_model_runs():
    d = clean(_raw())
    d = M.add_rest(M.add_elo(d))
    assert (d.rest_h <= 14).all()
    rng = np.random.default_rng(2)
    n = 300
    big = pd.DataFrame({"h_close": rng.uniform(1.3, 3, n)})
    big["a_close"] = 1 / (1.05 - 1 / big.h_close)
    big["home_win"] = (rng.random(n) < M.devig(big.h_close, big.a_close)).astype(float)
    big["elo_p"], big["rest_h"], big["rest_a"] = 0.5, 7, 7
    big["season"] = 2020
    m = M.fit_model(big)
    p = M.predict_h2h(m, big, "elo_rest")
    assert p.shape == (n,) and ((p > 0) & (p < 1)).all()
    assert 0.9 <= m["power_k"] <= 1.4


def test_wilson_roi_calib():
    lo, hi = wilson(50, 100)
    assert lo < 0.5 < hi and wilson(0, 0) == [None, None]
    r = roi([0.6, 0.6, 0.4], [2.0, 2.0, 2.0], [1, 0, 1], 0.0)
    assert r["bets"] == 2 and abs(r["roi"]) < 1e-12  # one win (+1), one loss (-1)
    c = calib(np.array([0.1, 0.9]), np.array([0, 1]), [0, 0.5, 1.0001])
    assert [x["n"] for x in c] == [1, 1]
