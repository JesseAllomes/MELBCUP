"""Unders vs overs: said (app chance) vs got, by band and stat, on forward-v2.jsonl. Token-free.
Usage: python3 tools/nba/unders_report.py forward-v2.jsonl (owner question 2026-11-10)."""
import json, sys, math
from collections import defaultdict
rows = [json.loads(l) for l in open(sys.argv[1])]
seen, legs = set(), []
for r in rows:
    if r.get("kind") != "leg" or r.get("result") not in ("won", "lost") or not r.get("chance"):
        continue
    key = (r.get("espn_event") or r.get("event"), r.get("label"), r.get("agency"))
    if key in seen: continue
    seen.add(key); legs.append(r)
print("settled legs (deduped):", len(legs), "days", len({r['day'] for r in legs}))
def rep(title, sel, keyf):
    g = defaultdict(list)
    for r in sel: g[keyf(r)].append(r)
    print(f"\n{title}")
    print(f"{'group':26}{'n':>6}{'said':>7}{'got':>7}{'gap':>7}{'±95%':>7}{'ret/$1':>8}")
    for k in sorted(g, key=str):
        v = g[k]; n = len(v)
        said = sum(r["chance"] for r in v)/n; got = sum(r["result"]=="won" for r in v)/n
        se = math.sqrt(max(said*(1-said),1e-9)/n)*1.96
        ret = sum((r["price"] if r["result"]=="won" else 0) - 1 for r in v)/n
        print(f"{str(k):26}{n:6}{said:7.3f}{got:7.3f}{got-said:+7.3f}{se:7.3f}{ret:+8.3f}")
band = lambda c: f"{int(c*10)/10:.1f}-{int(c*10)/10+0.1:.1f}"
rep("ALL legs: under vs over", legs, lambda r: "under" if r["under"] else "over")
rep("UNDERS by chance band", [r for r in legs if r["under"]], lambda r: band(r["chance"]))
rep("OVERS by chance band", [r for r in legs if not r["under"]], lambda r: band(r["chance"]))
rep("UNDERS by stat", [r for r in legs if r["under"]], lambda r: r["stat"])
rep("OVERS by stat", [r for r in legs if not r["under"]], lambda r: r["stat"])
# legs the app actually picked into multis
picked = {(r.get("espn_event") or r.get("event"), l) for r in rows if r.get("kind") != "leg" for l in (r.get("legs_labels") or [])}
print("\nmulti rows kinds:", sorted({r.get('kind') for r in rows}))
