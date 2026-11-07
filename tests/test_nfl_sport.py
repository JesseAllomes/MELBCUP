import math

import numpy as np
import pandas as pd

from tools.sports.nfl import build, model
from tools.sports.nfl import test as nfl_eval


def test_american_to_decimal():
    assert build.american_to_decimal(-110) == 1 + 100 / 110
    assert build.american_to_decimal(150) == 2.5
    assert math.isnan(build.american_to_decimal(float("nan")))


def test_devig_sums_to_one_and_keeps_order():
    a, b = build.devig(1.5, 2.8)
    assert abs(a + b - 1) < 1e-12 and a > b
    assert math.isnan(build.devig(float("nan"), 2.0)[0])


def _raw(tmp_path):
    cols = ("game_id,season,game_type,week,gameday,away_team,away_score,home_team,home_score,"
            "location,result,total,away_rest,home_rest,away_moneyline,home_moneyline,spread_line,"
            "away_spread_odds,home_spread_odds,total_line,under_odds,over_odds")
    rows = [
        "g1,2024,REG,1,2024-09-05,AAA,17,BBB,24,Home,7,41,7,7,150,-170,-3.5,-110,-110,44.5,-110,-110",
        "g2,2024,REG,1,2024-09-06,CCC,20,DDD,20,Home,0,40,7,7,100,-120,0,-110,-110,40,-110,-110",
        "g3,2026,REG,9,2026-11-08,EEE,,FFF,,Home,,,7,7,200,-250,-6,-110,-110,45,-110,-110",
    ]
    (tmp_path / "games.csv").write_text(cols + "\n" + "\n".join(rows) + "\n")
    return tmp_path


def test_build_outcomes_and_pushes(tmp_path):
    d = build.build(_raw(tmp_path)).set_index("game_id")
    assert d.loc["g1", "home_win"] == 1 and d.loc["g1", "home_cover"] == 1
    assert d.loc["g1", "over"] == 0  # 41 < 44.5
    assert d.loc["g2", "home_win"] == 0.5  # tie
    assert math.isnan(d.loc["g2", "home_cover"]) and math.isnan(d.loc["g2", "over"])  # pushes
    assert not d.loc["g3", "played"] and math.isnan(d.loc["g3", "home_win"])
    assert abs(d.loc["g1", "p_home"] + d.loc["g1", "p_away"] - 1) < 1e-12


def test_elo_is_pre_game_no_lookahead():
    d = build.build.__globals__["pd"].DataFrame(
        dict(game_id=["a", "b"], season=[2020, 2020], date=["2020-09-01", "2020-09-08"],
             home=["X", "X"], away=["Y", "Y"], neutral=[0, 0], played=[True, True],
             home_score=[30.0, 10.0], away_score=[10.0, 30.0]))
    out = model.add_elo(d)
    assert out.elo_diff[0] == model.ELO_HFA  # equal ratings before game 1
    assert out.elo_diff[1] > model.ELO_HFA  # X won game 1 so is stronger before game 2


def test_fit_logit_recovers_slope():
    rng = np.random.default_rng(0)
    x = rng.normal(size=20000)
    y = (rng.random(20000) < model.sigmoid(0.3 + 0.8 * x)).astype(float)
    w = model.fit_logit(np.column_stack([np.ones_like(x), x]), y)
    assert abs(w[0] - 0.3) < 0.08 and abs(w[1] - 0.8) < 0.08


def test_usable_drops_ml_ties_and_missing():
    d = pd.DataFrame(dict(p_home=[0.6, 0.5, np.nan], home_win=[1.0, 0.5, 1.0], spread=[-3, -3, -3]))
    assert len(model.usable(d, "ml")) == 1


def test_wilson_and_logloss():
    lo, hi = nfl_eval.wilson(50, 100)
    assert lo < 0.5 < hi and 0.4 < lo and hi < 0.6
    assert abs(model.logloss(np.array([0.5]), np.array([1.0]))[0] - math.log(2)) < 1e-9


def test_market_variant_predicts_market():
    d = pd.DataFrame(dict(p_home=[0.7, 0.4]))
    f = model.Fitted("ml", "mkt", None)
    assert list(f.predict(d)) == [0.7, 0.4]
