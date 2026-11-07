"""Hold-out evaluation. Train/tune on seasons before HOLDOUT_SEASON only; evaluate once on the
sealed hold-out (2025-26) and, as a pure forward check, on the partial 2026-27 season.

Run:  python3 tools/sports/racing/test.py     (needs out/dataset.csv.gz, out/betfair.csv.gz)
Writes OUT/holdout_results.json and OUT/model.json.
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model as M  # noqa: E402
from common import HOLDOUT_SEASON, OUT  # noqa: E402

BANDS = [0, 0.02, 0.04, 0.07, 0.10, 0.15, 0.20, 0.30, 0.40, 1.0]
RNG = np.random.default_rng(7)
TRIED = {"count": 0, "log": []}


def tried(what: str) -> None:
    TRIED["count"] += 1
    TRIED["log"].append(what)


def wilson(k: float, n: float, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (float(c - h), float(c + h))


def boot_mean(
    per_day: pd.DataFrame, n: int = 2000, pct: float = 95.0
) -> tuple[float, float, float]:
    """per_day has columns s (sum) and n (count) per race day. Mean and 95% race-day bootstrap."""
    s, c = per_day["s"].to_numpy(), per_day["n"].to_numpy()
    idx = RNG.integers(0, len(s), (n, len(s)))
    m = s[idx].sum(1) / c[idx].sum(1)
    t = (100 - pct) / 2
    return float(s.sum() / c.sum()), float(np.percentile(m, t)), float(np.percentile(m, 100 - t))


def paired_gain(ll_base: pd.DataFrame, ll_new: pd.DataFrame) -> dict:
    """Mean per-race log-loss gain of new over base (positive = new better), 95% race-day CI."""
    j = ll_base.merge(ll_new, on=["race", "date"], suffixes=("_b", "_n"))
    j["d"] = j["ll_b"] - j["ll_n"]
    pd_ = j.groupby("date")["d"].agg(s="sum", n="count")
    m, lo, hi = boot_mean(pd_)
    return {
        "races": len(j),
        "base_ll": float(j["ll_b"].mean()),
        "new_ll": float(j["ll_n"].mean()),
        "gain": m,
        "lo": lo,
        "hi": hi,
        "clears_95": bool(lo > 0),
    }


def calib(df: pd.DataFrame, p: pd.Series, by: pd.Series | None = None, bands=BANDS) -> list[dict]:
    """said (mean prob) vs got (win rate) per band, with 95% Wilson ranges."""
    d = pd.DataFrame({"p": p, "win": df["win"], "band": pd.cut(p, bands, include_lowest=True)})
    if by is not None:
        d["by"] = by
    d["band"] = d["band"].map(
        lambda i: f"{max(i.left, 0):.2f}-{i.right:.2f}" if pd.notna(i) else None
    )
    d = d[d["p"].notna()]
    out = []
    keys = ["band"] if by is None else ["by", "band"]
    for k, g in d.groupby(keys, observed=True):
        lo, hi = wilson(g["win"].sum(), len(g))
        r = {
            "n": len(g),
            "said": float(g["p"].mean()),
            "got": float(g["win"].mean()),
            "lo": lo,
            "hi": hi,
            "outside": bool(g["p"].mean() < lo or g["p"].mean() > hi),
        }
        if by is None:
            r["band"] = str(k[0] if isinstance(k, tuple) else k)
        else:
            r["by"], r["band"] = str(k[0]), str(k[1])
        out.append(r)
    return out


def roi(df: pd.DataFrame, price: pd.Series, mask: pd.Series) -> dict:
    """Flat $1 at ONE book's price. Dead heats paid in full (slightly generous)."""
    m = mask & price.notna()
    ret = (df["win"] * price - 1).where(m)
    g = pd.DataFrame({"date": df["date"], "r": ret})[m]
    if len(g) == 0:
        return {"bets": 0}
    pdv = g.groupby("date")["r"].agg(s="sum", n="count")
    mean, lo, hi = boot_mean(pdv)
    _, lo99, hi99 = boot_mean(pdv, pct=99.0)  # ~Bonferroni for 5 look-alike variants
    return {
        "bets": int(len(g)),
        "roi": mean,
        "lo": lo,
        "hi": hi,
        "lo99": lo99,
        "hi99": hi99,
        "clears_zero": bool(lo > 0),
        "clears_zero_99": bool(lo99 > 0),
    }


def cat(df: pd.DataFrame) -> dict[str, pd.Series]:
    cl = df["class"].fillna("").str.lower()
    ctype = np.select(
        [
            cl.str.contains("mdn|maiden"),
            cl.str.contains("group|listed|^g\\d|^lr"),
            cl.str.contains("bm|benchmark|cl|class|rst"),
        ],
        ["maiden", "black-type", "handicap/class"],
        "other",
    )
    fs = pd.cut(df["field_size"], [0, 7, 10, 13, 40], labels=["<=7", "8-10", "11-13", "14+"])
    dist = pd.cut(
        df["distance"],
        [0, 1100, 1400, 1800, 2400, 9999],
        labels=["<=1100", "1200-1400", "1500-1800", "1900-2400", "2500+"],
    )
    return {
        "state": df["state"],
        "field": fs.astype(str),
        "distance": dist.astype(str),
        "race type": pd.Series(ctype, index=df.index),
        "going": df["track_condition"].fillna("?").str.extract(r"^(\w+)")[0],
    }


def source_report(tr: pd.DataFrame, ho: pd.DataFrame, col: str) -> tuple[dict, dict]:
    """Proportional vs power for one price column; alpha tuned on train only."""
    qtr, qho = M.market_probs(tr, col), M.market_probs(ho, col)
    rtr, rho = M.race_id(tr), M.race_id(ho)
    a = M.fit_alpha(qtr, tr["win"], rtr)
    tried(f"{col}: power alpha")
    pho = M.power_probs(qho, rho, a)
    l0, l1 = M.race_logloss(qho, ho), M.race_logloss(pho, ho)
    rep = {
        "alpha_train": a,
        "holdout_races": len(l0),
        "overround_mean": float(M.overround(ho, col).mean()),
        "logloss_proportional": float(l0["ll"].mean()),
        "logloss_power": float(l1["ll"].mean()),
        "power_vs_proportional": paired_gain(l0, l1),
    }
    return rep, {"q": qho, "p": pho, "a": a}


def main() -> None:
    res: dict = {"holdout_season": HOLDOUT_SEASON}
    d = pd.read_csv(os.path.join(OUT, "dataset.csv.gz"), low_memory=False)
    d = d[~d["venue"].isin(["sha-tin", "happy-valley"])]  # Hong Kong, not in Betfair ANZ files
    tr = d[d["season"].isin(["2022-23", "2023-24", "2024-25"])].reset_index(drop=True)
    ho = d[d["season"] == HOLDOUT_SEASON].reset_index(drop=True)
    fw = d[d["season"] == "2026-27"].reset_index(drop=True)
    res["sizes"] = {
        "train_rows": len(tr),
        "holdout_rows": len(ho),
        "forward_rows": len(fw),
        "holdout_races": int(M.race_id(ho).nunique()),
    }

    # 1. each price source: proportional vs power, on its own complete races
    res["sources"], keep = {}, {}
    for col in ["sb", "lb", "tote_v", "tote_n", "sp", "bsp"]:
        rep, k = source_report(tr, ho, col)
        res["sources"][col] = rep
        keep[col] = k

    # 2. all sources on IDENTICAL races (Sportsbet, Ladbrokes, tote, Betfair BSP all complete)
    cols = ["sb", "lb", "tote_v", "bsp"]
    ok = pd.concat([M.market_probs(ho, c).notna() for c in cols], axis=1).all(axis=1)
    common = ho[ok]
    rows = {}
    base = None
    for c in cols:
        ls = M.race_logloss(keep[c]["q"][ok], common)
        rows[c] = {"logloss": float(ls["ll"].mean()), "races": len(ls)}
        base = base if base is not None else ls
        if c != "sb":
            rows[c]["vs_sb_gain"] = paired_gain(base, ls)
        lp = M.race_logloss(keep[c]["p"][ok], common)
        rows[c]["logloss_power"] = float(lp["ll"].mean())
    res["identical_races"] = rows

    # 3. feature model on Sportsbet, trained on train seasons, tested on hold-out
    qtr, qho = M.market_probs(tr, "sb"), M.market_probs(ho, "sb")
    allq = pd.concat([qtr, qho, M.market_probs(fw, "sb")])
    alld = pd.concat([tr, ho, fw]).reset_index(drop=True)
    alld = M.add_prior_residuals(alld, allq.reset_index(drop=True))
    ntr, nho = len(tr), len(ho)
    tr2, ho2, fw2 = alld.iloc[:ntr], alld.iloc[ntr : ntr + nho], alld.iloc[ntr + nho :]
    fm = M.FeatureModel(l2=50.0).fit(tr2, qtr)
    tried("feature model (9 features) l2=50")
    pf = fm.predict(ho2.reset_index(drop=True), qho)
    l_prop = M.race_logloss(qho, ho2.reset_index(drop=True))
    l_pow = M.race_logloss(keep["sb"]["p"], ho2.reset_index(drop=True))
    l_fm = M.race_logloss(pf, ho2.reset_index(drop=True))
    res["feature_model"] = {
        "alpha": fm.alpha,
        "beta": dict(zip(M.FEATURES, fm.beta.tolist(), strict=True)),
        "vs_proportional": paired_gain(l_prop, l_fm),
        "vs_power": paired_gain(l_pow, l_fm),
        "power_vs_proportional": paired_gain(l_prop, l_pow),
    }
    # forward check (2026-27, untouched until here)
    qfw = M.market_probs(fw2.reset_index(drop=True), "sb")
    pfw = fm.predict(fw2.reset_index(drop=True), qfw)
    pwfw = M.power_probs(qfw, M.race_id(fw2.reset_index(drop=True)), keep["sb"]["a"])
    f0 = M.race_logloss(qfw, fw2.reset_index(drop=True))
    res["forward_2026_27"] = {
        "races": len(f0),
        "power_vs_proportional": paired_gain(f0, M.race_logloss(pwfw, fw2.reset_index(drop=True))),
        "feature_vs_proportional": paired_gain(f0, M.race_logloss(pfw, fw2.reset_index(drop=True))),
    }

    # 4. calibration (Sportsbet de-margined, hold-out): overall, per market type
    hq = qho.reset_index(drop=True)
    hp = keep["sb"]["p"].reset_index(drop=True)
    hh = ho.reset_index(drop=True)
    res["calibration"] = {"proportional_overall": calib(hh, hq), "power_overall": calib(hh, hp)}
    tried("calibration overall x2")
    res["calibration_by_type"] = {}
    for name, ser in cat(hh).items():
        res["calibration_by_type"][name] = calib(hh, hp, ser.reset_index(drop=True))
        tried(f"calibration by {name}")
    res["calibration_by_book"] = {}
    for c in ["sb", "lb", "tote_v", "sp", "bsp"]:
        res["calibration_by_book"][c] = calib(hh, keep[c]["p"].reset_index(drop=True))
        tried(f"calibration book {c}")
    flat = [r for k in res["calibration_by_type"].values() for r in k if r["n"] >= 300]
    res["calibration_by_type_summary"] = {
        "cells_n>=300": len(flat),
        "outside_95": sum(r["outside"] for r in flat),
        "expected_outside_by_chance": round(0.05 * len(flat), 1),
    }

    # 5. place market (fields >=8, top 3), Sportsbet and tote prices
    res["place"] = {}
    pm = hh[hh["field_size"] >= 8].reset_index(drop=True)
    for col in ["sb_place", "tote_v_place", "lb_place"]:
        if col not in pm:
            continue
        inv = 1 / pm[col].where(pm[col] > 1)
        rid = M.race_id(pm)
        ok = inv.notna().groupby(rid).transform("all")
        q = (inv * 3 / inv.groupby(rid).transform("sum")).where(ok)
        q = q.clip(upper=0.999)
        d_ = pd.DataFrame({"p": q, "top3": pm["top3"]})
        d_ = d_[d_["p"].notna()]
        d_["band"] = pd.cut(d_["p"], [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.65, 1.0])
        rows = []
        for b, g in d_.groupby("band", observed=True):
            lo, hi = wilson(g["top3"].sum(), len(g))
            rows.append(
                {
                    "band": str(b),
                    "n": len(g),
                    "said": float(g["p"].mean()),
                    "got": float(g["top3"].mean()),
                    "lo": lo,
                    "hi": hi,
                    "outside": bool(g["p"].mean() < lo or g["p"].mean() > hi),
                }
            )
        res["place"][col] = {
            "overround_mean": float(inv.groupby(rid).sum()[ok.groupby(rid).first()].div(3).mean()),
            "bands": rows,
        }
        tried(f"place calibration {col}")

    # 6. ROI at single-book Sportsbet price (hold-out). Bands defined on de-margined probability.
    sb = hh["sb"]
    res["roi_sportsbet"] = {"all_runners": roi(hh, sb, sb.notna())}
    bands = {}
    for lo_, hi_ in zip(BANDS[:-1], BANDS[1:], strict=True):
        m = (hq > lo_) & (hq <= hi_)
        bands[f"{lo_:.2f}-{hi_:.2f}"] = roi(hh, sb, m)
        tried(f"roi band {lo_}-{hi_}")
    res["roi_sportsbet"]["by_band"] = bands
    for name, pser, thr in [
        ("power", hp, 1.0),
        ("power", hp, 1.05),
        ("feature", pf.reset_index(drop=True), 1.0),
        ("feature", pf.reset_index(drop=True), 1.05),
        ("feature", pf.reset_index(drop=True), 1.10),
    ]:
        res["roi_sportsbet"][f"value_{name}_edge{thr}"] = roi(hh, sb, (pser * sb) > thr)
        tried(f"roi value {name} {thr}")
    # forward ROI (2026-27, untouched): same rules, nothing re-tuned
    fwh = fw2.reset_index(drop=True)
    fsb = fwh["sb"]
    res["roi_forward_2026_27"] = {"all_runners": roi(fwh, fsb, fsb.notna())}
    for thr in [1.0, 1.05, 1.10]:
        res["roi_forward_2026_27"][f"value_feature_edge{thr}"] = roi(
            fwh, fsb, (pfw.reset_index(drop=True) * fsb) > thr
        )
        res["roi_forward_2026_27"][f"value_power_edge{thr}"] = roi(
            fwh, fsb, (pwfw.reset_index(drop=True) * fsb) > thr
        )
    # ROI by price source if backing everything (shows each book's margin)
    res["roi_all_runners_by_book"] = {
        c: roi(hh, hh[c], hh[c].notna()) for c in ["sb", "lb", "tote_v", "sp"]
    }

    # 7. Betfair file, longer history: exchange prices as market (train 2019-20..2024-25)
    bf = pd.read_csv(os.path.join(OUT, "betfair.csv.gz"), low_memory=False)
    bf["meeting_id"] = bf["date"] + bf["track"]
    btr = bf[bf["season"] < HOLDOUT_SEASON].reset_index(drop=True)
    bho = bf[bf["season"] == HOLDOUT_SEASON].reset_index(drop=True)
    res["betfair_file"] = {"train_rows": len(btr), "holdout_rows": len(bho)}
    for col in ["bsp", "preplay_wavg"]:
        rep, _ = source_report(btr, bho, col)
        res["betfair_file"][col] = rep
    res["tried_count"] = TRIED["count"]
    res["tried_log"] = TRIED["log"]
    M.save_json(res, os.path.join(OUT, "holdout_results.json"))
    M.save_json(
        {
            "market_column": "sb",
            "alpha_power": keep["sb"]["a"],
            "feature_model": fm.to_json(),
            "trained_on": ["2022-23", "2023-24", "2024-25"],
            "holdout": HOLDOUT_SEASON,
            "use": "p = softmax(alpha*log(q) + beta.x_std); "
            "q = proportional de-margin of Sportsbet win prices",
        },
        os.path.join(OUT, "model.json"),
    )
    print("done; tried", TRIED["count"])


if __name__ == "__main__":
    main()
