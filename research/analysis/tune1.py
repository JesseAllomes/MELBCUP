"""Protocol v1 section 5 step 3 (tune1 refinement; development, 95% intervals) and the tune1 numbers for amendment A.
Rule fixed before running: (1) lambda re-chosen from the grid by tune1 log-loss with all train-kept families;
(2) backward elimination: repeatedly drop the family whose removal most lowers tune1 log-loss, until none does."""
import json
import numpy as np
import evaluate as E
import screen as S

sel = json.load(open(f"{S.RESULTS}/selection_train.json"))
d = E.load_u(["train", "tune1"])
tr, t1 = d[d["block"] == "train"].reset_index(drop=True), d[d["block"] == "tune1"].reset_index(drop=True)
t1s = E.train_rows(t1)
rc1 = S.Races(t1s)


def t1_ll(fams, lam):
    m = E.fit(tr, fams, lam)
    sc = {k: tuple(v) for k, v in m["scalers"].items()}
    X, _ = S.design(t1s, fams, sc)
    eta = m["alpha"] * rc1.logM + X @ np.array(m["w"])
    return rc1.logloss(eta), m


base = rc1.logloss(E.fit(tr, [], 0)["alpha"] * rc1.logM)
log = {"offset_only_ll": base, "lambda": {}, "elimination": []}
fams = sel["kept"]
for lam in S.LAMBDAS:
    log["lambda"][lam] = t1_ll(fams, lam)[0]
lam = min(log["lambda"], key=log["lambda"].get)
cur = log["lambda"][lam]
while len(fams) > 0:
    trial = {f: t1_ll([g for g in fams if g != f], lam)[0] for f in fams}
    f, v = min(trial.items(), key=lambda kv: kv[1])
    log["elimination"].append(dict(current=cur, best_drop=f, ll_after=v))
    if v < cur:
        fams = [g for g in fams if g != f]
        cur = v
    else:
        break
log["final_fams"], log["final_lambda"], log["final_ll"] = fams, lam, cur
m = E.fit(tr, fams, lam)
P, Ma, Mr = E.predict(m, t1)
log["tune1_claims_95"] = E.claims(t1, P, Ma, Mr, 0.95)
log["model_train_fit"] = m
json.dump(log, open(S.out_path("tune1_refine.json"), "w"), indent=1, default=float)
print(json.dumps({k: v for k, v in log.items() if k != "model_train_fit"}, indent=1, default=float))
