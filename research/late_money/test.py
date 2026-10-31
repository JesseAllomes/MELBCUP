"""Step 4c: THE ONE TEST. tune2 (2026-01-01 to 2026-04-30) is read here and nowhere else. Guards: (1) RERUN.md must already contain the sha256
of frozen.json; (2) a flag file makes a second run refuse. Nothing is fitted or tuned here: frozen models and rules are applied as they are."""
import hashlib, json, os, pickle, sys
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lm_lib as L, lm_model as M, bets as B

OUT = f"{L.LM}/out"; FLAG = f"{OUT}/TEST_RUN_DONE"
DRY = os.environ.get("LM_DRY") == "1"          # code check on the last development quarter (already used for tuning); never on tune2
if DRY:
    L.TEST_START, L.TEST_END = "2025-10-01", "2025-12-31"; FLAG = f"{OUT}/DRY_FLAG"
frozen_path = f"{OUT}/frozen.json"
h = hashlib.sha256(open(frozen_path, "rb").read()).hexdigest()
_rp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "RERUN.md")
report = open(_rp).read() if os.path.exists(_rp) else ""
if not DRY and h not in report:
    sys.exit("refusing: RERUN.md does not record the frozen rule's sha256 yet")
if os.path.exists(FLAG) and not DRY:
    sys.exit("refusing: the test block was already run once")
open(FLAG, "w").write(h)
F = json.load(open(frozen_path)); R = F["rules"]
exo = B.parse_exo(pickle.load(open(f"{L.LM}/extras/extras.pkl", "rb"))["exo"])
res = {"frozen_sha256": h}
data = {}


def frame(T):
    """test-block runners at T with every chance column: p_raw (consensus), p0 (alpha-corrected consensus), p_MS / p_ALL (frozen models)."""
    if T in data:
        return data[T]
    d = M.load_T(T, L.TEST_START, L.TEST_END)
    rc = L.Races(d["race_id"], d["won"], d["logM"])
    d["p_raw"] = d["M"]
    for name in ("p_MS", "p_ALL"):
        k = f"T{T}_{name}"
        if k in F["models"]:
            spec, m = M.load_model(F["models"][k])
            d[name] = rc.probs(spec.eta(m, d))
            d["p0"] = rc.probs(m["alpha"] * d["logM"].to_numpy())
    d["day"] = d["day"].astype(str)
    data[T] = d
    return d


def days(T):
    return sorted(frame(T)["day"].unique())


def S(b, T, extra=None):
    r = B.summarise(b, days(T)); r["races_days"] = len(days(T)); r["races"] = int(frame(T)["race_id"].nunique())
    return r


# ---- model gains on the test block (log-loss, millinats per race, day bootstrap)
def gain(O, a, b):
    w = O["won"].to_numpy()
    la = -np.log(O[a].to_numpy()[w]); lb = -np.log(O[b].to_numpy()[w])
    est, ci = L.day_bootstrap(O["day"].to_numpy()[w], np.c_[la - lb, np.ones(len(la))], lambda s: 1000 * s[0] / s[1], n=2000)
    return dict(gain_mn=float(est), lo=float(ci[0]), hi=float(ci[1]), races=int(w.sum()))


res["model_gain"] = {}
for T in (10, 5, 2):
    O = frame(T)
    res["model_gain"][f"T{T}"] = {"p0_over_raw": gain(O, "p_raw", "p0"), "p_MS_over_p0": gain(O, "p0", "p_MS"), "p_MS_over_raw": gain(O, "p_raw", "p_MS"),
                                 "staying_p_MS_over_p0": gain(O[O["distance_m"] >= 2000], "p0", "p_MS")}
    mO = O["mO"]
    cal = []
    for g, mask in {"firm >=10% (open to T)": mO >= np.log(1 / 0.9), "steady": (mO > -np.log(1.1)) & (mO < np.log(1 / 0.9)), "drift >=10%": mO <= -np.log(1.1),
                    "drift >=10% in last 15 min": O["m15"] <= -np.log(1.1)}.items():
        mask = mask.fillna(False); o = O[mask]
        row = dict(group=g, runners=int(mask.sum()), wins=int(o["won"].sum()))
        for c in ("p_raw", "p0", "p_MS"):
            est, ci = L.day_bootstrap(o["day"].to_numpy(), np.c_[o["won"].astype(float).to_numpy(), o[c].to_numpy()], lambda s: s[0] / s[1], n=1000)
            row[f"AE_{c}"] = float(est); row[f"AE_{c}_ci"] = [float(ci[0]), float(ci[1])]
        cal.append(row)
    res["model_gain"][f"T{T}"]["calibration"] = cal

# ---- WIN (frozen vs benchmark = the current agreed rule, same T)
r = R["win"]; T = r["T"]; O = frame(T)
wb = B.win_rule(O, r["model"], r["edge"], r["pmin"]); wb_p0 = B.win_rule(O, "p0", r["edge"], r["pmin"])
wbench = B.win_rule(O, "p_raw", 0.05, 0.0, topk=4)
res["win"] = dict(rule=r, frozen=S(wb, T), same_rule_without_move_features=S(wb_p0, T), benchmark_current_rule=S(wbench, T),
                  frozen_staying=S(wb[wb["distance_m"] >= 2000], T), benchmark_staying=S(wbench[wbench["distance_m"] >= 2000], T),
                  frozen_bets=wb[["race_id", "day", "entry_no", "q_sb", "won"]].assign(p=wb[r["model"]]).to_dict("records"))
# a looser reading of the same rule, descriptive only (not the frozen rule): edge 0, any chance
res["win"]["descriptive_edge0_pmin0"] = S(B.win_rule(O, r["model"], 0.0, 0.0), T)
# at the other times, same thresholds (descriptive)
res["win"]["descriptive_other_T"] = {f"T{t}": S(B.win_rule(frame(t), "p_MS", r["edge"], r["pmin"]), t) for t in (10, 5)}

# ---- MULTIS: doubles of consecutive-leg frozen win bets (legs at their own T: an upper bound, not executable as stated)
res["multi"] = dict(frozen=S(B.doubles(wb, None), T), benchmark=S(B.doubles(wbench, None), T))

# ---- PLACE and EACH-WAY (T-2, stored last Sportsbet place price)
for kind in ("place", "ew"):
    r = R[kind]; T = r["T"]; O = frame(T)
    for m in ("p_MS", "p_raw"):
        P, k = B.place_chances(O, m); O["plc_" + m] = P
    O["plc_k"] = k
    fb = B.place_rule(O, r["model"], r["edge"], r["pmin"], mode=kind)
    bb = B.place_rule(O, "p_raw", 0.0, 0.0, topk=4, mode=kind)
    res[kind] = dict(rule=r, frozen=S(fb, T), benchmark_current_rule=S(bb, T), frozen_staying=S(fb[fb["distance_m"] >= 2000], T), benchmark_staying=S(bb[bb["distance_m"] >= 2000], T))

# ---- EXOTICS
bench = dict(quinella=("quin3", 0.0), exacta=("exa2", 0.0), trifecta=("tri4", 0.20))
for pool in ("quinella", "exacta", "trifecta"):
    r = R[pool]; T = r["T"]; O = frame(T)
    tab = B.exotic_table(O, r["model"]); tab_raw = B.exotic_table(O, "p_raw")
    fb = B.exotic_settle(tab, r["kind"], r["thr"], exo); bk, bt = bench[pool]; bb = B.exotic_settle(tab_raw, bk, bt, exo)
    res[pool] = dict(rule=r, frozen=S(fb, T), benchmark_current_rule=dict(kind=bk, thr=bt, **S(bb, T)),
                     races_with_stored_dividend=int(sum(1 for rid in O["race_id"].unique() if exo.get((rid, B.POOL[r["kind"]])))))
res["first_four"] = dict(rule=None, races_with_stored_dividend=int(sum(1 for rid in frame(2)["race_id"].unique() if exo.get((rid, "First Four")))))

# ---- Cups in the block, and staying races, side view
O = frame(2)
res["cups_in_test_block"] = int(O["race_name"].astype(str).str.fullmatch(r"(?i)(lexus )?melbourne cup").groupby(O["race_id"]).any().sum())
res["test_block"] = dict(races_T2=int(O["race_id"].nunique()), days_T2=len(days(2)), staying_races_T2=int(O[O["distance_m"] >= 2000]["race_id"].nunique()))
json.dump(res, open(f"{OUT}/test_result{'_dry' if DRY else ''}.json", "w"), indent=1, default=float)
print(json.dumps({k: v for k, v in res.items() if k not in ("model_gain",)}, indent=1, default=float)[:6000])
print(json.dumps(res["model_gain"], indent=1, default=float)[:5000])
