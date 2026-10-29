"""Parity of point estimates: research/evaluator.py (standalone) against research/analysis/evaluate.py (v1)
on random synthetic races with scratchings, dead heats, no-bet races and nominations. Intervals are not
compared: the two use different bootstrap populations and generators by design (EVALUATOR_COMPARISON.md).
Run from the repository root: MELBCUP_DATA=x MELBCUP_RESULTS=<tmp> python3 tests/test_evaluator_parity_synthetic.py"""
import math, os, random, sys
import numpy as np
import pandas as pd
sys.path[:0] = [os.path.join(os.path.dirname(__file__), "..", "research", "analysis"), os.path.join(os.path.dirname(__file__), "..")]
import evaluate as V1
from research import evaluator as SA


def scenario(seed, races=400, alpha=1.13):
    rng = random.Random(seed)
    rows = []
    for k in range(races):
        n = rng.randint(5, 14)
        m = np.array([rng.gammavariate(1.2, 1) for _ in range(n)]); m /= m.sum()
        model = m * np.exp(np.array([rng.gauss(0, 0.6) for _ in range(n)])); model /= model.sum()
        ma = m ** alpha; ma /= ma.sum()
        price = np.round(1 / (m * rng.uniform(1.0, 1.25)), 2)
        starter = [rng.random() > 0.02 for _ in range(n)]
        live = [i for i in range(n) if starter[i]]
        w = rng.choices(live, weights=m[live])[0]
        won = [i == w for i in range(n)]
        if rng.random() < 0.03:            # dead heat with another starter
            other = rng.choice([i for i in live if i != w] or [w])
            won[other] = True
        day = f"2024-{1 + k % 12:02d}-{1 + k % 28:02d}"
        for i in range(n):
            rows.append(dict(race_id=f"r{k:04d}", runner_id=f"{i:02d}", day=day, block="train", model=model[i], m=m[i], ma=ma[i],
                             price=price[i], starter=starter[i], won=won[i] and starter[i], barrier=i + 1))
    return pd.DataFrame(rows)


def v1(df):
    nw = df.groupby("race_id")["won"].transform("sum")
    status = np.where(nw >= 2, "dead_heat", np.where((~df["starter"]).groupby(df["race_id"]).transform("any"), "late_scratching", "ok"))
    fav = df["m"] >= df.groupby("race_id")["m"].transform("max") - 1e-9
    d = pd.DataFrame(dict(race_id=df["race_id"], mel_date=df["day"], starter=df["starter"], won=df["won"], M_t30=df["m"], fav_M_t30=fav,
                          sb_t30=df["price"], lb_t30=df["price"], barrier=df["barrier"], scoring_status_t30=status))
    return V1.claims(d, df["model"].to_numpy(), df["ma"].to_numpy(), df["m"].to_numpy(), 0.95)


def sa(df):
    preds = [dict(race_id=r.race_id, runner_id=r.runner_id, day=r.day, block="train", model_prob=r.model, market_prob=r.m,
                  corrected_prob=r.ma, win_price=r.price, bookmaker="sb") for r in df.itertuples()]
    outs = [dict(race_id=r.race_id, runner_id=r.runner_id, starter=str(r.starter), won=str(r.won)) for r in df.itertuples()]
    return SA.evaluate(preds, outs, SA.Rules(resamples=200))


def main():
    for seed in range(5):
        df = scenario(seed)
        a, b = v1(df), sa(df)
        checks = {
            "A gain": (a["A"]["mean_ll_gain"], b["claims"]["A"]["estimate"]),
            "A races": (a["A"]["races"], b["counts"]["probability_scored_races"]),
            "logloss model": (a["A"]["logloss_P"], b["metrics"]["model"]["logloss"]),
            "brier corrected": (a["A"]["brier_Malpha"], b["metrics"]["corrected_market"]["brier"]),
            "brier raw": (a["A"]["brier_raw"], b["metrics"]["raw_market"]["brier"]),
            "Malpha vs raw ll": (a["A"]["malpha_gain_over_raw"], b["comparisons"]["corrected_vs_raw_logloss"]["estimate"]),
            "Malpha vs raw brier": (a["A"]["malpha_brier_gain_over_raw"], b["comparisons"]["corrected_vs_raw_brier"]["estimate"]),
            "B bets": (a["B"]["bets"], b["counts"]["settled_bets"]),
            "B roi": (a["B"]["roi"], b["claims"]["B"]["estimate"]),
            "B excluded": (a["B"]["excluded_late_scratch_bets"], b["counts"]["excluded_late_scratch_bets"]),
            "C nominations": (a["C"]["nominations"], b["counts"]["scored_nominations"]),
            "C diff": (a["C"]["mean_diff"], b["claims"]["C"]["estimate"]),
        }
        for name, (x, y) in checks.items():
            same = (x is None or (isinstance(x, float) and math.isnan(x))) and y is None or math.isclose(float(x), float(y), rel_tol=1e-9, abs_tol=1e-12)
            assert same, (seed, name, x, y)
        print(f"seed {seed}: {len(checks)} point estimates agree "
              f"(A races {checks['A races'][0]}, bets {checks['B bets'][0]}, nominations {checks['C nominations'][0]})")


if __name__ == "__main__":
    main()
