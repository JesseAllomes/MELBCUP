"""Honest hold-out evaluation. Tune on seasons <= 2024, seal 2025, 2026 (partial) as 2nd check.

Writes OUT/holdout_results.json. Usage: python -m tools.sports.afl.test
Markets: h2h (closing single book, and average of books), line, total.
"""

import json

import numpy as np
import pandas as pd

from tools.sports.afl import model as M
from tools.sports.afl.build import build
from tools.sports.afl.paths import OUT, REPO_OUT

HOLD = 2025
RNG = np.random.default_rng(20261107)
NB = 4000


def boot_ci(x, n=NB, alpha=0.05):
    x = np.asarray(x, dtype=float)
    idx = RNG.integers(0, len(x), (n, len(x)))
    m = x[idx].mean(1)
    return [float(np.quantile(m, alpha / 2)), float(np.quantile(m, 1 - alpha / 2))]


def wilson(h, n, z=1.96):
    if n == 0:
        return [None, None]
    p = h / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    w = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [float(c - w), float(c + w)]


def calib(p, y, edges):
    rows = []
    p, y = np.asarray(p), np.asarray(y)
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        m = (p >= lo) & (p < hi)
        n = int(m.sum())
        if n:
            rows.append(
                {
                    "band": f"{lo:.2f}-{hi:.2f}",
                    "n": n,
                    "said": float(p[m].mean()),
                    "got": float(y[m].mean()),
                    "got_95": wilson(float(y[m].sum()), n),
                }
            )
    return rows


EDGES = [0, 0.2, 0.35, 0.5, 0.65, 0.8, 1.0001]


def line_total_frames(d: pd.DataFrame):
    ln = d.dropna(subset=["line_close", "h_line_odds", "a_line_odds"]).copy()
    ln["cover"] = ln["margin"] + ln["line_close"]
    ln = ln[ln["cover"] != 0].copy()
    ln["y"] = (ln["cover"] > 0).astype(float)
    ln["o1"], ln["o2"] = ln["h_line_odds"], ln["a_line_odds"]
    tt = d.dropna(subset=["total_close", "over_odds", "under_odds"]).copy()
    tt["diff"] = tt["total"] - tt["total_close"]
    tt = tt[tt["diff"] != 0].copy()
    tt["y"] = (tt["diff"] > 0).astype(float)
    tt["o1"], tt["o2"] = tt["over_odds"], tt["under_odds"]
    return ln, tt


def simple_market_eval(f: pd.DataFrame, hold_season: int, name: str, tried: list):
    """Line/total: market vs power-k vs recal, fitted on train seasons only."""
    tr, ho = f[f.season < hold_season], f[f.season == hold_season]
    res = {"n_train": len(tr), "n_hold": len(ho)}
    y = ho["y"].to_numpy()
    base = M.devig(ho.o1, ho.o2)
    k = M.fit_power_k(tr.o1, tr.o2, tr["y"])
    w = M.fit_logit(M.logit(M.devig(tr.o1, tr.o2)).reshape(-1, 1), tr["y"].to_numpy())
    cands = {
        "market": base,
        "power": M.devig(ho.o1, ho.o2, k),
        "recal": M.predict_logit(w, M.logit(base).reshape(-1, 1)),
    }
    tried += [f"{name}:power", f"{name}:recal"]
    lb = M.log_loss(base, y)
    res["power_k"], res["recal"] = k, w.tolist()
    res["models"] = {}
    for nme, p in cands.items():
        ll = M.log_loss(p, y)
        res["models"][nme] = {
            "logloss": float(ll.mean()),
            "diff_vs_market": float((ll - lb).mean()),
            "diff_95": boot_ci(ll - lb),
        }
    res["margin_mean"] = float((M.overround(ho.o1, ho.o2)).mean())
    # side-level calibration on the raw market (nothing fitted): first side vs second side
    res["calib_market_hold"] = calib(base, y, EDGES)
    allp = M.devig(f.o1, f.o2)
    res["calib_market_all_seasons"] = calib(allp, f["y"].to_numpy(), EDGES)
    res["n_all"] = int(len(f))
    return res


def roi(p, o, y, edge):
    """Flat 1-unit bets where model p * book odds > 1+edge, at ONE book's prices."""
    p, o, y = map(np.asarray, (p, o, y))
    m = p * o > 1 + edge
    n = int(m.sum())
    if n == 0:
        return {"edge": edge, "bets": 0}
    r = np.where(y[m] == 1, o[m] - 1, -1.0)
    return {
        "edge": edge,
        "bets": n,
        "hit": float(y[m].mean()),
        "roi": float(r.mean()),
        "roi_95": boot_ci(r),
    }


def run() -> dict:
    d = (
        pd.read_csv(OUT / "games_with_odds.csv.gz", parse_dates=["date"])
        if (OUT / "games_with_odds.csv.gz").exists()
        else build()
    )
    d = d[d.finals.ge(0)].copy()
    tried: list[str] = []
    res: dict = {
        "hold_season": HOLD,
        "rows": int(len(d)),
        "seasons": [int(d.season.min()), int(d.season.max())],
    }
    # tune Elo on <=2024
    ep, ngrid = M.tune_elo(d, HOLD - 1)
    tried += [f"elo_grid:{ngrid}"]
    d = M.add_elo(d, **ep)
    d = M.add_rest(d)
    res["elo_params"] = ep

    # ---- H2H, single book closing (Pinnacle <= 2018-04-02, bet365 after) ----------------------
    h = d.dropna(subset=["h_close", "a_close"])
    train = h[h.season < HOLD]
    fit = M.fit_model(train)
    tried += ["h2h:power", "h2h:recal", "h2h:elo", "h2h:elo_rest"]
    res["h2h_fit"] = fit
    out = {}
    splits = (("hold_2025", h[h.season == HOLD]), ("fwd_2026_partial", h[h.season > HOLD]))
    for label, sub in splits:
        y = sub["home_win"].to_numpy()
        base = M.predict_h2h(fit, sub, "market")
        lb = M.log_loss(base, y)
        mods = {}
        for kind in ("market", "power", "recal", "elo", "elo_rest"):
            p = M.predict_h2h(fit, sub, kind)
            ll = M.log_loss(p, y)
            mods[kind] = {
                "logloss": float(ll.mean()),
                "diff_vs_market": float((ll - lb).mean()),
                "diff_95": boot_ci(ll - lb),
                "brier": float(((p - y) ** 2).mean()),
                "acc": float(((p > 0.5) == (y > 0.5)).mean()),
            }
        out[label] = {
            "n": int(len(sub)),
            "models": mods,
            "overround_mean": float(M.overround(sub.h_close, sub.a_close).mean()),
        }
        out[label]["roi_single_book"] = {
            kind: [
                roi(
                    np.r_[M.predict_h2h(fit, sub, kind), 1 - M.predict_h2h(fit, sub, kind)],
                    np.r_[sub.h_close, sub.a_close],
                    np.r_[y, 1 - y],
                    e,
                )
                for e in (0.0, 0.03, 0.05)
            ]
            for kind in ("market", "recal", "elo")
        }
    tried += [f"roi:{k}:{e}" for k in ("market", "recal", "elo") for e in (0, 0.03, 0.05)]
    # blind baselines: bet every home / every away at the single book (shows the margin cost)
    sub = h[h.season == HOLD]
    out["blind_hold_2025"] = {
        "home": roi(np.ones(len(sub)), sub.h_close, sub.home_win, -1.0),
        "away": roi(np.ones(len(sub)), sub.a_close, 1 - sub.home_win, -1.0),
    }
    # average-of-books market (2009+) vs single-book close: is the single book sharper?
    ha = d.dropna(subset=["h_avg", "a_avg", "h_close", "a_close"])
    sub = ha[ha.season == HOLD]
    ya = sub["home_win"].to_numpy()
    out["avg_vs_close_hold_2025"] = {
        "logloss_avg": float(M.log_loss(M.devig(sub.h_avg, sub.a_avg), ya).mean()),
        "logloss_close": float(M.log_loss(M.devig(sub.h_close, sub.a_close), ya).mean()),
        "logloss_open": float(M.log_loss(M.devig(sub.h_open, sub.a_open), ya).mean()),
    }
    # calibration, raw market (nothing fitted), single book close: all seasons and hold-out
    pall = M.devig(h.h_close, h.a_close)
    out["calib_market_all_seasons"] = calib(pall, h["home_win"].to_numpy(), EDGES)
    ph = M.devig(h[h.season == HOLD].h_close, h[h.season == HOLD].a_close)
    out["calib_market_hold"] = calib(ph, h[h.season == HOLD]["home_win"].to_numpy(), EDGES)
    # home vs away side, favourite vs dog on the market (all seasons)
    fav = pall >= 0.5
    yy = h["home_win"].to_numpy()
    sides = {}
    for nm, m_p, m_y in (
        ("home_fav", pall[fav], yy[fav]),
        ("home_dog", pall[~fav], yy[~fav]),
        ("away_fav", 1 - pall[~fav], 1 - yy[~fav]),
        ("away_dog", 1 - pall[fav], 1 - yy[fav]),
    ):
        sides[nm] = {
            "n": int(len(m_p)),
            "said": float(m_p.mean()),
            "got": float(m_y.mean()),
            "got_95": wilson(float(m_y.sum()), len(m_y)),
        }
    out["side_calibration_all_seasons"] = sides
    res["h2h"] = out

    # ---- line and total -----------------------------------------------------------------------
    ln, tt = line_total_frames(d)
    res["line"] = simple_market_eval(ln, HOLD, "line", tried)
    res["total"] = simple_market_eval(tt, HOLD, "total", tried)
    # over / under side calibration
    for nm, f in (("line", ln), ("total", tt)):
        p = M.devig(f.o1, f.o2)
        res[nm]["side_calibration_all_seasons"] = {
            "first_side(home_cover/over)": {
                "said": float(p.mean()),
                "got": float(f.y.mean()),
                "n": int(len(f)),
                "got_95": wilson(float(f.y.sum()), len(f)),
            }
        }
    # line and total ROI at one book's prices (bet365 post-2018) with recal model, hold-out
    for nm, f in (("line", ln), ("total", tt)):
        ho = f[f.season == HOLD]
        r = res[nm]
        p1 = M.predict_logit(np.array(r["recal"]), M.logit(M.devig(ho.o1, ho.o2)).reshape(-1, 1))
        yv = ho["y"].to_numpy()
        r["roi_single_book_recal"] = [
            roi(np.r_[p1, 1 - p1], np.r_[ho.o1, ho.o2], np.r_[yv, 1 - yv], e) for e in (0, 0.03)
        ]
        r["blind_first_side"] = roi(np.ones(len(ho)), ho.o1, yv, -1.0)
        r["blind_second_side"] = roi(np.ones(len(ho)), ho.o2, 1 - yv, -1.0)
    tried += [f"roi:{n}:{e}" for n in ("line", "total") for e in (0, 0.03)]

    # ---- price-band reliability across all three market types (all seasons, raw market) --------
    res["tried_count"] = len(tried)
    res["tried"] = tried
    k_comp = len(tried)
    res["bonferroni_alpha_per_test"] = 0.05 / max(k_comp, 1)
    # final model: refit on everything up to and including hold-out for publication
    final_train = h[h.season <= HOLD]
    final = M.fit_model(final_train)
    _, _, ratings = M.elo_run(d, ep["k"], ep["hga"])
    final["elo_params"] = ep
    final["elo_ratings_end"] = {k: round(v, 1) for k, v in sorted(ratings.items())}
    final["note"] = (
        "Start from de-margined single-book close; adjustments are listed but only "
        "used if holdout_results.json shows a gain outside its 95% range."
    )
    res["_final_model"] = final
    return res


def main():
    res = run()
    final = res.pop("_final_model")
    OUT.mkdir(parents=True, exist_ok=True)
    REPO_OUT.mkdir(parents=True, exist_ok=True)
    for dest in (OUT, REPO_OUT):
        (dest / "holdout_results.json").write_text(json.dumps(res, indent=1))
        (dest / "model.json").write_text(json.dumps(final, indent=1))
    print(json.dumps({k: res[k] for k in ("hold_season", "rows", "tried_count")}))


if __name__ == "__main__":
    main()
