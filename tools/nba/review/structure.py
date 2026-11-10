"""Q3: structural checks. (a) same-game dependence between different players' legs, (b) alt-rung
margin table vs outcomes, (c) OVER_SHADE overall and by role, (d) staleness / price drift,
(e) ladder smoothing (market vs the leg's own price), (f) early vs latest log of the same bet.
Usage: python3 -I tools/nba/review/structure.py forward-v2.jsonl"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import math, random
from collections import defaultdict
from datetime import datetime
from common import *

legs, multis = load(sys.argv[1])
S = settled_legs(legs)
role = roles(legs)
RM = ((1.3, 0.067), (2.2, 0.076), (3.0, 0.063)); RML = 0.10; SHADE = 0.013


def ci(vals_by_game, f):
    """Point estimate f(list of per-game items) and a game-bootstrap 95% interval."""
    g = list(vals_by_game.values()); rng = random.Random(SEED); out = []
    for _ in range(B):
        out.append(f([g[rng.randrange(len(g))] for _ in g]))
    out = sorted(x for x in out if x is not None)
    return f(g), out[int(.025 * len(out))], out[int(.975 * len(out)) - 1]


# ---- (a) same-game dependence ----------------------------------------------------------------
print("== (a) Same-game dependence: correlation of standardised outcomes, different players ==")
print("one leg per (game, player, stat); e = (won - chance)/sd. pair value = mean e_i*e_j; 0 = independent.")
def one_per(sel, target):
    best = {}
    for r in S:
        if sel(r):
            k = (gid(r), r["player"], r["stat"])
            if k not in best or abs(r["chance"] - target) < abs(best[k]["chance"] - target):
                best[k] = r
    return list(best.values())
SETS = {
    "main O/U line, as overs": one_per(lambda r: ltype(r) == "ou" and not r["under"], 0.5),
    "short over rung (.65-.90)": one_per(lambda r: ltype(r) == "rung" and 0.65 <= r["chance"] <= 0.90, 0.78),
}
def corr_f(pairsel):
    def f(games):
        num = n = 0
        for rows in games:
            for i in range(len(rows)):
                a = rows[i]
                for j in range(i):
                    b = rows[j]
                    if a[0] != b[0] and pairsel(a, b):
                        num += a[1] * b[1]; n += 1
        return num / n if n else None
    return f
for name, rows in SETS.items():
    by = defaultdict(list)
    for r in rows:
        c = min(max(r["chance"], 0.02), 0.98)
        by[gid(r)].append((r["player"], (won(r) - c) / math.sqrt(c * (1 - c)), r.get("team") or "", r["stat"][:3], role(r)))
    npairs = lambda sel: sum(1 for rows_ in by.values() for i in range(len(rows_)) for j in range(i)
                             if rows_[i][0] != rows_[j][0] and sel(rows_[i], rows_[j]))
    print(f"-- {name}: {len(rows)} legs, {len(by)} games")
    tests = {
        "any two players": lambda a, b: True,
        "teammates (team known)": lambda a, b: a[2] and a[2] == b[2],
        "opponents (team known)": lambda a, b: a[2] and b[2] and a[2] != b[2],
        "pts-pts": lambda a, b: a[3] == b[3] == "poi",
        "same stat": lambda a, b: a[3] == b[3],
        "different stat": lambda a, b: a[3] != b[3],
        "star-star": lambda a, b: a[4] == b[4] == "star20+",
        "star-bench": lambda a, b: {a[4], b[4]} == {"star20+", "bench<12"},
        "bench-bench": lambda a, b: a[4] == b[4] == "bench<12",
        "teammates star-bench": lambda a, b: a[2] and a[2] == b[2] and {a[4], b[4]} == {"star20+", "bench<12"},
    }
    for t, sel in tests.items():
        e, lo, hi = ci(by, corr_f(sel))
        print(f"   {t:26} pairs {npairs(sel):6}  r = {e:+.3f} [{lo:+.3f},{hi:+.3f}]")
    # game-level overdispersion: variance of the game sum of residuals / number of legs (1 = independent)
    def od(games):
        return sum(sum(x[1] for x in rows_) ** 2 for rows_ in games) / sum(len(rows_) for rows_ in games)
    e, lo, hi = ci(by, od)
    print(f"   overdispersion of game totals (1 = independent, same-player pairs included): {e:.2f} [{lo:.2f},{hi:.2f}]")

# picked same-game stacks: joint vs product by side mix
print("-- picked same-game multis (stacks_same + by_game): pairs of legs inside one multi, distinct pairs only")
seen = {}
for m in multis:
    if m["mkind"] == "stacks" or m["result"] not in ("won", "lost"):
        continue
    L = [d for d in m["detail"] if d.get("result") in ("won", "lost")]
    for i in range(len(L)):
        for j in range(i):
            a, b = L[i], L[j]
            k = tuple(sorted([(a["player"], a["stat"], a["line"], a["under"]), (b["player"], b["stat"], b["line"], b["under"])])) + (gid(a),)
            seen[k] = (a, b)
by = defaultdict(lambda: defaultdict(list))
for (a, b) in seen.values():
    t = "over+over" if not a["under"] and not b["under"] else "under+under" if a["under"] and b["under"] else "over+under"
    by[t][gid(a)].append((a["chance"] * b["chance"], won(a) * won(b)))
for t, g in by.items():
    f = lambda games: (sum(x[1] for r_ in games for x in r_) / max(sum(x[0] for r_ in games for x in r_), 1e-9))
    e, lo, hi = ci(g, f)
    print(f"   {t:12} pairs {sum(len(v) for v in g.values()):5} games {len(g):3}  both-won / product = {e:.3f} [{lo:.3f},{hi:.3f}]")

# ---- (b) rung margin table --------------------------------------------------------------------
print("\n== (b) Alt-rung margin: fitted m = -ln(mean(won*price)) vs the table (single-agency price) ==")
print(f"{'price band':12}{'n':>6}{'table m':>9}{'fitted m':>10} {'95%':>16}{'said-got':>10}")
bands = ((1.0, 1.15), (1.15, 1.3), (1.3, 1.5), (1.5, 1.8), (1.8, 2.2), (2.2, 3.0), (3.0, 5.0), (5.0, 10.0), (10.0, 1e9))
for lo_, hi_ in bands:
    v = [r for r in S if ltype(r) == "rung" and lo_ <= r["price"] < hi_]
    if len(v) < 50:
        continue
    s = stats(v)
    mid = math.sqrt(lo_ * min(hi_, 20)); tm = next((m for top, m in RM if mid < top), RML)
    fm = lambda roi: -math.log(max(1 + roi, 1e-6))
    print(f"{lo_:g}-{hi_:<9g}{s['n']:6}{tm:9.3f}{fm(s['roi']):10.3f} [{fm(s['rhi']):.3f},{fm(s['rlo']):.3f}]{-s['gap']:+10.3f}")
print("(fitted m includes the over lean the picker removes separately: about 0.026 of it at a 50% leg, 0.008 at 85%)")

# ---- (c) OVER_SHADE ---------------------------------------------------------------------------
print("\n== (c) Over/under lean on native O/U pairs: 'market' is the no-vig chance before the lean ==")
print("lean = (market - got) for overs, pooled with (got - market) for unders; the picker uses 0.013")
OU = [r for r in S if ltype(r) == "ou" and r.get("market")]
def lean_rows(rows):
    by = defaultdict(list)
    for r in rows:
        d = r["market"] - won(r)
        by[gid(r)].append(-d if r["under"] else d)
    return by
mean_f = lambda games: (sum(x for r_ in games for x in r_) / max(sum(len(r_) for r_ in games), 1))
for name, sel in (("all O/U", lambda r: True), ("star20+", lambda r: role(r) == "star20+"),
                  ("starter12-19", lambda r: role(r) == "starter12-19"), ("bench<12", lambda r: role(r) == "bench<12"),
                  ("points", lambda r: r["stat"] == "points"), ("rebounds", lambda r: r["stat"] == "reboundsTotal"),
                  ("assists", lambda r: r["stat"] == "assists"), ("threes", lambda r: r["stat"] == "threePointersMade"),
                  ("bench points", lambda r: role(r) == "bench<12" and r["stat"] == "points"),
                  ("bench other stats", lambda r: role(r) == "bench<12" and r["stat"] != "points"),
                  ("sb", lambda r: r["agency"] == "sb"), ("pb", lambda r: r["agency"] == "pb")):
    v = [r for r in OU if sel(r)]
    e, lo, hi = ci(lean_rows(v), mean_f)
    print(f"   {name:18} n {len(v):5} (pairs counted twice)  lean {e:+.3f} [{lo:+.3f},{hi:+.3f}]")
print("   by day (all O/U):", "  ".join(f"{d}: {mean_f(list(lean_rows([r for r in OU if r['day']==d]).values())):+.3f}"
                                         for d in sorted({r['day'] for r in OU})))

# ---- (d) staleness and price drift -------------------------------------------------------------
print("\n== (d) Staleness: hours from the logged quote to tip-off; and later price drift ==")
def ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None
print(HEAD)
g = defaultdict(list)
for r in S:
    q, t = ts(r.get("quoted_at") or ""), ts(r.get("startsAt") or "")
    if q and t and r["chance"] >= 0.5:
        h = (t - q) / 3600
        g["lead <3h" if h < 3 else "lead 3-8h" if h < 8 else "lead 8-16h" if h < 16 else "lead 16h+"].append(r)
for k in sorted(g):
    print(line(f"chance>=.5 {k}", stats(g[k])))
g = defaultdict(list)
for r in S:
    t = ts(r.get("startsAt") or "")
    qs = [q for q in (r.get("quotes") or []) if t and (ts(q.get("at") or "") or 1e18) < t]  # pre-tip quotes only
    if qs and r["chance"] >= 0.45:
        last = qs[-1]["price"]; d = math.log(last / r["price"])
        g["price later shortened >3%" if d < -0.03 else "price later drifted >3%" if d > 0.03 else "price held"].append(r)
for k in sorted(g):
    print(line(k, stats(g[k])))
for sd in ("over", "under"):
    for k in sorted(g):
        v = [r for r in g[k] if side(r) == sd]
        if len(v) >= 30:
            print(line(f"{sd}: {k}", stats(v)))

# ---- (e) ladder smoothing ----------------------------------------------------------------------
print("\n== (e) Ladder smoothing / cross-book mean: market vs the leg's own-price chance (rungs) ==")
print(HEAD)
g = defaultdict(list)
for r in S:
    if ltype(r) == "rung" and r.get("market") and 0.45 <= r["chance"]:
        m = next((mm for top, mm in RM if r["price"] < top), RML)
        own = math.exp(-m) / r["price"]
        d = r["market"] - own
        g["market > own price by 2+ pts" if d > 0.02 else "market < own price by 2+ pts" if d < -0.02 else "market ~ own price"].append(r)
for k in sorted(g):
    print(line(k, stats(g[k])))
    print(line("  same legs, said = own price", stats(g[k], said=lambda r: min(math.exp(-next((mm for top, mm in RM if r['price'] < top), RML)) / r['price'], .999))))

# ---- (f) early vs latest log of the same bet ----------------------------------------------------
print("\n== (f) Same bet logged on an earlier day vs its latest log (Brier score, lower is better) ==")
first, last = {}, {}
for r in legs:
    if r.get("result") in ("won", "lost") and r.get("chance"):
        k = lkey(r)
        if k not in first or r["day"] < first[k]["day"]:
            first[k] = r
        if k not in last or r["day"] > last[k]["day"]:
            last[k] = r
pairs = [(first[k], last[k]) for k in first if first[k]["day"] != last[k]["day"]]
if pairs:
    b0 = sum((a["chance"] - won(a)) ** 2 for a, b in pairs) / len(pairs)
    b1 = sum((b["chance"] - won(b)) ** 2 for a, b in pairs) / len(pairs)
    mv = sum(abs(a["chance"] - b["chance"]) for a, b in pairs) / len(pairs)
    print(f"bets logged on 2+ days: {len(pairs)}; Brier early {b0:.4f} vs latest {b1:.4f}; mean |move| {mv:.3f}")
else:
    print("no bet was logged on two days")
