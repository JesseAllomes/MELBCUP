"""Robustness checks behind the two headline claims.
(1) Low-line ("bench") players: overs overstated, unders understated - by day, agency, line size.
(2) Mixed over/under stacks losing: how many distinct bets carry it (leave-one-bet-out).
(3) What a leg type is worth: P(multi) = (1/payout) x product of (1 + leg ROI), so the leg ROI per
    type is the whole story for "highest chance at the same payout".
Usage: python3 -I tools/nba/review/extras.py forward-v2.jsonl"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import math
from collections import defaultdict, Counter
from common import *

legs, multis = load(sys.argv[1])
S = settled_legs(legs)
role = roles(legs)

print("== (1) Points O/U by the size of the line (main line, both sides; gap = got - said) ==\n" + HEAD)
OU = [r for r in S if ltype(r) == "ou" and r["stat"] == "points"]
lb = lambda r: "line <=8.5" if r["line"] <= 9 else "line 9.5-13.5" if r["line"] <= 14 else "line 14.5-19.5" if r["line"] <= 20 else "line 20.5+"
for sd in ("over", "under"):
    g = defaultdict(list)
    for r in OU:
        if side(r) == sd:
            g[lb(r)].append(r)
    for k in sorted(g):
        print(line(f"points {sd} {k}", stats(g[k])))
print("-- bench (<12 median points) points unders by day and agency")
for k, f in (("day", lambda r: r["day"]), ("agency", lambda r: r["agency"])):
    g = defaultdict(list)
    for r in OU:
        if r["under"] and role(r) == "bench<12":
            g[f(r)].append(r)
    for kk in sorted(g):
        print(line(f"{k} {kk}", stats(g[kk])))
print("-- bench overs on rungs (the picker's main leg), by price band and by day")
g = defaultdict(list)
for r in S:
    if ltype(r) == "rung" and role(r) == "bench<12" and r["chance"] >= 0.5:
        g["price " + pband(r["price"])].append(r); g["day " + r["day"]].append(r); g["stat " + r["stat"][:6]].append(r)
for kk in sorted(g):
    print(line(f"bench over rung {kk}", stats(g[kk])))
print("-- same for stars and starters (control)")
for rl in ("star20+", "starter12-19"):
    print(line(f"{rl} over rung chance>=.5", stats([r for r in S if ltype(r) == "rung" and role(r) == rl and r["chance"] >= 0.5])))
print("-- how many distinct players sit behind 'bench': ",
      len({(r["player"]) for r in S if role(r) == "bench<12"}), "players;",
      len({(gid(r), r["player"]) for r in S if role(r) == "bench<12"}), "player-games")
# player-game clustered check: did the player go under his own points median?
pg = {}
for r in OU:
    if not r["under"]:
        k = (gid(r), r["player"])
        if k not in pg or abs(r["market"] - 0.5) < abs(pg[k]["market"] - 0.5):
            pg[k] = r
for rl in ("bench<12", "starter12-19", "star20+"):
    v = [r for r in pg.values() if role(r) == rl]
    k = sum(won(r) for r in v); lo, hi = wilson(k, len(v))
    print(f"   one main points line per player-game, {rl:13}: over won {k}/{len(v)} = {k/max(len(v),1):.3f} [{lo:.3f},{hi:.3f}]"
          f" vs market {sum(r['market'] for r in v)/max(len(v),1):.3f}")

print("\n== (2) Mixed stacks (exactly one under, cross-game): which bets lose them ==")
M = [m for m in multis if m["result"] in ("won", "lost") and m["mkind"] == "stacks"]
one = []
for m in M:
    L = [d for d in m["detail"] if d.get("result") in ("won", "lost")]
    if sum(d["under"] for d in L) == 1 and len(L) > 1:
        one.append((m, L))
print(f"multis {len(one)}: won {sum(m['result']=='won' for m, _ in one)}; days {dict(Counter(m['day'] for m, _ in one))}")
bk = lambda d: (gid(d), d["player"], d["stat"], d["line"], bool(d["under"]))
ub = Counter(bk(d) for m, L in one for d in L if d["under"]); ob = Counter(bk(d) for m, L in one for d in L if not d["under"])
print(f"distinct under bets {len(ub)} (instances {sum(ub.values())}), distinct over bets {len(ob)} (instances {sum(ob.values())})")
res = {}
for m, L in one:
    for d in L:
        res[bk(d)] = d["result"]
print("under bets: won", sum(res[b] == "won" for b in ub), "of", len(ub), "| over bets: won", sum(res[b] == "won" for b in ob), "of", len(ob))
killer = Counter()
for m, L in one:
    if m["result"] == "lost":
        f = [d for d in L if d["result"] == "lost"]
        killer["under only" if all(d["under"] for d in f) else "over only" if not any(d["under"] for d in f) else "both"] += 1
print("lost multis by what failed:", dict(killer))
print("leave-one-bet-out: wins/n after dropping every multi that holds the single most repeated losing bet:")
worst = Counter(bk(d) for m, L in one if m["result"] == "lost" for d in L if d["result"] == "lost").most_common(3)
for b, c in worst:
    rest = [(m, L) for m, L in one if all(bk(d) != b for d in L)]
    print(f"   drop bet in {c} lost multis ({'under' if b[4] else 'over'} {b[2][:6]}): {sum(m['result']=='won' for m,_ in rest)}/{len(rest)}"
          f" said {sum(m['chance'] for m,_ in rest)/max(len(rest),1):.3f}")

print("\n== (3) Leg ROI by type -> chance of a multi at a fixed payout T: P = (1/T) x prod(1+ROI_i) ==")
print("example T = $3: legs needed at the type's typical price, and the multi's chance if every leg has the type's ROI")
print(f"{'type':34}{'n':>6}{'ROI':>8} {'95%':>17}{'typ price':>10}{'legs for $3':>12}{'P($3 multi)':>12} {'range':>15}")
T = {"under O/U 1.5-2.2": lambda r: r["under"] and 1.5 <= r["price"] < 2.2,
     "over O/U 1.5-2.2": lambda r: ltype(r) == "ou" and not r["under"] and 1.5 <= r["price"] < 2.2,
     "over rung <1.15": lambda r: ltype(r) == "rung" and r["price"] < 1.15,
     "over rung 1.15-1.3": lambda r: ltype(r) == "rung" and 1.15 <= r["price"] < 1.3,
     "over rung 1.3-1.5": lambda r: ltype(r) == "rung" and 1.3 <= r["price"] < 1.5,
     "over rung 1.5-2.2": lambda r: ltype(r) == "rung" and 1.5 <= r["price"] < 2.2,
     "over rung 1.15-1.5 star/starter": lambda r: ltype(r) == "rung" and 1.15 <= r["price"] < 1.5 and role(r) != "bench<12",
     "over rung 1.15-1.5 bench": lambda r: ltype(r) == "rung" and 1.15 <= r["price"] < 1.5 and role(r) == "bench<12",
     "under O/U bench": lambda r: r["under"] and role(r) == "bench<12",
     "under O/U star/starter": lambda r: r["under"] and role(r) != "bench<12",
     "rung, book price beats consensus": None}
RM = ((1.3, 0.067), (2.2, 0.076), (3.0, 0.063))
for name, sel in T.items():
    if sel is None:
        v = [r for r in S if ltype(r) == "rung" and r["chance"] >= 0.45 and r["market"] - math.exp(-next((m for t, m in RM if r["price"] < t), 0.10)) / r["price"] > 0.02]
    else:
        v = [r for r in S if sel(r)]
    s = stats(v)
    gp = math.exp(sum(math.log(r["price"]) for r in v) / len(v))
    nl = math.log(3) / math.log(gp)
    p = lambda roi: (1 + roi) ** nl / 3
    print(f"{name:34}{s['n']:6}{s['roi']:+8.3f} [{s['rlo']:+.3f},{s['rhi']:+.3f}]{gp:10.2f}{nl:12.1f}{p(s['roi']):12.3f} [{p(s['rlo']):.3f},{p(s['rhi']):.3f}]")
