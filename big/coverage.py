import glob, gzip, json, collections
files = sorted(glob.glob("meetings/2026-0[4-9]*.json.gz"))[-600:]
c = collections.Counter(); n = 0; races = 0; rc = collections.Counter(); mc = collections.Counter(); states = collections.Counter()
def has(v):
    return v not in (None, "", [], {}, "0", 0, "0.00", "-")
for f in files:
    m = json.load(gzip.open(f)); states[m.get("state")] += 1
    for k in ("railPosition", "weather", "rainfall", "irrigation", "penetrometer", "comments", "trackConditions", "previousRailPositions"):
        mc[k] += has(m.get(k))
    for r in m.get("races") or []:
        races += 1
        for k in ("tempo", "hasSectionals", "standardTimeDifference", "fastestLate", "exotics", "time"):
            rc[k] += has(r.get(k))
        for e in r.get("formRaceEntries") or []:
            if e.get("scratched"): continue
            n += 1
            t = e.get("timing") or {}
            for k in ("startingPrice", "positionAtSettledAbv", "positionAt800Abv", "positionAt400Abv", "timeSectional", "commentStewards",
                      "gearChanges", "speedValue", "handicapRating", "bettingFluctuationsPriceOpen", "margin"):
                c[k] += has(e.get(k))
            c["sb_flucs"] += bool(e.get("sb") and e["sb"][0].get("flucsWin"))
            c["lb_flucs"] += bool(e.get("lb") and e["lb"][0].get("flucsWin"))
            c["timing_200m_splits"] += bool(t.get("times"))
            c["distanceFromRail"] += has(t.get("distanceFromRail"))
            c["topSpeed"] += has(t.get("topSpeed"))
            c["sire"] += has((e.get("horse") or {}).get("sireHorseName"))
print(len(files), "meetings,", races, "races,", n, "runners (Apr-Sep 2026 sample)", dict(states))
print("runner fields:", {k: f"{v/n:.0%}" for k, v in c.most_common()})
print("race fields:", {k: f"{v/races:.0%}" for k, v in rc.most_common()})
print("meeting fields:", {k: f"{v/len(files):.0%}" for k, v in mc.most_common()})
