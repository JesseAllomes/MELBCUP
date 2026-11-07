"""Hold-out evaluation. Dev = walk-forward 2016-2024 (fit on prior seasons >= 2006);
sealed hold-out = 2025 (fit on <= 2024, evaluated once); 2026 (partial) = forward check.

Usage: python3 -m tools.sports.nfl.test [--data dataset.csv.gz] [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from tools.sports.nfl import model as M
from tools.sports.nfl.build import OUT_DEFAULT

DEV_SEASONS = range(2016, 2025)
HOLDOUT, FORWARD = 2025, 2026
FIRST_MARKET_SEASON = 2006
NBOOT = 2000
BANDS = [0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 1.0]
ROI_VARIANT = {"ml": "platt+elo+rest", "spread": "platt+elo_resid", "total": "platt+tline"}
SIDES = {  # market -> (side name, prob col transform, decimal col, outcome fn)
    "ml": [("home", "dec_home", False), ("away", "dec_away", True)],
    "spread": [("home", "dec_spread_home", False), ("away", "dec_spread_away", True)],
    "total": [("over", "dec_over", False), ("under", "dec_under", True)],
}


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (c - h, c + h)


def boot_mean(x, seed=7, conf=0.95):
    x = np.asarray(x, float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(x), (NBOOT, len(x)))
    m = x[idx].mean(1)
    a = (1 - conf) / 2
    return float(x.mean()), float(np.quantile(m, a)), float(np.quantile(m, 1 - a))


def load(path):
    d = pd.read_csv(path)
    d = d[d.game_type.notna()]
    return M.add_elo(d)


def walk_forward(d, market, variant, seasons):
    parts = []
    for s in seasons:
        tr = d[(d.season >= FIRST_MARKET_SEASON) & (d.season < s)]
        te = M.usable(d[d.season == s], market)
        f = M.fit(tr, market, variant)
        yv = te[M.MARKETS[market]["y"]].values
        parts.append(pd.DataFrame({"season": s, "p": f.predict(te), "y": yv, "idx": te.index}))
    return pd.concat(parts)


def compare(d, market, seasons, fit_through=None):
    """Log-loss of each variant vs raw market over `seasons`; paired bootstrap on the diff."""
    out = {}
    base = None
    for v in M.VARIANTS[market]:
        if fit_through is None:
            r = walk_forward(d, market, v, seasons)
        else:
            tr = d[(d.season >= FIRST_MARKET_SEASON) & (d.season <= fit_through)]
            te = M.usable(d[d.season.isin(list(seasons))], market)
            f = M.fit(tr, market, v)
            r = pd.DataFrame({"p": f.predict(te), "y": te[M.MARKETS[market]["y"]].values,
                              "idx": te.index})
        ll = M.logloss(r.p.values, r.y.values)
        if v == "mkt":
            base = ll
        diff = ll - base
        m, lo, hi = boot_mean(diff) if v != "mkt" else (0.0, 0.0, 0.0)
        m99, lo99, hi99 = (boot_mean(diff, conf=1 - 0.05 / 12)) if v != "mkt" else (0, 0, 0)
        out[v] = dict(n=int(len(ll)), logloss=float(ll.mean()), diff=m, ci95=[lo, hi],
                      ci_bonf12=[lo99, hi99], beats_market=bool(v != "mkt" and hi < 0))
    return out


def calibration(d, market, seasons):
    t = M.usable(d[d.season.isin(list(seasons))], market)
    y = t[M.MARKETS[market]["y"]]
    rows = []
    for side, _dec, flip in SIDES[market]:
        p = t[M.MARKETS[market]["p"]]
        ps = 1 - p if flip else p
        ys = (1 - y) if flip else y
        keep = y.notna() & ~(y == 0.5)
        for lo, hi in zip(BANDS[:-1], BANDS[1:], strict=True):
            m = keep & (ps >= lo) & (ps < hi)
            n = int(m.sum())
            if n == 0:
                continue
            k = float(ys[m].sum())
            wl, wh = wilson(k, n)
            rows.append(dict(market=market, side=side, band=f"{lo:.1f}-{hi:.1f}", n=n,
                             said=float(ps[m].mean()), got=k / n, lo=wl, hi=wh,
                             outside=bool(not (wl <= ps[m].mean() <= wh))))
    return rows


def roi_rows(d, market, seasons, probs=None, thr=0.0):
    """Flat 1u at the listed (single source) price. probs None = bet every game (blind)."""
    t = M.usable(d[d.season.isin(list(seasons))], market)
    y = t[M.MARKETS[market]["y"]]
    res = []
    for _side, dec, flip in SIDES[market]:
        ps = (1 - t[M.MARKETS[market]["p"]]) if flip else t[M.MARKETS[market]["p"]]
        if probs is not None:
            pm = probs.reindex(t.index)
            ps = 1 - pm if flip else pm
        edge = ps * t[dec] - 1
        m = (edge > thr) if probs is not None else pd.Series(True, index=t.index)
        win = (1 - y) if flip else y
        pnl = np.where(win == 0.5, 0.0, np.where(win == 1, t[dec] - 1, -1.0))
        res.append(pd.Series(pnl[m.values], index=t.index[m]))
    return pd.concat(res) if res else pd.Series(dtype=float)


def roi_summary(pnl):
    if len(pnl) < 5:
        return dict(bets=int(len(pnl)), roi=None, ci95=None)
    m, lo, hi = boot_mean(pnl.values)
    return dict(bets=int(len(pnl)), roi=m, ci95=[lo, hi])


def run(data, out_dir):
    d = load(data)
    res = dict(n_variants_tried=sum(len(v) - 1 for v in M.VARIANTS.values()),
               dev_seasons=[min(DEV_SEASONS), max(DEV_SEASONS)], holdout=HOLDOUT, forward=FORWARD,
               dev={}, holdout_res={}, forward_res={}, calibration={}, roi={})
    selected = {}
    for mk in M.MARKETS:
        res["dev"][mk] = compare(d, mk, DEV_SEASONS)
        sel = [v for v, r in res["dev"][mk].items() if r["beats_market"]]
        selected[mk] = min(sel, key=lambda v: res["dev"][mk][v]["logloss"]) if sel else "mkt"
        res["holdout_res"][mk] = compare(d, mk, [HOLDOUT], fit_through=2024)
        res["forward_res"][mk] = compare(d, mk, [FORWARD], fit_through=2025)
        res["calibration"][mk] = {
            "holdout_2025": calibration(d, mk, [HOLDOUT]),
            "pooled_2006_2025": calibration(d, mk, range(2006, 2026)),
        }
    res["selected"] = selected
    # ROI at the single listed price: blind bets (margin cost) and model-edge bets
    tr = d[(d.season >= FIRST_MARKET_SEASON) & (d.season <= 2024)]
    for mk in M.MARKETS:
        te_idx = M.usable(d[d.season == HOLDOUT], mk).index
        blind = roi_rows(d, mk, [HOLDOUT])
        pooled = roi_rows(d, mk, range(2006, 2026))
        f = M.fit(tr, mk, ROI_VARIANT[mk])
        pr = pd.Series(f.predict(d.loc[te_idx]), index=te_idx)
        res["roi"][mk] = dict(
            blind_all_sides_holdout=roi_summary(blind),
            blind_all_sides_pooled_2006_2025=roi_summary(pooled),
            model_edge_gt_0_holdout=roi_summary(roi_rows(d, mk, [HOLDOUT], pr, 0.0)),
            model_edge_gt_3pct_holdout=roi_summary(roi_rows(d, mk, [HOLDOUT], pr, 0.03)),
            model_edge_variant=f.variant,
        )
    mdl = {mk: M.fit(tr, mk, selected[mk]).to_json() for mk in M.MARKETS}
    mdl_all = {mk: M.fit(d[(d.season >= FIRST_MARKET_SEASON) & (d.season <= HOLDOUT)], mk,
                         selected[mk]).to_json() for mk in M.MARKETS}
    model = dict(
        description="Market-first: raw no-vig market unless a variant beat it on walk-forward dev "
                    "with 95% bootstrap range excluding zero. "
                    "fit_through_2024 is what the hold-out used; "
                    "refit_through_2025 is for future use.",
        selected=selected, fit_through_2024=mdl, refit_through_2025=mdl_all,
        elo=dict(k=M.ELO_K, hfa=M.ELO_HFA, revert=M.ELO_REVERT, pts_per_point=M.ELO_PTS),
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "holdout_results.json").write_text(json.dumps(res, indent=1))
    (out_dir / "model.json").write_text(json.dumps(model, indent=1))
    return res, model


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=OUT_DEFAULT / "dataset.csv.gz")
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    a = ap.parse_args()
    r, m = run(a.data, a.out)
    print(json.dumps(r["selected"]))
