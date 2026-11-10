"""Q4: replay the picker's own search (melbcup.nba_legs, read-only import) on each logged slate
with alternative leg pools / chances, and score every variant on what actually happened.
A slate = (day, agency): the legs logged that day that later settled won/lost. Recalibrated
variants are fitted leave-one-day-out (the day being scored never informs its own correction).
Usage: python3 -I tools/nba/review/replay.py forward-v2.jsonl [repo root]"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(1, sys.argv[2] if len(sys.argv) > 2 else os.path.abspath(os.path.join(HERE, "..", "..", "..")))
import math, random
from collections import defaultdict
from common import *
from melbcup import nba_legs as N

legs, multis = load(sys.argv[1])
role = roles(legs)
TARGETS = (2.0, 3.0, 5.0, 10.0)
slates = defaultdict(list)
for r in legs:
    if r.get("result") in ("won", "lost") and r.get("chance") and r.get("price", 0) > 1:
        slates[(r["day"], r["agency"])].append(r)
days = sorted({d for d, _a in slates})
print(f"slates {len(slates)} (day x agency), days {days}")


def cell(r):
    return (side(r), ltype(r), role(r), "pts" if r["stat"] == "points" else "other",
            "short" if r["price"] < 1.5 else "mid" if r["price"] < 2.2 else "long")


def cell2(r):
    return (side(r), role(r), "pts" if r["stat"] == "points" else "other")


def fit(exclude_day, K=200, cell=None):
    cell = cell or globals()["cell"]
    """Additive gap (got - said) per cell from the other days, shrunk toward 0 with K pseudo-legs."""
    acc = defaultdict(lambda: [0, 0.0])
    for r in settled_legs([x for x in legs if x["day"] != exclude_day]):
        a = acc[cell(r)]; a[0] += 1; a[1] += won(r) - r["chance"]
    return {k: a[1] / (a[0] + K) for k, a in acc.items()}


def prep(rows, chance=lambda r: r["chance"], keep=lambda r: True):
    out = []
    for r in rows:
        if keep(r):
            c = min(max(chance(r), 0.01), 0.99)
            out.append({**r, "chance": c, "said0": r["chance"], "event": gid(r)})
    return out


def run(pool, max_legs=10, min_legs=2, floor=0.5, same_floor=None):
    """(cross-game stacks, same-game stacks) as lists of leg lists per target."""
    cross = {}
    for t in TARGETS:
        byg = defaultdict(list)
        for g in N._auto(list(pool)):
            if g["chance"] >= floor:
                byg[g["event"]].append(g)
        cross[t] = N.best_stack([N.frontier(v) for v in byg.values()], t, min_legs, max_legs)
    old = N.SAME_FLOOR
    if same_floor is not None:
        N.SAME_FLOOR = same_floor
    try:
        byg = defaultdict(list)
        for g in N._auto(list(pool)):
            byg[g["event"]].append(g)
        same = {t: [] for t in TARGETS}
        for gs in byg.values():
            found = N.best_same_game(N._player_groups(gs), TARGETS, max_legs=min(max_legs, N.SAME_MAX_LEGS), min_legs=min_legs)
            for t, hit in found.items():
                if hit:
                    same[t].append(hit[0])
    finally:
        N.SAME_FLOOR = old
    return cross, same


VARIANTS = {
    "A current picker": dict(),
    "B overs only": dict(keep=lambda r: not r["under"]),
    "C unders + overs, no mixing*": None,  # handled below: best of overs-only and unders-only by said
    "D at most 3 legs": dict(max_legs=3),
    "F no bench (<12 pts) overs": dict(keep=lambda r: r["under"] or role(r) != "bench<12"),
    "G recalibrated chance (LODO)": "recal",
    "H role-only correction (LODO)": "role",
    "I no leg under $1.20": dict(keep=lambda r: r["price"] >= 1.20),
    "J no leg under 60% (cross)": dict(floor=0.60),
    "K own-price chance (no cross-book)": "own",
}
res = {v: {"cross": [], "same": []} for v in VARIANTS}
for (day, ag), rows in sorted(slates.items()):
    gap = fit(day)
    gap2 = fit(day, cell=cell2)
    rc = lambda r: r["chance"] + gap.get(cell(r), 0.0)
    for v, spec in VARIANTS.items():
        if spec is None:
            a = run(prep(rows, keep=lambda r: not r["under"]))
            b = run(prep(rows, keep=lambda r: r["under"]))
            pc = lambda st: math.prod(g["chance"] for g in st) if st else -1
            cross = {t: max((a[0][t], b[0][t]), key=pc) for t in TARGETS}
            same = a[1]
        elif spec == "recal":
            cross, same = run(prep(rows, chance=rc))
        elif spec == "role":
            cross, same = run(prep(rows, chance=lambda r: r["chance"] + gap2.get(cell2(r), 0.0)))
        elif spec == "own":
            own = lambda r: N.shade(N.single_chance(r["price"]), bool(r["under"])) if ltype(r) == "rung" else r["chance"]
            cross, same = run(prep(rows, chance=own))
        else:
            kw = {k: spec[k] for k in ("max_legs", "floor") if k in spec}
            cross, same = run(prep(rows, keep=spec.get("keep", lambda r: True)), **kw)
        for t in TARGETS:
            if cross[t]:
                res[v]["cross"].append((day, ag, t, cross[t]))
            for st in same[t]:
                res[v]["same"].append((day, ag, t, st))


def score(items, fair):
    """n, said (picker's own chance at pick time), fair (LODO-recalibrated product), got, price, legs, unders share."""
    n = len(items)
    if not n:
        return None
    said = sum(math.prod(g["chance"] for g in st) for *_x, st in items) / n
    fr = sum(math.prod(min(max(g["said0"] + fair[d].get(cell(g), 0.0), 0.01), 0.99) for g in st) for d, _a, _t, st in items) / n
    wins = [all(g["result"] == "won" for g in st) for *_x, st in items]
    price = sum(math.prod(g["price"] for g in st) for *_x, st in items) / n
    ret = sum(math.prod(g["price"] for g in st) if w else 0.0 for w, (*_x, st) in zip(wins, items)) / n - 1
    nl = sum(len(st) for *_x, st in items) / n
    un = sum(g["under"] for *_x, st in items for g in st) / sum(len(st) for *_x, st in items)
    lh = sum(g["result"] == "won" for *_x, st in items for g in st) / sum(len(st) for *_x, st in items)
    return n, said, fr, sum(wins) / n, price, ret, nl, un, lh, wins


fair = {d: fit(d) for d in days}
for kind in ("cross", "same"):
    print(f"\n== {'One leg per game (stacks)' if kind == 'cross' else 'Same-game (stacks_same), every game'}: targets {TARGETS} ==")
    print(f"{'variant':36}{'n':>5}{'said':>7}{'fair':>7}{'got':>7} {'Wilson95':>14}{'avg price':>10}{'ret/$':>7}{'legs':>6}{'unders':>8}{'leg hit':>8}  got - A (paired, slate bootstrap 95%)")
    base = {(d, a, t, i): w for i, ((d, a, t, _s), w) in enumerate(zip(res["A current picker"][kind], score(res["A current picker"][kind], fair)[-1]))}
    for v in VARIANTS:
        s = score(res[v][kind], fair)
        if not s:
            continue
        n, said, fr, got, price, ret, nl, un, lh, wins = s
        lo, hi = wilson(sum(wins), n)
        # paired difference per slate (mean win rate of the variant minus A's on the same slate)
        per = defaultdict(lambda: [0, 0]); perA = defaultdict(lambda: [0, 0])
        for (d, a, _t, _s), w in zip(res[v][kind], wins):
            per[(d, a)][0] += w; per[(d, a)][1] += 1
        for (d, a, _t, _s), w in zip(res["A current picker"][kind], score(res["A current picker"][kind], fair)[-1]):
            perA[(d, a)][0] += w; perA[(d, a)][1] += 1
        keys = [k for k in per if k in perA]
        rng = random.Random(SEED); diffs = []
        for _ in range(B):
            ks = [keys[rng.randrange(len(keys))] for _ in keys]
            diffs.append(sum(per[k][0] for k in ks) / sum(per[k][1] for k in ks) - sum(perA[k][0] for k in ks) / sum(perA[k][1] for k in ks))
        diffs.sort()
        print(f"{v:36}{n:5}{said:7.3f}{fr:7.3f}{got:7.3f} [{lo:.3f},{hi:.3f}]{price:10.2f}{ret:+7.2f}{nl:6.1f}{100*un:7.0f}%{lh:8.3f}  {got - sum(base.values())/len(base):+.3f} [{diffs[int(.025*B)]:+.3f},{diffs[int(.975*B)-1]:+.3f}]")
    print("-- by target, got (fair) per variant")
    for v in VARIANTS:
        parts = []
        for t in TARGETS:
            it = [x for x in res[v][kind] if x[2] == t]
            s = score(it, fair)
            if s:
                parts.append(f"${t:g}: {s[3]:.2f} ({s[2]:.2f}) n={s[0]}")
        print(f"   {v:34} " + "  ".join(parts))
print("\n'fair' = product of the legs' logged chance + the leave-one-day-out type correction: the lower-noise"
      "\nestimate of the true chance; 'got' is the raw outcome on the same slates and is very noisy at these n."
      "\n* C picks, per target, the likelier of the overs-only and the unders-only stack (never a mix).")

# sanity: how close is variant A to what the app logged? (the app ran several times a day on the
# pool of that moment and with the leg-count rule of that day; the log keeps one end-of-day pool)
logged = defaultdict(list)
for m in multis:
    if m["mkind"] == "stacks":
        logged[(m["day"], m["agency"], m["target"])].append(set(m["picks"]))
hit = tot = 0; jac = []
for d, a, t, st in res["A current picker"]["cross"]:
    if (d, a, t) in logged:
        mine = {g["label"] for g in st}
        tot += 1; hit += any(mine == x for x in logged[(d, a, t)])
        jac.append(max(len(mine & x) / len(mine | x) for x in logged[(d, a, t)]))
print(f"\nreplay check: variant A equals a logged cross-game pick on {hit} of {tot} slate-targets; mean best leg overlap"
      f" {sum(jac)/max(len(jac),1):.2f}. The replay is the CURRENT search on the end-of-day pool, not a re-run of history.")
print("Rows 'D at most 3 legs' drop the targets three legs cannot reach: compare it by target only.")
