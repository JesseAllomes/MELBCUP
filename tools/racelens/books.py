# ruff: noqa
"""Does adding RaceLens' extra bookmakers (TAB, Ladbrokes/Neds, OP...) help MELBCUP? Token-free.

Usage: python3 tools/racelens/books.py RAWDIR [REPO]
Only quotes fetched at or before RaceLens' prediction time (about 2 minutes before the jump) are used, so
no post-jump price leaks in. Reports log loss on the winner for MELBCUP's 4-book consensus vs every
fixed book, and the price uplift on MELBCUP's win pick when TAB/Ladbrokes/Neds may be used.
"""
import sys, json, glob, math, datetime as dt
sys.path.insert(0, sys.argv[2] if len(sys.argv) > 2 else ".")
from melbcup.model.probability import corrected_market

ts = lambda s: dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
OURS = {"SB2", "LB2", "PB3", "BT"}            # racing.com codes MELBCUP uses today
ACCOUNTS = {"SB2", "Sportsbet", "PB3"}        # where the owner holds money (Betfair not in this data)
EXTRA = {"TAB Fixed", "Ladbrokes", "LB2"}     # agencies RaceLens adds that the owner could open
rows = []
for f in sorted(glob.glob(f"{sys.argv[1]}/race_*.json")):
    r = json.load(open(f)); race, pred, res = r["race"], r.get("prediction"), r.get("result")
    if not pred or not res or res.get("status") != "final" or not res.get("placings"): continue
    gen = ts(pred["generatedAt"])
    if gen > ts(race["startTime"]): continue
    run = [x for x in race["runners"] if not x.get("scratched")]
    q = {}
    for x in run:
        last = {}
        for o in x.get("odds", []):
            if o.get("type") == "fixed" and o.get("win") and ts(o["fetchedAt"]) <= gen:
                b = o["bookmaker"]
                if b not in last or ts(o["fetchedAt"]) >= ts(last[b]["fetchedAt"]): last[b] = o
        q[x["number"]] = {b: o["win"] for b, o in last.items()}
    def cons(books):
        imp = {n: [1 / p for b, p in v.items() if b in books] for n, v in q.items()}
        if any(not v for v in imp.values()): return None
        m = {n: sum(v) / len(v) for n, v in imp.items()}; t = sum(m.values())
        return corrected_market({n: v / t for n, v in m.items()})
    allb = set().union(*[set(v) for v in q.values()]) if q else set()
    a, b = cons(OURS), cons(allb)
    if not a or not b: continue
    rows.append(dict(id=f.split("race_")[1][:-5], w=res["placings"][0][0], a=a, b=b, q=q))

def ll(k): return sum(-math.log(max(x[k].get(x["w"], 1e-6), 1e-6)) for x in rows) / len(rows)
print(f"races with every runner priced before the prediction: {len(rows)}")
if rows:
    d = [math.log(max(x["b"].get(x["w"], 1e-6), 1e-6)) - math.log(max(x["a"].get(x["w"], 1e-6), 1e-6)) for x in rows]
    m = sum(d) / len(d); se = (sum((v - m) ** 2 for v in d) / max(len(d) - 1, 1)) ** .5 / len(d) ** .5
    print(f"log loss  MELBCUP 4 books {ll('a'):.4f}   all fixed books {ll('b'):.4f}   all minus 4: {m:+.4f} nats/race better (se {se:.4f})")
    up = []; st = ret_a = ret_b = 0
    for x in rows:
        p = x["a"]
        cand = {n: max([v[b] for b in v if b in ACCOUNTS] or [0]) for n, v in x["q"].items()}
        ev = {n: p[n] * cand[n] - 1 for n in p if cand[n] and p[n] >= 0.04}
        if not ev: continue
        n = max(ev, key=ev.get)
        pa = cand[n]; pb = max([pa] + [x["q"][n][b] for b in x["q"][n] if b in EXTRA])
        up.append(pb / pa - 1); st += 1; ret_a += pa if n == x["w"] else 0; ret_b += pb if n == x["w"] else 0
    if up:
        print(f"win pick price uplift from TAB/Ladbrokes: mean {100*sum(up)/len(up):+.1f}%, better price in {sum(u>0 for u in up)}/{len(up)} races")
        print(f"flat $1 win pick ROI: current accounts {100*(ret_a-st)/st:+.1f}%   with TAB/Ladbrokes {100*(ret_b-st)/st:+.1f}%  ({st} bets)")
