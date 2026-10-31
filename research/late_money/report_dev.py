"""Step 3 report (development only, out-of-fold): log-loss gains with day-bootstrap intervals, calibration of firmers vs drifters,
the move coefficients, and the staying-race slice. Reads oof_T*.pkl (2024-01 to 2025-12) and fits on development data only."""
import json, os, sys
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lm_lib as L, lm_model as M

OUT = f"{L.LM}/out"; res = {}


def gains(O, a, b, mask=None, n=2000):
    """mean per-race log-loss gain (millinats) of column b over column a, day bootstrap."""
    O = O if mask is None else O[mask]
    w = O["won"].to_numpy()
    la = -np.log(O[a].to_numpy()[w]); lb = -np.log(O[b].to_numpy()[w])
    days = O["day"].to_numpy()[w]
    est, ci = L.day_bootstrap(days, np.c_[la - lb, np.ones(len(la))], lambda s: 1000 * s[0] / s[1], n=n)
    return dict(gain_mn=float(est), lo=float(ci[0]), hi=float(ci[1]), races=int(w.sum()))


def ae(O, col, mask, n=1000):
    """actual wins / expected wins (sum of the column) in the mask, day bootstrap."""
    o = O[mask]
    est, ci = L.day_bootstrap(o["day"].to_numpy(), np.c_[o["won"].to_numpy().astype(float), o[col].to_numpy()], lambda s: s[0] / s[1], n=n)
    return float(est), [float(ci[0]), float(ci[1])], int(o["won"].sum()), float(o[col].sum())


for T in (10, 5, 2):
    O = pd.read_pickle(f"{OUT}/oof_T{T}.pkl"); r = {}
    for a, b in (("p_raw", "p0"), ("p0", "p_MS"), ("p0", "p_ALL"), ("p_raw", "p_MS")):
        r[f"{b}_over_{a}"] = gains(O, a, b)
    stay = O["distance_m"] >= 2000
    r["staying_p_MS_over_p0"] = gains(O, "p0", "p_MS", stay)
    r["non_staying_p_MS_over_p0"] = gains(O, "p0", "p_MS", ~stay)
    # firmers vs drifters: open -> T (raw mean-of-books log move), and the last 15 minutes
    mO, m15 = O["mO"], O["m15"]
    groups = {"firm >=20% (open to T)": mO >= np.log(1 / 0.8), "firm 10-20%": (mO >= np.log(1 / 0.9)) & (mO < np.log(1 / 0.8)),
              "steady (within 10%)": (mO > -np.log(1.1)) & (mO < np.log(1 / 0.9)), "drift 10-25%": (mO <= -np.log(1.1)) & (mO > -np.log(1.25)),
              "drift >25%": mO <= -np.log(1.25),
              "firm >=10% in last 15 min": m15 >= np.log(1 / 0.9), "drift >=10% in last 15 min": m15 <= -np.log(1.1)}
    cal = []
    for g, mask in groups.items():
        mask = mask.fillna(False)
        row = dict(group=g, runners=int(mask.sum()))
        for c in ("p_raw", "p0", "p_MS"):
            e, ci, wins, exp = ae(O, c, mask); row[f"AE_{c}"] = e; row[f"AE_{c}_lo"] = ci[0]; row[f"AE_{c}_hi"] = ci[1]
        row["wins"] = wins
        cal.append(row)
    r["calibration"] = cal
    res[f"T{T}"] = r
    print(f"T-{T}: races {O['race_id'].nunique()}, days {O['day'].nunique()}")
    for k in ("p0_over_p_raw", "p_MS_over_p0", "p_ALL_over_p0", "p_MS_over_p_raw", "staying_p_MS_over_p0", "non_staying_p_MS_over_p0"):
        x = r[k]; print(f"  {k:26s} {x['gain_mn']:+.3f} mn [{x['lo']:+.3f}, {x['hi']:+.3f}]  races {x['races']}")
    for c in cal:
        print(f"  {c['group']:28s} n={c['runners']:6d} wins={c['wins']:5d}  A/E raw {c['AE_p_raw']:.3f} [{c['AE_p_raw_lo']:.2f},{c['AE_p_raw_hi']:.2f}]  p0 {c['AE_p0']:.3f}  MS {c['AE_p_MS']:.3f} [{c['AE_p_MS_lo']:.2f},{c['AE_p_MS_hi']:.2f}]")
    # move coefficients: fit MOVE+SPREAD on all development data at the screened lambda
    sc = json.load(open(f"{OUT}/screen_T{T}.json"))["model_MS"]
    d = M.load_T(T, L.DEV_START, L.DEV_END); spec = M.Spec(["MOVE", "SPREAD"]); m = spec.fit(d, sc["lam"])
    names = [c for f in spec.fams for c, _ in M.FAMS[f]]
    names = [x for f in spec.fams for x in [c for c, _ in M.FAMS[f]] + [f + "_missing"]]
    r["move_coefs_per_sd"] = dict(zip(names, [round(float(x), 4) for x in m["w"]])); r["alpha"] = float(m["alpha"]); r["lam"] = sc["lam"]
    print("  coefs", r["move_coefs_per_sd"], "alpha", round(m["alpha"], 4))
json.dump(res, open(f"{OUT}/report_dev.json", "w"), indent=1)
