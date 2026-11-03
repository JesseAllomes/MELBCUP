# ruff: noqa: E501, E702
"""NBA props model v3 with rolling validation (owner, 2026-11-03). Token-free.

Usage: python3 tools/nba/tune_v3.py BOXDIR [--folds 00221,00222,00223] [--check 00224] [--sample 4]
Adds three levers to v2 (tools/nba/tune.py, whose features it reuses):
  role     minutes from the player's own starter or bench pattern, by today's role, blended (g)
  usage    rate x (1 + c_use x share of the team's stat that sits out with absent regulars)
  script   starters lose minutes as the expected margin grows (from recent team point margins)
Rolling validation: for each fold season Y, tune on every earlier season and score on Y; the
reported figure is the mean over folds, so one lucky season cannot pick the model. The check
season is scored once with parameters tuned on everything before it. 2025-26 stays sealed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
from scipy import optimize

sys.path.insert(0, os.path.dirname(__file__))
from tune import HLS, LINES, STATS, build, load, nb_tail  # noqa: E402


def predict(R, idx, s, hm, hr, th):
    w, c_miss, a_opp, log_phi, ca, cb, g, c_blow, c_use = th
    n = R["n"][idx]
    base = R[f"m{hm}"][idx]
    starter = R["starter"][idx]
    role = np.where(starter > 0, R["m_start"][idx], R["m_bench"][idx])
    role = np.where(np.isnan(role), base, role)
    mins = (g * role + (1 - g) * base) * (1 + c_miss * R["miss"][idx])
    mins = mins * (1 - c_blow * starter * np.minimum(np.abs(R["margin"][idx]), 25) / 10)
    rate = (n * R[f"r_{s}_{hr}"][idx] + w * R[f"car_{s}"][idx]) / (n + w)
    rate = rate * (1 + c_use * R[f"use_{s}"][idx])
    mu = np.maximum(mins, 0) * rate * np.power(np.clip(R[f"opp_{s}"][idx], 0.5, 2.0), a_opp)
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


def fit(R, idx, s, start=None):
    f = lambda th, hm, hr: loss(R, idx, s, hm, hr, th)  # noqa: E731
    nm = {"method": "Nelder-Mead", "options": {"maxiter": 500, "xatol": 1e-3, "fatol": 1e-6}}
    x0 = np.array(start if start is not None else [80.0, 0.45, 0.5, np.log(1.5), 0.9, -0.1, 0.5, 0.02, 0.3])
    th = optimize.minimize(f, x0, args=(3, 8), **nm).x
    hm = min(HLS, key=lambda h: f(th, h, 8))
    hr = min(HLS, key=lambda h: f(th, hm, h))
    r = optimize.minimize(f, th, args=(hm, hr), **nm)
    return hm, hr, r.x


def calib(R, idx, s, hm, hr, th):
    pr = predict(R, idx, s, hm, hr, th)
    ps = np.concatenate(list(pr.values())); ys = np.concatenate([R[f"y_{s}"][idx] >= k for k in pr])
    out = []
    for b in range(10):
        m = (ps >= b / 10) & (ps < (b + 1) / 10)
        if m.sum() >= 200:
            out.append(f"{b*10}-{b*10+9}%:{100*ys[m].mean():.1f}%")
    return " ".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("boxdir")
    ap.add_argument("--folds", default="00221,00222,00223")
    ap.add_argument("--check", default="00224")
    ap.add_argument("--sample", type=int, default=4)
    a = ap.parse_args()
    games = [g for g in load(a.boxdir) if g[1] != "00225" or a.check == "00225"]
    R = build(games)
    season = R["season"]
    v2 = json.load(open(os.path.join(os.path.dirname(__file__), "model_v2.json")))
    import tune as T  # the v2 predictor, for the side-by-side
    out = {}
    print(f"games {len(games)}; folds {a.folds}; check {a.check}")
    for s in STATS:
        fold_v2 = []; fold_v3 = []; last = None
        for y in a.folds.split(","):
            tr = np.where(season < y)[0][:: a.sample]; te = np.where(season == y)[0]
            hm, hr, th = fit(R, tr, s, last); last = th
            p2 = v2[s]; th2 = np.array(p2["theta"])
            fold_v2.append(T.loss(R, te, s, p2["hl_minutes"], p2["hl_rate"], th2))
            fold_v3.append(loss(R, te, s, hm, hr, th))
        tr = np.where(season < a.check)[0][:: a.sample]; te = np.where(season == a.check)[0]
        hm, hr, th = fit(R, tr, s, last)
        p2 = v2[s]; th2 = np.array(p2["theta"])
        c2 = T.loss(R, te, s, p2["hl_minutes"], p2["hl_rate"], th2); c3 = loss(R, te, s, hm, hr, th)
        out[s] = {"hl_minutes": hm, "hl_rate": hr, "theta": [round(float(x), 5) for x in th]}
        print(f"\n{s}: g {th[6]:.2f} c_blow {th[7]:.3f} c_use {th[8]:.2f} c_miss {th[1]:.2f} a_opp {th[2]:.2f} phi {np.exp(th[3]):.2f} hl {hm}/{hr}")
        print(f"  rolling folds  v2 {np.mean(fold_v2):.4f}  v3 {np.mean(fold_v3):.4f}  ({' '.join(f'{x:.4f}->{y:.4f}' for x, y in zip(fold_v2, fold_v3, strict=True))})")
        print(f"  check {a.check}  v2 {c2:.4f}  v3 {c3:.4f}")
        print(f"  calibration v3 on check: {calib(R, te, s, hm, hr, th)}")
    json.dump(out, open(os.path.join(os.path.dirname(__file__), "model_v3.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
