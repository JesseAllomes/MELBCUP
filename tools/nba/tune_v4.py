# ruff: noqa: E501, E702
"""NBA props model v4 = v3 + rest, minutes and blowout levers, rolling validation (owner, 2026-11-04). Token-free.

Usage: python3 tools/nba/tune_v4.py BOXDIR [--folds 00221,00222,00223] [--check 00224] [--sample 4] [--out FILE]
Stage A rest:     team back-to-back (and starters on one), opponent back-to-back, player back from 7+ days off
Stage B minutes:  starters lose more minutes when regulars are missing, soft cap on projected minutes
Stage C blowout:  extra starter minutes cut once the expected margin passes 8 points (proxy: recent net rating gap)
Each stage is kept only if it lowers the mean log loss over the rolling folds AND the check season.
--out saves the parameters (merge stats into model_v4.json; the winning stages' parameters per stat; a stat where nothing helped keeps v3's).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
from scipy import optimize

sys.path.insert(0, os.path.dirname(__file__))
from tune import LINES, STATS, build, load, nb_tail  # noqa: E402

N3 = 9
START = [0.0, 0.0, 0.0, 0.0, 0.0, 48.0, 0.0]  # c_b2b, c_ob2b, c_long, c_b2b_star, c_ms, cap, c_blow2
STAGES = {"A": [9, 10, 11, 12], "B": [13, 14], "C": [15]}


def minutes_mu(R, idx, hm, th):
    """Projected minutes and the opponent-tiredness multiplier, from the 16-number parameter vector."""
    _w, c_miss, _a, _lp, _ca, _cb, g, c_blow, _cu, c_b2b, c_ob2b, c_long, c_b2b_star, c_ms, cap, c_blow2 = th
    base = R[f"m{hm}"][idx]
    starter = R["starter"][idx]
    role = np.where(starter > 0, R["m_start"][idx], R["m_bench"][idx])
    role = np.where(np.isnan(role), base, role)
    mins = (g * role + (1 - g) * base) * (1 + (c_miss + c_ms * starter) * R["miss"][idx])
    absm = np.minimum(np.abs(R["margin"][idx]), 25)
    mins = mins * (1 - c_blow * starter * absm / 10) * (1 - c_blow2 * starter * np.maximum(absm - 8, 0) / 10)
    mins = mins * (1 - (c_b2b + c_b2b_star * starter) * R["b2b"][idx]) * (1 - c_long * (R["prest"][idx] >= 7))
    mins = np.maximum(mins, 0)
    mins = mins / np.power(1 + np.power(mins / max(cap, 20.0), 6), 1 / 6)
    return mins, 1 + c_ob2b * R["opp_b2b"][idx]


def mean_mu(R, idx, s, hm, hr, th):
    """Projected minutes and expected count for rows idx."""
    w, _, a_opp, _lp, _ca, _cb, _, _, c_use = th[:9]
    n = R["n"][idx]
    mins, omult = minutes_mu(R, idx, hm, th)
    rate = (n * R[f"r_{s}_{hr}"][idx] + w * R[f"car_{s}"][idx]) / (n + w) * (1 + c_use * R[f"use_{s}"][idx])
    return mins, mins * rate * np.power(np.clip(R[f"opp_{s}"][idx], 0.5, 2.0), a_opp) * omult


def predict(R, idx, s, hm, hr, th):
    log_phi, ca, cb = th[3:6]
    _, mu = mean_mu(R, idx, s, hm, hr, th)
    out = {}
    for k in LINES[s]:
        p = np.clip(nb_tail(mu, np.exp(log_phi), k), 1e-5, 1 - 1e-5)
        out[k] = 1 / (1 + np.exp(-(ca * np.log(p / (1 - p)) + cb)))
    return out


def loss(R, idx, s, hm, hr, th):
    tot = 0.0; n = 0
    for k, p in predict(R, idx, s, hm, hr, th).items():
        y = R[f"y_{s}"][idx] >= k
        p = np.clip(p, 1e-5, 1 - 1e-5)
        tot += -np.sum(np.where(y, np.log(p), np.log(1 - p))); n += len(p)
    return tot / n


def fit(R, idx, s, hm, hr, th0, free):
    """Nelder-Mead over the parameters in `free`, the rest held at th0; half-lives are held at v3's."""
    th0 = np.array(th0, float); free = list(free)

    def f(x):
        th = th0.copy(); th[free] = x
        return loss(R, idx, s, hm, hr, th)
    r = optimize.minimize(f, th0[free], method="Nelder-Mead", options={"maxiter": 100 * len(free), "xatol": 1e-3, "fatol": 1e-7})
    th = th0.copy(); th[free] = r.x
    return th


def buckets(R, idx, s, hm, hr, th):
    pr = predict(R, idx, s, hm, hr, th)
    ps = np.concatenate(list(pr.values())); ys = np.concatenate([R[f"y_{s}"][idx] >= k for k in pr])
    return ps, ys


def calib(R, idx, s, hm, hr, th):
    ps, ys = buckets(R, idx, s, hm, hr, th)
    out = []
    for b in range(10):
        m = (ps >= b / 10) & (ps < (b + 1) / 10)
        if m.sum() >= 200:
            out.append(f"{b*10}-{b*10+9}%:{100*ys[m].mean():.1f}%")
    return " ".join(out)


def calib_err(R, idx, s, hm, hr, th):
    """Count-weighted mean absolute gap between said and happened over 10 probability buckets."""
    ps, ys = buckets(R, idx, s, hm, hr, th)
    tot = 0.0
    for b in range(10):
        m = (ps >= b / 10) & (ps < (b + 1) / 10)
        if m.sum():
            tot += m.sum() * abs(ps[m].mean() - ys[m].mean())
    return tot / len(ps)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("boxdir")
    ap.add_argument("--folds", default="00221,00222,00223")
    ap.add_argument("--check", default="00224")
    ap.add_argument("--sample", type=int, default=4)
    ap.add_argument("--stats", default=",".join(STATS))
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    games = [g for g in load(a.boxdir) if g[1] != "00225" or a.check == "00225"]
    R = build(games)
    season = R["season"]
    v3 = json.load(open(os.path.join(os.path.dirname(__file__), "model_v3.json")))
    out = {}
    print(f"games {len(games)}; folds {a.folds}; check {a.check}")
    for s in a.stats.split(","):
        hm, hr = v3[s]["hl_minutes"], v3[s]["hl_rate"]
        v3th = np.array(v3[s]["theta"] + START)
        keep = []
        results = {}
        best = None
        for label, stage in (("v3", ""), ("+A rest", "A"), ("+B minutes", "B"), ("+C blowout", "C")):
            trial = keep + ([stage] if stage else [])
            free = list(range(N3)) + [i for st in trial for i in STAGES[st]]
            fl = []
            for y in a.folds.split(","):
                tr = np.where(season < y)[0][:: a.sample]; te = np.where(season == y)[0]
                fl.append(loss(R, te, s, hm, hr, fit(R, tr, s, hm, hr, v3th, free)))
            tr = np.where(season < a.check)[0][:: a.sample]; te = np.where(season == a.check)[0]
            th = fit(R, tr, s, hm, hr, v3th, free)
            chk = loss(R, te, s, hm, hr, th); ce = calib_err(R, te, s, hm, hr, th)
            roll = float(np.mean(fl))
            results[label] = (roll, chk, ce)
            verdict = ""
            if stage:
                if roll < best[0] - 2e-5 and chk < best[1] - 2e-5:
                    keep = trial; verdict = "KEEP"; best = (roll, chk, th)
                else:
                    verdict = "drop"
            else:
                best = (roll, chk, th)
            print(f"{s:18} {label:12} rolling {roll:.4f}  check {chk:.4f}  calib-gap {ce:.4f}  {verdict}", flush=True)
        th = best[2]
        te = np.where(season == a.check)[0]
        print(f"  kept {keep or 'none'}  extras {[round(float(x), 3) for x in th[9:]]}\n  calibration on check: {calib(R, te, s, hm, hr, th)}", flush=True)
        out[s] = {"hl_minutes": hm, "hl_rate": hr, "theta": [round(float(x), 5) for x in th], "stages": keep,
                  "before": list(results["v3"]), "after": [best[0], best[1]]}
    if a.out:
        json.dump(out, open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
