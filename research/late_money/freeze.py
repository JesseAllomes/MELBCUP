"""Step 4b: fit the chosen chance models on ALL development data (2023-01-01 to 2025-12-31) and write frozen.json (rules + model coefficients).
Reads only development blocks. After this, nothing is tuned: RERUN.md records frozen.json's sha256 before test.py is allowed to run."""
import hashlib, json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lm_lib as L, lm_model as M

C = json.load(open(f"{L.LM}/out/candidates.json"))
screen = {T: json.load(open(f"{L.LM}/out/screen_T{T}.json")) for T in (10, 5, 2)}
need = set()
rules = {}
for k in ("win", "place", "ew"):
    c = C[k]; rules[k] = dict(T=int(c["T"]), model=c["model"], edge=c["edge"], pmin=c["pmin"]); need.add((int(c["T"]), c["model"]))
for k in ("quinella", "exacta", "trifecta"):
    c = C[k]; rules[k] = dict(T=int(c["T"]), model=c["model"], kind=c["kind"], thr=c["thr"]); need.add((int(c["T"]), c["model"]))
rules["first_four"] = None
for T in (10, 5, 2):
    need.add((T, "p_MS"))      # the move model at every T, for the test-block log-loss gain
models = {}
for T, name in sorted(need):
    fams = screen[T][f"model_{name[2:]}"]["fams"]; lam = screen[T][f"model_{name[2:]}"]["lam"]
    d = M.load_T(T, L.DEV_START, L.DEV_END)
    spec = M.Spec(fams); m = spec.fit(d, lam)
    models[f"T{T}_{name}"] = M.dump_model(m, fams, lam)
    names = []
    print(f"T-{T} {name}: fams {fams} lam {lam} alpha {m['alpha']:.4f}; trained on {d['race_id'].nunique()} races", flush=True)
out = dict(blocks=dict(develop=[L.DEV_START, L.DEV_END], test=[L.TEST_START, L.TEST_END]), rules=rules, models=models)
p = f"{L.LM}/out/frozen.json"
open(p, "w").write(json.dumps(out, indent=1, sort_keys=True))
print("sha256", hashlib.sha256(open(p, "rb").read()).hexdigest())
print(json.dumps(rules, indent=1))
