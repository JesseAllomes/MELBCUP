# ruff: noqa
"""Head-to-head: RaceLens model vs MELBCUP model on the same pre-race snapshot. Token-free.
Usage: python3 score.py RAWDIR MELBCUP_REPO"""
import sys, json, glob, math, datetime as dt, collections
sys.path.insert(0, sys.argv[2])
from melbcup.model.probability import corrected_market, top_k_probs
RAW = sys.argv[1]
BOOKS = ("SB2", "LB2", "PB3", "BT")  # racing.com codes = MELBCUP's sb, lb, pb, bt
ts = lambda s: dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
rows = []
for f in sorted(glob.glob(f"{RAW}/race_*.json")):
    r = json.load(open(f)); race, pred, res = r["race"], r.get("prediction"), r.get("result")
    if not pred or not res or res.get("status") != "final" or not res.get("placings"): continue
    gen, start = ts(pred["generatedAt"]), ts(race["startTime"])
    if gen > start: continue  # prediction made after the jump: not a fair test
    plc = [p[0] for p in res["placings"] if p]  # dead heats: first listed
    winner = plc[0]
    run = {x["number"]: x for x in race["runners"] if not x.get("scratched")}
    # market snapshot frozen inside the prediction (stored odds are often refreshed after the jump)
    mw = {x["number"]: x.get("marketWinProb") for x in pred["ranked"] if x["number"] in run}
    if len(mw) < len(run) or not all(mw.values()): continue
    s_ = sum(mw.values()); mkt = {n: v / s_ for n, v in mw.items()}
    mel = corrected_market(mkt)
    rl = {x["number"]: x["winProb"] for x in pred["ranked"] if x["number"] in run}
    if len(rl) < len(run): continue
    t = sum(rl.values()); rl = {n: v / t for n, v in rl.items()}
    best = {x["number"]: x.get("bestOdds") for x in pred["ranked"]}
    bestpl = {x["number"]: x.get("bestPlace") for x in pred["ranked"]}
    places = 2 if len(run) <= 7 else 3
    rows.append(dict(id=f.split("race_")[1][:-5], n=len(run), winner=winner, plc=plc[:places], mkt=mkt, mel=mel, rl=rl,
                     melpl=top_k_probs(mel, places), rlpl={x["number"]: x["placeProb"] for x in pred["ranked"]},
                     best=best, bestpl=bestpl, div=res.get("dividends") or {}, bet=(pred.get("betting") or {}),
                     dp=bool(pred.get("dayPatternsApplied"))))

def metrics(key):
    ll = br = top = 0.0
    for x in rows:
        p = x[key]; ll += -math.log(max(p.get(x["winner"], 1e-6), 1e-6))
        br += sum((p[n] - (n == x["winner"])) ** 2 for n in p)
        top += max(p, key=p.get) == x["winner"]
    k = len(rows); return ll / k, br / k, top / k

def flat_roi(key, rule):
    """1 unit per race on that model's pick at best fixed price available at prediction time."""
    st = ret = 0; hits = 0
    for x in rows:
        p = x[key]; b = x["best"]
        cand = [(n, p[n] * b[n] - 1) for n in p if b.get(n) and p[n] >= 0.04]
        if not cand: continue
        if rule == "fav": n = max(p, key=p.get)
        elif rule == "value": 
            v = [c for c in cand if c[1] > 0]
            if not v: continue
            n = max(v, key=lambda c: c[1])[0]
        elif rule == "closest": n = max(cand, key=lambda c: (round(c[1], 2), p[c[0]]))[0]
        if not b.get(n): continue
        st += 1; win = n == x["winner"]; hits += win; ret += b[n] if win else 0
    return st, hits, (ret - st) / st if st else 0

def place_roi(key):
    st = ret = 0
    for x in rows:
        p = x["melpl"] if key == "mel" else x["rlpl"]; bp = x["bestpl"]
        c = [n for n in x[key] if bp.get(n)]
        if not c: continue
        n = max(c, key=lambda n: p.get(n, 0)); st += 1; ret += bp[n] if n in x["plc"] else 0
    return st, (ret - st) / st if st else 0

def racelens_suggestions():
    """Settle RaceLens' own suggestions: win/place/EW at best fixed, exotics at the tote dividend x flexi."""
    agg = collections.defaultdict(lambda: [0.0, 0.0, 0])
    for x in rows:
        for s in x["bet"].get("suggestions", []):
            t, amt, rn = s["type"], s["stakeAmount"], s["runners"]; d = x["div"]; plc = x["plc"]; got = 0.0
            if t == "win": got = amt * x["best"].get(rn[0], 0) if rn[0] == x["winner"] else 0
            elif t == "place": got = amt * (x["bestpl"].get(rn[0]) or 0) if rn[0] in plc else 0
            elif t == "each-way":
                h = amt / 2; got = (h * x["best"].get(rn[0], 0) if rn[0] == x["winner"] else 0) + (h * (x["bestpl"].get(rn[0]) or 0) if rn[0] in plc else 0)
            else:
                need = {"quinella": 2, "exacta": 2, "trifecta": 3, "first4": 4}[t]
                top = plc[:need] if len(plc) >= need else None
                if s.get("legs"):
                    hit = bool(top) and all(top[i] in leg for i, leg in enumerate(s["legs"][:need]))
                else:
                    hit = bool(top) and set(top) <= set(rn)
                div = d.get(t)
                if hit and div:
                    unit = s["flexiPct"] / 100 if s.get("flexiPct") else amt / s.get("combinations", 1)
                    got = div * unit
            a = agg[t]; a[0] += amt; a[1] += got; a[2] += got > 0
    return agg

print(f"races scored: {len(rows)} (prediction before the jump, final result, full prices)  day-pattern adjusted: {sum(x['dp'] for x in rows)}")
print(f"{'model':10} {'logloss':>8} {'brier':>7} {'top-pick wins':>14}")
for k, name in (("mkt", "market"), ("mel", "MELBCUP"), ("rl", "RaceLens")):
    ll, b, t = metrics(k); print(f"{name:10} {ll:8.4f} {b:7.4f} {t:14.1%}")
# paired: per-race log-loss difference
d = [math.log(max(x["mel"].get(x["winner"], 0), 1e-6)) - math.log(max(x["rl"].get(x["winner"], 0), 1e-6)) for x in rows]
m = sum(d) / len(d); sd = (sum((v - m) ** 2 for v in d) / (len(d) - 1)) ** .5
print(f"MELBCUP minus RaceLens, nats/race on the winner: {m:+.4f} (se {sd/len(d)**.5:.4f}; + = MELBCUP better)")
print("\nflat $1 win bets at best fixed price at prediction time:")
for k, name in (("mel", "MELBCUP"), ("rl", "RaceLens")):
    for rule in ("fav", "closest", "value"):
        st, h, roi = flat_roi(k, rule); print(f"  {name:9} {rule:8} bets {st:3}  wins {h:3}  ROI {roi:+.1%}")
for k, name in (("mel", "MELBCUP"), ("rl", "RaceLens")):
    st, roi = place_roi(k); print(f"  {name:9} likeliest placer: bets {st}  ROI {roi:+.1%}")
print("\nRaceLens own suggestions settled (win/place at best fixed, exotics at tote dividend x flexi):")
T = [0, 0]
for t, (a, g, h) in sorted(racelens_suggestions().items()):
    print(f"  {t:9} staked ${a:7.2f}  returned ${g:7.2f}  hits {h:3}  ROI {(g-a)/a:+.1%}"); T[0] += a; T[1] += g
print(f"  {'TOTAL':9} staked ${T[0]:7.2f}  returned ${T[1]:7.2f}  ROI {(T[1]-T[0])/T[0]:+.1%}")
json.dump([{k: v for k, v in x.items() if k in ('id', 'winner')} for x in rows], open(sys.argv[1] + '/scored_races.json', 'w'))

# Does RaceLens add information on top of MELBCUP? p ∝ mel^(1-w) * rl^w, leave-one-meeting-out choice of w.
def ll_at(w, rs):
    t = 0.0
    for x in rs:
        q = {n: math.exp((1 - w) * math.log(max(x["mel"][n], 1e-9)) + w * math.log(max(x["rl"][n], 1e-9))) for n in x["mel"]}
        z = sum(q.values()); t += -math.log(max(q.get(x["winner"], 0) / z, 1e-6))
    return t
W = [i / 20 for i in range(0, 11)]
print("\nblend weight on RaceLens (in-sample nats/race):", "  ".join(f"{w:.2f}:{ll_at(w, rows)/len(rows):.4f}" for w in W))
meets = sorted({x["id"].rsplit("_", 1)[0] for x in rows}); oos = 0.0; chosen = []
for m in meets:
    tr = [x for x in rows if not x["id"].startswith(m + "_")]; te = [x for x in rows if x["id"].startswith(m + "_")]
    w = min(W, key=lambda w: ll_at(w, tr)); chosen.append(w); oos += ll_at(w, te)
print(f"leave-one-meeting-out blend: {oos/len(rows):.4f} nats/race vs MELBCUP alone {ll_at(0, rows)/len(rows):.4f}; weights chosen {sorted(set(chosen))}")
