# ruff: noqa: E501
"""Hold-out evaluation. Prints the tables research/sports/nba.md quotes and writes the JSON.

    python3 tools/sports/nba/test.py [DATA_DIR]

Games: fit on 2007-08..2019-20, choose among 4 variants on 2020-21 only, refit on <=2020-21 and
score the sealed 2021-22 season (and the part-season 2022-23 the archive holds). Props: 2024-25
only, one season, so a date split (first 55% fit, rest scored); nothing is sealed, so treat it as
indicative. Prices for games are one source's closing line; spread and total prices are not in the
archive, so their ROI assumes -110 (marked "assumed").
"""

from __future__ import annotations

import csv
import gzip
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model as M  # noqa: E402

RAW = "/tmp/claude-0/-home-user/418442d0-6a93-5b3f-a291-37c2b3744726/scratchpad/sports/nba"
RNG = np.random.default_rng(7)
TRIED = {"game_variants": len(M.VARIANTS), "game_bands": 0, "prop_cuts": 0}


def boot_ci(d: np.ndarray, n: int = 2000) -> tuple[float, float, float]:
    """Mean and 95% range of a per-bet difference (bootstrap)."""
    if len(d) == 0:
        return (0.0, 0.0, 0.0)
    m = RNG.integers(0, len(d), (n, len(d)))
    means = d[m].mean(1)
    return float(d.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def roi(dec: np.ndarray, win: np.ndarray) -> dict:
    r = dec * win - 1.0
    m, lo, hi = boot_ci(r)
    return {"n": int(len(r)), "roi": round(m, 4), "lo": round(lo, 4), "hi": round(hi, 4)}


def band_table(p, y, edges, label=""):
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
        TRIED["game_bands"] += 1
    return rows


def games_section(data: str) -> dict:
    games = M.load_games(os.path.join(data, "games.csv.gz"))
    f = M.game_features(games)
    seas = np.array([games[i]["season"] for i in f["idx"]])
    train = seas <= "2019-20"
    val = seas == "2020-21"
    ho = seas == "2021-22"
    part = seas == "2022-23"
    out = {"rows": len(games), "with_moneyline": int(len(f["idx"])),
           "seasons": sorted(set(seas.tolist()))}
    # 1. choose on 2020-21
    val_ll = {}
    for v in M.VARIANTS:
        w = M.fit_variant(v, f, train)
        val_ll[v] = float(M.log_loss_each(M.predict_variant(v, w, f, val), f["y"][val]).mean())
    out["validation_2020_21_logloss"] = val_ll
    best = min(val_ll, key=val_ll.get)
    out["chosen_on_validation"] = best
    # 2. refit on <=2020-21, score sealed seasons
    fit_mask = seas <= "2020-21"
    res, models = {}, {}
    for v in M.VARIANTS:
        w = M.fit_variant(v, f, fit_mask)
        models[v] = w
        for nm, mk in (("holdout_2021_22", ho), ("part_2022_23", part)):
            p = M.predict_variant(v, w, f, mk)
            res.setdefault(nm, {})[v] = {"logloss": round(float(M.log_loss_each(p, f["y"][mk]).mean()), 5)}
            if v != "market":
                d = M.log_loss_each(f["pm"][mk], f["y"][mk]) - M.log_loss_each(p, f["y"][mk])
                m, lo, hi = boot_ci(d)
                res[nm][v].update({"model_better_than_market_by": round(m, 5),
                                   "lo": round(lo, 5), "hi": round(hi, 5)})
    out["results"] = res
    out["models"] = models
    # 3. calibration by price band on the home-win chance, market said vs got, all seasons / holdout
    edges = [0, .2, .3, .4, .5, .6, .7, .8, 1.0001]
    for nm, mk in (("2007_2020", seas <= "2020-21"), ("holdout_2021_22", ho)):
        out.setdefault("calibration_home_win", {})[nm] = band_table(f["pm"][mk], f["y"][mk], edges)
        # away sides: the mirror chance
        out.setdefault("calibration_away_win", {})[nm] = band_table(1 - f["pm"][mk], 1 - f["y"][mk], edges)
    # 4. ROI at the single source's closing moneyline (the archive's one line, not best-of-books)
    ml_h = np.array([games[i]["ml_home"] for i in f["idx"]])
    ml_a = np.array([games[i]["ml_away"] for i in f["idx"]])
    dh = np.array([M.decimal_from_american(x) for x in ml_h])
    da = np.array([M.decimal_from_american(x) for x in ml_a])
    y = f["y"]
    rois = {}
    for nm, mk in (("2007_2020", seas <= "2020-21"), ("holdout_2021_22", ho)):
        r = {}
        fav_home = f["pm"] >= .5
        pfav = np.where(fav_home, f["pm"], 1 - f["pm"])
        dfav = np.where(fav_home, dh, da)
        wfav = np.where(fav_home, y, 1 - y)
        dog_d = np.where(fav_home, da, dh)
        wdog = 1 - wfav
        r["all_favourites"] = roi(dfav[mk], wfav[mk])
        r["all_underdogs"] = roi(dog_d[mk], wdog[mk])
        r["all_home"] = roi(dh[mk], y[mk])
        r["all_away"] = roi(da[mk], 1 - y[mk])
        for a, b in ((.5, .6), (.6, .7), (.7, .8), (.8, 1.01)):
            k = mk & (pfav >= a) & (pfav < b)
            r[f"favourite_{a:.1f}-{b:.1f}"] = roi(dfav[k], wfav[k])
            r[f"underdog_of_{a:.1f}-{b:.1f}_fav"] = roi(dog_d[k], wdog[k])
        rois[nm] = r
    # model-side bets on the sealed season, by the best validation variant (if not the market)
    for v in M.VARIANTS:
        if v == "market":
            continue
        p = M.predict_variant(v, models[v], f, ho)
        for thr in (0.0, 0.03, 0.05):
            home_bet = p - f["pm"][ho] > thr
            away_bet = (1 - p) - (1 - f["pm"][ho]) > thr
            dec = np.concatenate([dh[ho][home_bet], da[ho][away_bet]])
            win = np.concatenate([y[ho][home_bet], 1 - y[ho][away_bet]])
            rois.setdefault("model_side_holdout", {})[f"{v}_edge>={thr:.2f}"] = roi(dec, win)
    out["roi_single_source_ml"] = rois
    # 5. spreads and totals (closing line; result vs line, pushes dropped)
    st = {}
    for nm, mk_s in (("2007_2020", lambda s: s <= "2020-21"), ("holdout_2021_22", lambda s: s == "2021-22")):
        gs = [g for g in games if mk_s(g["season"])]
        marg = np.array([g["home_pts"] - g["away_pts"] for g in gs], float)
        sp = np.array([g["spread_home_close"] if g["spread_home_close"] is not None else np.nan for g in gs])
        tot = np.array([g["total_close"] for g in gs], float)
        pts = np.array([g["home_pts"] + g["away_pts"] for g in gs], float)
        cov = marg + sp
        k = np.isfinite(cov) & (cov != 0)
        home_cover = (cov[k] > 0).astype(float)
        over = (pts - tot)
        ko = over != 0
        o = (over[ko] > 0).astype(float)
        d = 1.9091
        def rate(a):
            lo, hi = M.wilson(int(a.sum()), len(a))
            return {"n": len(a), "got": round(float(a.mean()), 4), "lo": round(lo, 3), "hi": round(hi, 3)}
        entry = {"home_covers": rate(home_cover), "over": rate(o),
                 "assumed_-110_roi_home": roi(np.full(len(home_cover), d), home_cover),
                 "assumed_-110_roi_over": roi(np.full(len(o), d), o), "bands": {}}
        tb = [(0, 205), (205, 215), (215, 225), (225, 235), (235, 400)]
        for a, b in tb:
            kk = (tot[ko] >= a) & (tot[ko] < b)
            if kk.sum():
                entry["bands"][f"total_{a}-{b}_over"] = rate(o[kk])
                TRIED["game_bands"] += 1
        sb = [(0, 3), (3, 6), (6, 10), (10, 40)]
        for a, b in sb:
            kk = (np.abs(sp[k]) >= a) & (np.abs(sp[k]) < b)
            if kk.sum():
                fav_cover = np.where(sp[k][kk] < 0, home_cover[kk], 1 - home_cover[kk])
                entry["bands"][f"spread_{a}-{b}_favourite_covers"] = rate(fav_cover)
                TRIED["game_bands"] += 1
        st[nm] = entry
    out["spread_total"] = st
    return out


def props_section(data: str) -> dict:
    rows = list(csv.DictReader(gzip.open(os.path.join(data, "props.csv.gz"), "rt")))
    rows.sort(key=lambda r: r["date"])
    cut = int(len(rows) * 0.55)
    po = np.array([M.devig(float(r["over_odds"]), float(r["under_odds"])) for r in rows])
    y = np.array([1.0 if r["result"] == "over" else 0.0 for r in rows])
    stat = np.array([r["stat"] for r in rows])
    do = np.array([M.decimal_from_american(float(r["over_odds"])) for r in rows])
    du = np.array([M.decimal_from_american(float(r["under_odds"])) for r in rows])
    mp = np.array([float(r["min_prior10"]) if r["min_prior10"] else np.nan for r in rows])
    out = {"rows": len(rows), "dates": [rows[0]["date"], rows[-1]["date"]],
           "fit_rows": cut, "scored_rows": len(rows) - cut, "split_date": rows[cut]["date"]}
    tr, te = np.arange(len(rows)) < cut, np.arange(len(rows)) >= cut
    base = M.log_loss_each(po[te], y[te])
    variants = {}
    # v1: one over/under shift
    X = M.logit(po)[:, None]
    # shift on top of the market logit: p = sigmoid(logit(po) + a), a fit with slope fixed 1
    a = 0.0
    for _ in range(100):
        p = M.sigmoid(M.logit(po[tr]) + a)
        a -= (p - y[tr]).sum() / max((p * (1 - p)).sum(), 1e-9)
    variants["shift_all"] = M.sigmoid(M.logit(po) + a)
    out["shift_all_fitted_a"] = round(float(a), 4)
    w = M.fit_logit(X[tr], y[tr])
    variants["shift_and_slope"] = M.predict_logit(w, X)
    out["shift_slope_w"] = [round(float(x), 4) for x in w]
    ps = po.copy()
    shifts = {}
    for s in sorted(set(stat)):
        k = tr & (stat == s)
        aa = 0.0
        for _ in range(100):
            p = M.sigmoid(M.logit(po[k]) + aa)
            aa -= (p - y[k]).sum() / max((p * (1 - p)).sum(), 1e-9)
        shifts[s] = round(float(aa) * len(po[k]) / (len(po[k]) + 800), 4)  # shrunk like learn.py
        ps[stat == s] = M.sigmoid(M.logit(po[stat == s]) + shifts[s])
    variants["shift_per_stat_shrunk"] = ps
    out["per_stat_shifts"] = shifts
    out["logloss_scored"] = {"market": round(float(base.mean()), 5)}
    for nm, p in variants.items():
        d = base - M.log_loss_each(p[te], y[te])
        m, lo, hi = boot_ci(d)
        out["logloss_scored"][nm] = {"logloss": round(float(M.log_loss_each(p[te], y[te]).mean()), 5),
                                     "better_than_market_by": round(m, 5), "lo": round(lo, 5), "hi": round(hi, 5)}
    TRIED["prop_cuts"] += 3
    # calibration of the market: said vs got, by stat / side / price band / role, all 1079 rows
    def cal(k, nm):
        n = int(k.sum())
        if n == 0:
            return None
        hits = int(y[k].sum())
        lo, hi = M.wilson(hits, n)
        TRIED["prop_cuts"] += 1
        return {"cut": nm, "n": n, "market_said_over": round(float(po[k].mean()), 3),
                "got_over": round(hits / n, 3), "lo": round(lo, 3), "hi": round(hi, 3),
                "outside": bool(po[k].mean() < lo or po[k].mean() > hi),
                "roi_over": roi(do[k], y[k]), "roi_under": roi(du[k], 1 - y[k])}
    allk = np.ones(len(rows), bool)
    cuts = [cal(allk, "all")]
    for s in sorted(set(stat)):
        cuts.append(cal(stat == s, f"stat={s}"))
    for a_, b_ in ((0, .4), (.4, .45), (.45, .5), (.5, .55), (.55, .6), (.6, 1.01)):
        cuts.append(cal((po >= a_) & (po < b_), f"market_over_prob {a_:.2f}-{b_:.2f}"))
    for a_, b_ in ((0, 28), (28, 33), (33, 99)):
        cuts.append(cal(np.isfinite(mp) & (mp >= a_) & (mp < b_), f"prior10_minutes {a_}-{b_}"))
    for s in sorted(set(stat)):
        for a_, b_ in ((0, .47), (.47, .53), (.53, 1.01)):
            cuts.append(cal((stat == s) & (po >= a_) & (po < b_), f"{s} over_prob {a_:.2f}-{b_:.2f}"))
    out["calibration_cuts"] = [c for c in cuts if c]
    return out


def main(base: str = RAW) -> None:
    data = os.path.join(base, "data")
    res = {"games": games_section(data), "props": props_section(data)}
    res["tried"] = TRIED
    path = os.path.join(data, "holdout_results.json")
    json.dump(res, open(path, "w"), indent=1)
    mdl = {"fit_through": "2020-21", "elo": {"k": 20, "home": 100, "carry": 0.75},
           "game_models_logit_weights": res["games"]["models"],
           "chosen": res["games"]["chosen_on_validation"],
           "prop_shift_all": res["props"]["shift_all_fitted_a"],
           "prop_per_stat_shifts": res["props"]["per_stat_shifts"],
           "note": "chosen = the market itself; no model cleared the market on validation."}
    json.dump(mdl, open(os.path.join(data, "model.json"), "w"), indent=1)
    g = res["games"]
    print("chosen on 2020-21:", g["chosen_on_validation"], g["validation_2020_21_logloss"])
    for nm, d in g["results"].items():
        print(nm, json.dumps(d))
    print("props:", json.dumps(res["props"]["logloss_scored"]))
    print("tried", TRIED, "->", path)


if __name__ == "__main__":
    main(*sys.argv[1:2])
