"""Development-block (out-of-fold, 2024-01 to 2025-12) results of the frozen rules and the benchmark, for the table beside the test result."""
import json, os, pickle, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lm_lib as L, bets as B
OUT = f"{L.LM}/out"; R = json.load(open(f"{OUT}/frozen.json"))["rules"]
exo = B.parse_exo(pickle.load(open(f"{L.LM}/extras/extras.pkl", "rb"))["exo"])
O = {T: pd.read_pickle(f"{OUT}/oof_T{T}.pkl") for T in (10, 5, 2)}
days = {T: sorted(O[T]["day"].unique()) for T in O}
S = lambda b, T: B.summarise(b, days[T], n_boot=1000)
res = {}
r = R["win"]; T = r["T"]
res["win"] = dict(frozen=S(B.win_rule(O[T], r["model"], r["edge"], r["pmin"]), T), without_move=S(B.win_rule(O[T], "p0", r["edge"], r["pmin"]), T), benchmark=S(B.win_rule(O[T], "p_raw", 0.05, 0.0, topk=4), T))
for kind in ("place", "ew"):
    r = R[kind]; T = r["T"]
    for m in ("p_MS", "p_raw"):
        P, k = B.place_chances(O[T], m); O[T]["plc_" + m] = P
    O[T]["plc_k"] = k
    res[kind] = dict(frozen=S(B.place_rule(O[T], r["model"], r["edge"], r["pmin"], mode=kind), T), benchmark=S(B.place_rule(O[T], "p_raw", 0.0, 0.0, topk=4, mode=kind), T))
bench = dict(quinella=("quin3", 0.0), exacta=("exa2", 0.0), trifecta=("tri4", 0.20))
for pool in bench:
    r = R[pool]; T = r["T"]
    tab = B.exotic_table(O[T], r["model"]); tr = B.exotic_table(O[T], "p_raw")
    res[pool] = dict(frozen=S(B.exotic_settle(tab, r["kind"], r["thr"], exo), T), benchmark=S(B.exotic_settle(tr, *bench[pool], exo), T))
json.dump(res, open(f"{OUT}/dev_rules.json", "w"), indent=1, default=float)
for k, v in res.items():
    print(k, {a: {x: (round(y, 3) if isinstance(y, float) else y) for x, y in b.items() if x in ("bets", "strike", "roi", "roi_lo", "roi_hi", "per_day")} for a, b in v.items()})
