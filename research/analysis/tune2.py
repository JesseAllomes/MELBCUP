"""The ONE tune2 look (protocol v1): pinned model-v1, unchanged; 98.33% race-day bootstrap intervals."""
import json, os
import evaluate as E
import screen as S
out = f"{S.RESULTS}/tune2_result.json"
assert not os.path.exists(out), "tune2 has already been looked at once"
m = json.load(open(f"{S.RESULTS}/model-v1.json"))
d = E.load_u(["tune2"])
P, Ma, Mr = E.predict(m, d)
res = E.claims(d, P, Ma, Mr, 0.9833)
json.dump(res, open(out, "w"), indent=1, default=float)
print(json.dumps(res, indent=1, default=float))
