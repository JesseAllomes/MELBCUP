"""Step 4a (development only): tune each bet type's rule on out-of-fold development predictions (2024-01 to 2025-12, inside train + tune1).
Writes $LM_DIR/out/tune_<type>.csv (full grid) and $LM_DIR/out/candidates.json. Does not read tune2 or final."""
import json, os, pickle, sys
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lm_lib as L, bets as B

OUT = f"{L.LM}/out"
EDGES = (0.02, 0.05, 0.08, 0.12, 0.20)
PMINS = (0.0, 0.05, 0.10, 0.15, 0.20, 0.30)
MIN_BETS = 25     # the rule fires rarely (see RERUN.md); 25 bets over two development years is the floor below which a rule is not considered at all
MODELS = ("p_MS", "p_ALL")
O = {T: pd.read_pickle(f"{OUT}/oof_T{T}.pkl") for T in (10, 5, 2)}
DAYS = {T: sorted(O[T]["day"].unique()) for T in O}
cand = {}


def pick(df, tie=0.1):
    """largest growth; differences under `tie` go to the larger edge, then the larger minimum chance (v2 proposal)."""
    df = df[df["bets"] >= MIN_BETS]
    if df.empty:
        return None
    top = df["G"].max()
    c = df[df["G"] >= top - tie].sort_values(["edge", "pmin"], ascending=False)
    return c.iloc[0].to_dict()


# ---------------- WIN
rows = []
for T in (10, 5, 2):
    for m in MODELS + ("p0",):
        for e in EDGES:
            for pm in PMINS:
                b = B.win_rule(O[T], m, e, pm)
                rows.append(dict(T=T, model=m, edge=e, pmin=pm, bets=len(b), G=B.growth(b), roi=(b["profit"].sum() / len(b)) if len(b) else np.nan, strike=b["won"].mean() if len(b) else np.nan))
W = pd.DataFrame(rows); W.to_csv(f"{OUT}/tune_win.csv", index=False)
cand["win"] = pick(W[W["model"].isin(MODELS)])
cand["win_p0_reference"] = pick(W[W["model"] == "p0"])
print("WIN grid best:", cand["win"], "\nWIN p0 reference:", cand["win_p0_reference"])
print(W[W["model"].isin(MODELS)].sort_values("G", ascending=False).head(8).round(4).to_string(index=False))

# ---------------- PLACE / EACH-WAY (T-2 only: the stored place price is the last one)
T = 2
for m in MODELS:
    P, k = B.place_chances(O[T], m); O[T]["plc_" + m] = P
O[T]["plc_k"] = k
rows = []
for mode in ("place", "ew"):
    for m in MODELS:
        for e in (0.0, 0.05, 0.10, 0.20):
            for pm in (0.0, 0.05, 0.10, 0.20, 0.30):
                b = B.place_rule(O[T], m, e, pm, mode=mode)
                rows.append(dict(mode=mode, T=T, model=m, edge=e, pmin=pm, bets=len(b), G=B.growth(b), roi=(b["profit"].sum() / len(b)) if len(b) else np.nan, strike=(b["profit"] > 0).mean() if len(b) else np.nan))
PL = pd.DataFrame(rows); PL.to_csv(f"{OUT}/tune_place.csv", index=False)
cand["place"] = pick(PL[PL["mode"] == "place"]); cand["ew"] = pick(PL[PL["mode"] == "ew"])
print("PLACE best:", cand["place"], "\nEW best:", cand["ew"])

# ---------------- EXOTICS (tote dividends as stored)
exo = B.parse_exo(pickle.load(open(f"{L.LM}/extras/extras.pkl", "rb"))["exo"])
rows = []
tabs = {}
for T in (10, 5, 2):
    for m in MODELS + ("p_raw",):
        tabs[(T, m)] = B.exotic_table(O[T], m)
        for kind in B.COMBOS:
            for h in (0.0, 0.05, 0.10, 0.20, 0.30, 0.50, 0.60, 0.70):
                b = B.exotic_settle(tabs[(T, m)], kind, h, exo)
                rows.append(dict(T=T, model=m, kind=kind, thr=h, bets=len(b), staked=b["stake"].sum() if len(b) else 0, roi=(b["profit"].sum() / b["stake"].sum()) if len(b) else np.nan,
                                 strike=b["won"].mean() if len(b) else np.nan, G=B.growth(b)))
X = pd.DataFrame(rows); X.to_csv(f"{OUT}/tune_exotics.csv", index=False)
for pool, kinds in (("quinella", ("quin2", "quin3", "quin4")), ("exacta", ("exa2", "exaBox3")), ("trifecta", ("tri3", "tri4")), ("first_four", ("ff4",))):
    x = X[X["model"].isin(MODELS) & X["kind"].isin(kinds) & (X["bets"] >= 50)]
    cand[pool] = x.sort_values("roi", ascending=False).iloc[0].to_dict() if len(x) else None      # exotics: best development ROI (cost-weighted), at least 50 bets
    print(pool.upper(), "best:", cand[pool])
json.dump(cand, open(f"{OUT}/candidates.json", "w"), indent=1, default=float)
