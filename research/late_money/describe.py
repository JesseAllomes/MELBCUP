"""Step 2: when does money come in? Development blocks only (train + tune1), starters of T-2-eligible races.
Writes $LM_DIR/out/describe.json and prints the tables used in RERUN.md."""
import json, os, sys
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lm_lib as L

os.makedirs(f"{L.LM}/out", exist_ok=True)
d = pd.read_pickle(f"{L.LM}/prep/runners_T2.pkl")
d = d[(d["date"] >= L.DEV_START) & (d["date"] <= L.DEV_END)].copy()
GRID = ["open", "t120", "t60", "t30", "t15", "t10", "t5", "t2", "t0"]
LAB = {"open": "open", "t120": "-120", "t60": "-60", "t30": "-30", "t15": "-15", "t10": "-10", "t5": "-5", "t2": "-2", "t0": "jump"}
col = lambda b, g: f"{b}_{g}"
# mean-of-books log price at each grid time (books with a quote at that time)
lp = {}
for g in GRID:
    lp[g] = pd.concat([np.log(d[col(b, g)]) for b in ("sb", "lb")], axis=1).mean(axis=1)
out = {}
print(f"development starters: {len(d)} in {d['race_id'].nunique()} races, {d['day'].nunique()} race days")

# ---- 1. segment moves (firm = price shorter: positive)
rows = []; tot_ss = 0.0
segs = list(zip(GRID[:-1], GRID[1:]))
for a, b in segs:
    mv = (lp[a] - lp[b]).dropna()
    rows.append(dict(segment=f"{LAB[a]} to {LAB[b]}", n=len(mv), median_abs_pct=100 * (np.exp(mv.abs()) - 1).median(), p90_abs_pct=100 * (np.exp(mv.abs().quantile(.9)) - 1),
                     share_moving_5pct=(mv.abs() >= np.log(1 / 0.95)).mean() * 100, ss=(mv ** 2).sum()))
S = pd.DataFrame(rows); S["share_of_squared_move_pct"] = 100 * S["ss"] / S["ss"].sum(); S = S.drop(columns="ss")
print(S.round(2).to_string(index=False)); out["segments"] = S.round(3).to_dict("records")

# ---- 2. firm / drift frequency from open to the jump, and when the threshold was first crossed
ref = lp["t0"]
rows = []
for x in (0.10, 0.20, 0.30):
    for sign, name in ((+1, "firm"), (-1, "drift")):
        thr = np.log(1 / (1 - x)) if sign > 0 else np.log(1 + x)                      # firm: price down by x (q <= (1-x) open); drift: price up by x
        mv = (lp["open"] - lp["t0"]) * sign
        has = (lp["open"].notna() & lp["t0"].notna())
        hit = has & (mv >= (np.log(1 / (1 - x)) if sign > 0 else np.log(1 + x)))
        r = dict(move=f"{name} {int(x*100)}%+", share_of_runners_pct=100 * hit.sum() / has.sum(), n=int(hit.sum()))
        for g in GRID[1:]:                                                              # first grid time at which cumulative move crosses the threshold
            cum = (lp["open"] - lp[g]) * sign
            r[f"crossed_by_{LAB[g]}_pct"] = 100 * ((cum >= (np.log(1 / (1 - x)) if sign > 0 else np.log(1 + x))) & hit).sum() / max(hit.sum(), 1)
        rows.append(r)
F = pd.DataFrame(rows); print(F.round(1).to_string(index=False)); out["firm_drift"] = F.round(2).to_dict("records")

# ---- 3. by price band (Sportsbet price at -10)
band = pd.cut(d["sb_t10"], [1, 3, 6, 10, 20, 1000], labels=["<=3", "3-6", "6-10", "10-20", "20+"])
rows = []
for bnd, g in d.groupby(band, observed=True):
    mO = (lp["open"] - lp["t0"]).loc[g.index].dropna()
    late = (lp["t15"] - lp["t0"]).loc[g.index].dropna()
    rows.append(dict(band=str(bnd), n=len(g), firm10_pct=100 * (mO >= np.log(1 / 0.9)).mean(), firm20_pct=100 * (mO >= np.log(1 / 0.8)).mean(),
                     drift10_pct=100 * (mO <= -np.log(1.1)).mean(), median_abs_open_to_jump_pct=100 * (np.exp(mO.abs()) - 1).median(),
                     late_firm10_last15_pct=100 * (late >= np.log(1 / 0.9)).mean(), late_drift10_last15_pct=100 * (late <= -np.log(1.1)).mean()))
B = pd.DataFrame(rows); print(B.round(1).to_string(index=False)); out["by_band"] = B.round(2).to_dict("records")

# ---- 4. information arrival: win-probability sharpness of the margin-free market at each time (same races, starters)
race = d["race_id"]; ok = pd.Series(True, index=d.index)
mm = {}
for g in GRID[1:]:
    ms = []
    for b in ("sb", "lb"):
        q = d[col(b, g)]; inv = 1 / q
        ok &= q.notna().groupby(race).transform("all")
        ms.append(inv / inv.groupby(race).transform("sum"))
    m = (ms[0] + ms[1]) / 2; mm[g] = m / m.groupby(race).transform("sum")
inv = 1 / d["sp"]; ok &= d["sp"].notna().groupby(race).transform("all")
mm["SP"] = inv / inv.groupby(race).transform("sum")
dd = d[ok]; days = dd["day"].to_numpy(); w = dd["won"].to_numpy()
rows = []; base = None
for g in list(mm):
    m = mm[g][ok].to_numpy()
    ll = np.where(w, -np.log(m), 0.0); mw = np.where(w, m, 0.0)
    est, ci = L.day_bootstrap(days, np.c_[ll, mw, w], lambda s: s[0] / s[2], n=500)
    rows.append(dict(time=LAB.get(g, g), logloss=est, ci_lo=ci[0], ci_hi=ci[1], mean_win_chance_of_winners=(mw.sum() / w.sum())))
I = pd.DataFrame(rows)
base = I.loc[I["time"] == "-120", "logloss"].iloc[0]
I["gain_vs_-120_millinats"] = 1000 * (base - I["logloss"])
print(f"common sample: {dd['race_id'].nunique()} races\n" + I.round(4).to_string(index=False)); out["info"] = I.round(5).to_dict("records")
out["n_races_info"] = int(dd["race_id"].nunique())
json.dump(out, open(f"{L.LM}/out/describe.json", "w"), indent=1)
