"""Q1/Q3: multi-level calibration and failure attribution.
Every group gets: said (logged chance), product of leg chances, got, Wilson interval, and a p-value
from a parametric null that respects the overlap between multis: each distinct bet is drawn once per
simulation with its logged chance (legs independent, as the picker assumes across players) and every
multi that holds it shares the draw. p = share of simulations with as few (or as many) wins.
Usage: python3 -I tools/nba/review/multis.py forward-v2.jsonl"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import random
from collections import defaultdict, Counter
from common import *

NSIM = 3000
legs, multis = load(sys.argv[1])
role = roles(legs)
M = [m for m in multis if m["result"] in ("won", "lost")]
bk = lambda d: (gid(d), d["player"], d["stat"], d["line"], bool(d["under"]))
for m in M:
    m["L"] = [d for d in m["detail"] if d.get("result") in ("won", "lost")]
    m["prod"] = 1.0
    for d in m["L"]:
        m["prod"] *= d["chance"]
    u = sum(1 for d in m["L"] if d["under"])
    m["comp"] = "overs only" if u == 0 else "unders only" if u == len(m["L"]) else "mixed"
    m["nu"] = u
bets = sorted({bk(d) for m in M for d in m["L"]})
idx = {b: i for i, b in enumerate(bets)}
rng = random.Random(SEED)
U = [[rng.random() for _ in bets] for _ in range(NSIM)]
print(f"settled multis {len(M)} over {len(bets)} distinct bets, {len({b[0] for b in bets})} games, "
      f"days {sorted({m['day'] for m in M})}")


def simwins(ms, shift=0.0):
    """Wins per simulation for the multis `ms` (leg chance + shift, clipped)."""
    spec = [[(idx[bk(d)], min(max(d["chance"] + shift, 0.0), 1.0)) for d in m["L"]] for m in ms]
    out = []
    for u in U:
        out.append(sum(1 for legs_ in spec if all(u[i] < c for i, c in legs_)))
    return out


def row(name, ms):
    n = len(ms)
    if n < 8:
        return
    k = sum(m["result"] == "won" for m in ms)
    said = sum(m["chance"] for m in ms) / n; prod = sum(m["prod"] for m in ms) / n
    lo, hi = wilson(k, n)
    sw = simwins(ms)
    exp = sum(sw) / NSIM / n
    pl = sum(1 for x in sw if x <= k) / NSIM; ph = sum(1 for x in sw if x >= k) / NSIM
    sw.sort()
    print(f"{name[:30]:30}{n:5}{said:7.3f}{prod:7.3f}{k/n:7.3f} [{lo:.3f},{hi:.3f}]"
          f"  null95 [{sw[int(.025*NSIM)]/n:.3f},{sw[int(.975*NSIM)]/n:.3f}] p_low={pl:.3f} p_high={ph:.3f}"
          f"  ret/$ {sum((m['price'] if m['result']=='won' else 0)-1 for m in ms)/n:+.2f}")


H = f"{'group':30}{'n':>5}{'said':>7}{'prod':>7}{'got':>7} Wilson95 (naive)   null interval for got, p-values, return per $1"
def table(title, keyf, sel=lambda m: True):
    print(f"\n== {title} ==\n{H}")
    g = defaultdict(list)
    for m in M:
        if sel(m):
            g[keyf(m)].append(m)
    for k in sorted(g, key=str):
        row(str(k), g[k])

table("all", lambda m: "all")
table("by mkind", lambda m: m["mkind"])
table("by mkind x target", lambda m: (m["mkind"], m["target"]))
table("by mkind x legs", lambda m: (m["mkind"], len(m["L"])))
table("by mkind x composition", lambda m: (m["mkind"], m["comp"]))
table("by mkind x number of unders", lambda m: (m["mkind"], f"{m['nu']} unders"))
table("by agency x mkind", lambda m: (m["agency"], m["mkind"]))
table("by day (all kinds)", lambda m: m["day"])
table("by day x composition (stacks + stacks_same)", lambda m: (m["day"], m["comp"]), lambda m: m["mkind"] != "by_game")
table("said band (stacks + stacks_same)", lambda m: cband(m["chance"]), lambda m: m["mkind"] != "by_game")

# ---- failure attribution -------------------------------------------------------------------
print("\n== Failure attribution (leg instances inside settled multis; by_game excluded = the picker's stacks) ==")
print("type: instances, share of instances, said, got, failed, expected failed (sum 1-chance), excess,"
      " sole-killer count (the only failed leg of a lost multi), expected sole killers under the null, null 95%")
T = {"side/type": lambda d: f"{side(d)}/{ltype(d)}",
     "side/stat": lambda d: f"{side(d)}/{d['stat'][:6]}",
     "side/price": lambda d: f"{side(d)}/{pband(d['price'])}",
     "side/role": lambda d: f"{side(d)}/{role(d)}",
     "side/mkind": None}
MS = [m for m in M if m["mkind"] != "by_game"]
for dim, f in T.items():
    print(f"-- {dim}")
    inst = defaultdict(lambda: [0, 0.0, 0, 0])
    sim_sole = defaultdict(lambda: [0] * NSIM)
    for m in MS:
        ff = f or (lambda d, m=m: f"{side(d)}/{m['mkind']}")
        fails = [d for d in m["L"] if d["result"] == "lost"]
        for d in m["L"]:
            a = inst[ff(d)]; a[0] += 1; a[1] += d["chance"]; a[2] += d["result"] == "lost"
        if len(fails) == 1:
            inst[ff(fails[0])][3] += 1
        spec = [(idx[bk(d)], d["chance"], ff(d)) for d in m["L"]]
        for s, u in enumerate(U[:1000]):
            bad = [t for i, c, t in spec if u[i] >= c]
            if len(bad) == 1:
                sim_sole[bad[0]][s] += 1
    tot = sum(a[0] for a in inst.values())
    for k in sorted(inst, key=lambda k: -inst[k][0]):
        n, s, fl, sole = inst[k]
        ss = sorted(sim_sole[k][:1000])
        print(f"{k:26}{n:5}{100*n/tot:6.1f}% said {s/n:.3f} got {1-fl/n:.3f} failed {fl:4} exp {n-s:6.1f}"
              f" excess {fl-(n-s):+6.1f} | sole killer {sole:3} exp {sum(ss)/1000:5.1f} [{ss[25]},{ss[974]}]")

print("\n== Lost multis: how many legs failed, and what failed ==")
c = Counter(); who = Counter()
for m in MS:
    if m["result"] == "lost":
        fl = [d for d in m["L"] if d["result"] == "lost"]
        c[min(len(fl), 3)] += 1
        kinds = {side(d) for d in fl}
        who["only unders failed" if kinds == {"under"} else "only overs failed" if kinds == {"over"} else "both"] += 1
print("failed legs per lost multi (3 = 3+):", dict(sorted(c.items())), "|", dict(who))
print("unique picked bets:", len(bets), "| instances per unique bet, top 10:",
      Counter(Counter(bk(d) for m in MS for d in m["L"]).values()).most_common(10))
# how concentrated: the bets that killed most multis
kill = Counter(); labels = {}
for m in MS:
    for d in m["L"]:
        labels[bk(d)] = (side(d), ltype(d), d["stat"][:6], pband(d["price"]), round(d["chance"], 2))
        if d["result"] == "lost":
            kill[bk(d)] += 1
tk = sum(kill.values())
print(f"failed leg instances {tk}; the 10 most repeated failing bets carry {sum(v for _k, v in kill.most_common(10))}"
      f" ({100*sum(v for _k, v in kill.most_common(10))/tk:.0f}%):")
for b, v in kill.most_common(10):
    print("  ", v, labels[b])
