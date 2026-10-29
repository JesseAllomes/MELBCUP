"""Amendment A: pin model-v1 on train + tune1 (alpha, standardisers, shrinkage-free coefficients) with the refined families and lambda."""
import json, hashlib
import evaluate as E
import screen as S
r = json.load(open(f"{S.RESULTS}/tune1_refine.json"))
d = E.load_u(["train", "tune1"])
m = E.fit(d, r["final_fams"], r["final_lambda"])
m["fit_blocks"] = ["train", "tune1"]
m["decision_time"] = "T-30"
m["dataset_manifest_sha256"] = hashlib.sha256(open(f"{S.DATA}/manifest.json", "rb").read()).hexdigest()
json.dump(m, open(S.out_path("model-v1.json"), "w"), indent=1)
print(json.dumps({k: m[k] for k in ("alpha", "fams", "lam", "n_train_races")}), dict(zip(m["names"], [round(x, 4) for x in m["w"]])))
