# ruff: noqa: E501
"""Hold-out evaluation. Prints the tables research/sports/nhl.md quotes and writes the JSON.

    python3 tools/sports/nhl/test.py [DATA_DIR] [OUT_DIR]

Fit on 2007-08..2019-20, choose Elo K and the stack variant on 2020-21 only, refit on <=2020-21
and score the sealed 2021-22 season once (and the part-season 2022-23 the archive holds as a
second look). Prices are one source's closing line (the archive's), not a best-of-books max.
Puck line exists from 2014-15 only. No free NHL prop prices exist, so there is no prop test.
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model as M  # noqa: E402

SCR = "/tmp/claude-0/-home-user/418442d0-6a93-5b3f-a291-37c2b3744726/scratchpad/sports/nhl"
RNG = np.random.default_rng(7)
VAL, HOLD, EXTRA = "2020-21", "2021-22", "2022-23"
KS = (4.0, 6.0, 10.0)
TRIED = {"elo_k": len(KS), "stack_variants": len(M.VARIANTS) * len(M.MARKETS), "bands": 0,
         "roi_rules": 0}


def boot_ci(d: np.ndarray, n: int = 2000) -> tuple[float, float, float]:
    """Mean and 95% range of a per-game difference (bootstrap)."""
    if len(d) == 0:
        return (0.0, 0.0, 0.0)
    idx = RNG.integers(0, len(d), (n, len(d)))
    means = d[idx].mean(1)
    return float(d.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def roi(dec: np.ndarray, win: np.ndarray) -> dict:
    TRIED["roi_rules"] += 1
    r = dec * win - 1.0
    m, lo, hi = boot_ci(r)
    return {"n": int(len(r)), "roi": round(m, 4), "lo": round(lo, 4), "hi": round(hi, 4)}


def calib(p, y, edges):
    rows = []
    for a, b in zip(edges[:-1], edges[1:], strict=True):
        k = (p >= a) & (p < b)
        n = int(k.sum())
        if n == 0:
            continue
        hits = int(y[k].sum())
        lo, hi = M.wilson(hits, n)
        rows.append({"band": f"{a:.2f}-{b:.2f}", "n": n, "said": round(float(p[k].mean()), 3),
                     "got": round(hits / n, 3), "lo": round(lo, 3), "hi": round(hi, 3),
                     "outside": bool(p[k].mean() < lo or p[k].mean() > hi)})
        TRIED["bands"] += 1
    return rows


def split(rec, seasons):
    return [r for r in rec if r["season"] in seasons]


def ys(rec):
    return np.array([r["y"] for r in rec])


def fit_variant(rec, market, variant):
    if variant == "market":
        return None
    X = M.design(rec, market, variant)
    a, w = M.fit_logistic(X, ys(rec))
    return {"a": a, "w": w}


def seasons_before(games, s):
    return sorted({g["season"] for g in games if g["season"] < s})


def ml_edges():
    return [0.0, 0.35, 0.45, 0.55, 0.65, 1.0]


def main(data=None, out=None) -> None:
    data = data or os.path.join(SCR, "data")
    out = out or data
    games = M.load_games(os.path.join(data, "games.csv.gz"))
    train_s = seasons_before(games, VAL)
    fit_s = train_s + [VAL]
    res = {"split": {"fit": f"{train_s[0]}..{train_s[-1]}", "validate": VAL, "holdout": HOLD,
                     "extra_partial": EXTRA}, "markets": {}, "tried": TRIED}

    # 1. choose Elo K on the validation season (ML, elo variant), training seasons only
    kloss = {}
    for k in KS:
        recs, _ = M.market_rows(games, k)
        tr, va = split(recs["ml"], train_s), split(recs["ml"], [VAL])
        prm = fit_variant(tr, "ml", "elo")
        kloss[k] = float(M.log_loss_each(M.predict_variant(prm, va, "ml", "elo"), ys(va)).mean())
    K = min(kloss, key=kloss.get)
    res["elo_k_val_logloss"] = {str(k): round(v, 5) for k, v in kloss.items()}
    res["elo_k"] = K
    recs, state = M.market_rows(games, K)

    model_json = {"elo_k": K, "variants_tried": list(M.VARIANTS), "markets": {},
                  "note": "market = proportional margin removal of the archive's closing prices"}
    for mk in M.MARKETS:
        rec = recs[mk]
        tr, va = split(rec, train_s), split(rec, [VAL])
        if len(tr) < 500:
            continue
        # 2. choose the variant on the validation season
        vloss = {}
        for v in M.VARIANTS:
            vloss[v] = float(M.log_loss_each(M.predict_variant(fit_variant(tr, mk, v), va, mk, v),
                                             ys(va)).mean())
        chosen = min(vloss, key=vloss.get)
        # 3. refit chosen variant on <=VAL, score sealed hold-out and the part-season
        fit = split(rec, fit_s)
        prm = fit_variant(fit, mk, chosen)
        block = {"validation_logloss": {k: round(v, 5) for k, v in vloss.items()},
                 "chosen": chosen, "params": prm, "n_fit": len(fit)}
        for name, seas in (("holdout", [HOLD]), ("extra", [EXTRA])):
            te = split(rec, seas)
            if not te:
                continue
            y = ys(te)
            pm = np.array([r["p"] for r in te])
            pmod = M.predict_variant(prm, te, mk, chosen)
            lm, lmod = M.log_loss_each(pm, y), M.log_loss_each(pmod, y)
            d = lm - lmod  # positive = model better
            mean, lo, hi = boot_ci(d)
            oa = np.array([r["o_a"] for r in te])
            ob = np.array([r["o_b"] for r in te])
            da, db = (np.array([M.decimal_from_american(o) for o in x]) for x in (oa, ob))
            side = {}
            # flat bets at the one source's closing price
            side["side_a_all"] = roi(da, y)  # home / home-covers / over
            side["side_b_all"] = roi(db, 1 - y)
            fav_a = pm >= 0.5
            side["favourites"] = roi(np.where(fav_a, da, db), np.where(fav_a, y, 1 - y))
            side["underdogs"] = roi(np.where(fav_a, db, da), np.where(fav_a, 1 - y, y))
            # model-chosen bets: back the side the model rates above the price by >= 3 points
            edge_a, edge_b = pmod * da - 1, (1 - pmod) * db - 1
            bet_a, bet_b = edge_a > 0.03, edge_b > 0.03
            r_model = np.r_[da[bet_a] * y[bet_a] - 1, db[bet_b] * (1 - y[bet_b]) - 1]
            m_, l_, h_ = boot_ci(r_model)
            TRIED["roi_rules"] += 1
            side["model_edge_3pct"] = {"n": int(len(r_model)), "roi": round(m_, 4),
                                       "lo": round(l_, 4), "hi": round(h_, 4)}
            block[name] = {
                "n": int(len(te)), "base_rate": round(float(y.mean()), 4),
                "logloss_market": round(float(lm.mean()), 5),
                "logloss_model": round(float(lmod.mean()), 5),
                "diff_market_minus_model": {"mean": round(mean, 5), "lo": round(lo, 5),
                                            "hi": round(hi, 5)},
                "model_beats_market_beyond_95": bool(lo > 0),
                "avg_overround": round(float(np.mean([M.overround(a, b) for a, b in zip(oa, ob, strict=True)])), 4),
                "calibration_market": calib(pm, y, ml_edges() if mk != "tot" else [0, 0.45, 0.48, 0.52, 0.55, 1.0]),
                "roi_single_source": side,
            }
        # every variant on the hold-out (reported, never used to choose): loss minus market loss
        te = split(rec, [HOLD])
        yh, pmh = ys(te), np.array([r["p"] for r in te])
        block["holdout_all_variants"] = {}
        for v in M.VARIANTS[1:]:
            pv = M.predict_variant(fit_variant(fit, mk, v), te, mk, v)
            m_, l_, h_ = boot_ci(M.log_loss_each(pmh, yh) - M.log_loss_each(pv, yh))
            block["holdout_all_variants"][v] = {"market_minus_variant": round(m_, 5),
                                                "lo": round(l_, 5), "hi": round(h_, 5)}
        # diagnostics on ALL seasons (not used to choose anything): calibration and ROI by band
        pa = np.array([r["p"] for r in rec])
        ya = ys(rec)
        da_all = np.array([M.decimal_from_american(r["o_a"]) for r in rec])
        db_all = np.array([M.decimal_from_american(r["o_b"]) for r in rec])
        edges = ml_edges() if mk != "tot" else [0, 0.45, 0.48, 0.52, 0.55, 1.0]
        block["calibrated_fit_ab"] = fit_variant(fit, mk, "calibrated")
        block["all_seasons"] = {"n": len(rec), "calibration_market": calib(pa, ya, edges),
                                "roi_by_band": []}
        for a_, b_ in zip(edges[:-1], edges[1:], strict=True):
            k = (pa >= a_) & (pa < b_)
            if k.sum() >= 100:
                block["all_seasons"]["roi_by_band"].append({
                    "band": f"{a_:.2f}-{b_:.2f}", "side_a": roi(da_all[k], ya[k]),
                    "side_b": roi(db_all[k], 1 - ya[k])})
        res["markets"][mk] = block
        model_json["markets"][mk] = {"variant": chosen, "params": prm}

    # elo ratings at end of data, for use in prediction
    model_json["elo_end"] = {t: round(v, 1) for t, v in sorted(state.elo.items())}
    model_json["scoring"] = {"gf": {t: round(v, 3) for t, v in state.gf.items()},
                             "ga": {t: round(v, 3) for t, v in state.ga.items()}}
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "holdout_results.json"), "w") as f:
        json.dump(res, f, indent=1)
    with open(os.path.join(out, "model.json"), "w") as f:
        json.dump(model_json, f, indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != "markets"}))
    for mk, b in res["markets"].items():
        print(mk, "chosen", b["chosen"], "val", b["validation_logloss"])
        for nm in ("holdout", "extra"):
            if nm in b:
                x = b[nm]
                print("  ", nm, x["n"], "mkt", x["logloss_market"], "model", x["logloss_model"],
                      x["diff_market_minus_model"], "overround", x["avg_overround"])


if __name__ == "__main__":
    main(*sys.argv[1:3])
