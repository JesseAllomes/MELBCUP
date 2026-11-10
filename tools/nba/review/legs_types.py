"""Q1/Q2: leg types offered, picked, calibration gap and ROI, game-cluster bootstrap + BH FDR.
Usage: python3 -I tools/nba/review/legs_types.py forward-v2.jsonl"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collections import defaultdict
from common import *

legs, multis = load(sys.argv[1])
S = settled_legs(legs)
role = roles(legs)
picked = defaultdict(int)
for m in multis:
    for d in m["detail"]:
        picked[(gid(d), d["label"], d.get("agency") or m["agency"])] += 1
P = [r for r in S if lkey(r) in picked]
print(f"settled legs {len(S)} in {len({gid(r) for r in S})} games; unique settled picked legs {len(P)}"
      f" in {len({gid(r) for r in P})} games; days {sorted({r['day'] for r in S})}")

DIMS = {
    "side": side, "type": ltype, "stat": lambda r: r["stat"][:6], "price": lambda r: pband(r["price"]),
    "chance": lambda r: cband(r["chance"]), "agency": lambda r: r["agency"], "role": role,
    "side/type": lambda r: f"{side(r)}/{ltype(r)}",
    "side/type/stat": lambda r: f"{side(r)}/{ltype(r)}/{r['stat'][:6]}",
    "side/type/price": lambda r: f"{side(r)}/{ltype(r)}/{pband(r['price'])}",
    "side/type/agency": lambda r: f"{side(r)}/{ltype(r)}/{r['agency']}",
    "side/type/role": lambda r: f"{side(r)}/{ltype(r)}/{role(r)}",
    "side/stat/role": lambda r: f"{side(r)}/{r['stat'][:6]}/{role(r)}",
}


def table(title, rows, minn=40):
    out = []
    for dim, f in DIMS.items():
        g = defaultdict(list)
        for r in rows:
            g[f(r)].append(r)
        for k, v in g.items():
            if len(v) >= minn:
                s = stats(v); s["name"] = f"{dim}={k}"; s["dim"] = dim
                out.append(s)
    bh(out)
    print(f"\n== {title}: {len(out)} cells tested, * = survives BH FDR 10% ==\n{HEAD}")
    last = None
    for s in out:
        if s["dim"] != last:
            last = s["dim"]; print(f"-- {last}")
        print(line(s["name"].split("=", 1)[1], s))
    return out


A = table("ALL OFFERED LEGS", S, 150)
Pt = table("PICKED LEGS (unique, any multi)", P, 25)

print("\n== Offer share: picked-leg instances vs the pool ==")
tot = sum(picked[lkey(r)] for r in P)
for dim in ("side/type", "side/type/price", "side/type/stat", "side/type/role", "agency"):
    f = DIMS[dim]; pool = defaultdict(int); inst = defaultdict(int); uniq = defaultdict(int)
    for r in S:
        pool[f(r)] += 1
    for r in P:
        inst[f(r)] += picked[lkey(r)]; uniq[f(r)] += 1
    print(f"-- {dim}: cell, % of pool, % of unique picked, % of picked instances, picks per pool leg")
    for k in sorted(pool, key=lambda k: -inst[k]):
        print(f"{k:30}{100*pool[k]/len(S):6.1f}{100*uniq[k]/max(len(P),1):7.1f}{100*inst[k]/max(tot,1):7.1f}{inst[k]/pool[k]:7.2f}")

print("\n== Winner's curse: same type, picked vs never picked (chance >= .5 pool) ==\n" + HEAD)
for name, sel in (("over/rung", lambda r: side(r) == "over" and ltype(r) == "rung"),
                  ("over/ou", lambda r: side(r) == "over" and ltype(r) == "ou"),
                  ("under/ou", lambda r: side(r) == "under")):
    for tag, pk in (("picked", True), ("not picked", False)):
        v = [r for r in S if sel(r) and r["chance"] >= 0.5 and (lkey(r) in picked) == pk]
        if v:
            print(line(f"{name} {tag}", stats(v)))
