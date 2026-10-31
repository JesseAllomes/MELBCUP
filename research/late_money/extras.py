"""Pull what build.py does not keep: stored Sportsbet/Ladbrokes fixed place prices and the stored tote dividends
(exotics) per race, straight from the racing.com dumps. No tokens, no network.
Usage: python3 -I extras.py <MELBCUP_ROOT> <out_dir>"""
import sys, os, glob, gzip, json, re, pickle, bisect, datetime
root, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
place, exo, snaps = [], [], []
GRID = (120, 15, 0)   # minutes before the scheduled start; the rest of the grid comes from build_lm.py
pools = {}
def price(s):
    try:
        v = float(str(s).replace("$", "")); return v if v > 1 else None
    except Exception:
        return None
def start_epoch(t):
    return datetime.datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()
def series(fl):
    pts = sorted((x["updateTime"], price(x.get("amount"))) for x in (fl or []) if x.get("updateTime") is not None and price(x.get("amount")))
    return [t for t, _ in pts], [p for _, p in pts]
def at(ts, ps, cut):
    i = bisect.bisect_right(ts, cut) - 1
    return ps[i] if i >= 0 else None
for f in sorted(glob.glob(f"{root}/big/meetings/*.json.gz")):
    try:
        d = json.load(gzip.open(f))
    except Exception:
        continue
    mid = str(d["id"])
    for r in d.get("races") or []:
        if not r.get("time"):
            continue
        rid = f"{mid}_{int(r['raceNumber'])}"
        for x in r.get("exotics") or []:
            pools[x.get("poolStatusCode")] = pools.get(x.get("poolStatusCode"), 0) + 1
            exo.append((rid, x.get("poolStatusCode"), x.get("selections"), price(x.get("amount")), x.get("amount")))
        st = start_epoch(r["time"])
        for e in r.get("formRaceEntries") or []:
            row = [rid, e.get("raceEntryNumber")]
            for b in ("sb", "lb"):
                ts, ps = series((e.get(b) or [{}])[0].get("flucsWin") if e.get(b) else None)
                row += [at(ts, ps, st - g * 60) for g in GRID]
            snaps.append(tuple(row))
            od = {o.get("providerCode"): o for o in (e.get("odds") or [])}
            place.append((rid, e.get("raceEntryNumber"), price((od.get("SB2") or {}).get("oddsPlace")), price((od.get("LB2") or {}).get("oddsPlace")),
                          price((od.get("V") or {}).get("oddsPlace")), price((od.get("N") or {}).get("oddsPlace")), price((od.get("Q") or {}).get("oddsPlace"))))
pickle.dump(dict(place=place, exo=exo, pools=pools, snaps=snaps, snap_cols=["race_id", "entry_no"] + [f"{b}_t{g}x" for b in ("sb", "lb") for g in GRID]), open(f"{out}/extras.pkl", "wb"))
print(len(place), len(exo), pools)
