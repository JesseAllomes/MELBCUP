"""Validate the live observation store's contents (tools/live_collector.py output).

Usage: python3 live_validate.py <observations folder> [--git <checkout of the live branch>] [--json out.json]

1. Timing
   - every record has obs_utc; every request record has recv_utc >= obs_utc;
   - market and field records were received before the race's start as racing.com held it at that
     observation, with the race still open;
   - per race: snapshots selectable strictly at or before T-30 (recv_utc <= start - 30 min, using the
     start time in the same snapshot), and the latest one.
2. Field meaning (field / field_post records): for weightCarried, weight, weightPrevious,
   apprenticeAllowedClaim and apprenticeCanClaim, the count of null, empty, false, zero and other values,
   kept separate; parseable kilograms; weightCarried vs weight agreement.
3. Continuity
   - obs_id unique (records written before obs_id existed are counted as legacy);
   - no unfinished .part files;
   - heartbeat gaps (tools/live_gaps.py rule) and runs without a stop record (restarts and kills);
   - with --git: every commit on the live branch only adds files, so no file has changed after its
     first commit.
"""
import argparse, collections, datetime, glob, gzip, json, os, re, subprocess

KG = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*kg\s*$", re.I)
FIELDS = ("weightCarried", "weight", "weightPrevious", "apprenticeAllowedClaim", "apprenticeCanClaim")


def ts(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))


def kind_of(v):
    if v is None:
        return "null"
    if v is False:
        return "false"
    if v is True:
        return "true"
    if isinstance(v, str):
        if v.strip() == "":
            return "empty"
        if v.strip() in ("0", "0.0"):
            return "zero"
        if KG.match(v):
            return "kg"
        try:
            float(v)
            return "number"
        except ValueError:
            return "text"
    if isinstance(v, (int, float)):
        return "zero" if v == 0 else "number"
    return type(v).__name__


def load(store):
    files = sorted(glob.glob(os.path.join(store, "*", "*.jsonl.gz")))
    recs = []
    for f in files:
        with gzip.open(f, "rt") as fh:
            for i, line in enumerate(fh):
                r = json.loads(line)
                r["_file"], r["_line"] = os.path.relpath(f, store), i
                recs.append(r)
    parts = glob.glob(os.path.join(store, "*", "*.part"))
    return files, recs, parts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("store")
    ap.add_argument("--git", help="checkout of the live branch, for the append-only history check")
    ap.add_argument("--json")
    ap.add_argument("--gap", type=float, default=150.0)
    a = ap.parse_args()
    files, recs, parts = load(a.store)
    out = dict(files=len(files), records=len(recs), kinds=dict(collections.Counter(r["kind"] for r in recs)))

    # ---------------- 1. timing
    t = collections.Counter()
    held = {}   # (run, what, target) -> latest data, for same_as markers in file order
    races = collections.defaultdict(list)
    for r in recs:
        t["has_obs_utc"] += "obs_utc" in r
        if r["kind"] in ("cycle", "start", "stop"):
            continue
        if "recv_utc" not in r:
            t["missing_recv_utc"] += 1
            continue
        if ts(r["recv_utc"]) < ts(r["obs_utc"]):
            t["recv_before_obs"] += 1
        tgt = (r["run"], r.get("what", r["kind"]), r.get("meet_code"), r.get("race_number"), r.get("state"))
        if "data" in r:
            held[tgt] = r["data"]
        elif "same_as" in r:
            t["markers"] += 1
        if r["kind"] != "market":
            continue
        data = r.get("data") or held.get(tgt)
        race = (data or {}).get("GetBettingData") or {}
        start = race.get("officialTime") or race.get("time")
        if not start:
            t["market_without_start"] += 1
            continue
        recv, st = ts(r["recv_utc"]), ts(start)
        status = f"{race.get('raceStatus')}/{race.get('bettingStatus')}"
        pre = recv < st
        t["market_pre_start"] += pre
        t["market_post_start"] += not pre
        t[f"status {status} {'pre' if pre else 'post'}-start"] += 1
        races[(r.get("meet_code"), r.get("race_number"))].append((recv, st, status))
    sel = []
    for key, snaps in races.items():
        ok = [s for s in snaps if s[0] <= s[1] - datetime.timedelta(minutes=30)]
        sel.append(dict(race=f"{key[0]}/{key[1]}", snapshots=len(snaps), at_or_before_T30=len(ok),
                        latest_selectable=ok and max(s[0] for s in ok).isoformat(timespec="seconds"),
                        start=snaps[-1][1].isoformat(timespec="seconds")))
    out["timing"] = dict(counts=dict(t), races=len(sel), races_with_T30_snapshot=sum(s["at_or_before_T30"] > 0 for s in sel),
                         example=sorted(sel, key=lambda s: s["start"])[:5])

    # ---------------- 2. field meaning
    f = {k: collections.Counter() for k in FIELDS}
    agree = collections.Counter()
    kgs = []
    held = {}
    for r in recs:
        if r["kind"] not in ("field", "field_post"):
            continue
        tgt = (r["run"], r.get("meet_code"), r.get("race_number"))
        data = r.get("data")
        if data is not None:
            held[tgt] = data
        else:
            data = held.get(tgt)
        for e in ((data or {}).get("getNoCacheRaceForm") or {}).get("formRaceEntries") or []:
            for k in FIELDS:
                f[k][kind_of(e.get(k, "<absent>") if k in e else "<absent>")] += 1
            wc, w = e.get("weightCarried"), e.get("weight")
            agree["weightCarried == weight" if wc == w else "differ"] += 1
            m = KG.match(wc or "")
            if m:
                kgs.append(float(m.group(1)))
    out["fields"] = dict(values={k: dict(v) for k, v in f.items()}, weight_agreement=dict(agree),
                         kg_range=[min(kgs), max(kgs)] if kgs else None, entries=sum(f["weight"].values()))

    # ---------------- 3. continuity
    ids = [r.get("obs_id") for r in recs]
    have = [i for i in ids if i]
    out_c = dict(records_with_obs_id=len(have), legacy_without_obs_id=len(ids) - len(have),
                 duplicate_obs_ids=len(have) - len(set(have)), part_files=len(parts))
    runs = {}
    cyc = []
    for r in recs:
        if r["kind"] == "start":
            runs.setdefault(r["run"], {})["start"] = r["obs_utc"]
        elif r["kind"] == "stop":
            runs.setdefault(r["run"], {})["stop"] = r["obs_utc"]
        elif r["kind"] == "cycle":
            cyc.append(ts(r["obs_utc"]))
            runs.setdefault(r["run"], {})
    cyc.sort()
    gaps = [(x.isoformat(timespec="seconds"), y.isoformat(timespec="seconds"), round((y - x).total_seconds() / 60, 1))
            for x, y in zip(cyc, cyc[1:]) if (y - x).total_seconds() > a.gap]
    out_c.update(runs={k: v.get("stop", "NO STOP RECORD (killed, cancelled or still running)") for k, v in runs.items()},
                 heartbeats=len(cyc), gaps=gaps)
    if a.git:
        g = lambda *x: subprocess.run(["git", "-C", a.git, *x], capture_output=True, text=True).stdout
        changed = [l for l in g("log", "--diff-filter=MDRTC", "--name-status", "--format=").splitlines() if l.strip()]
        out_c["history_commits"] = len(g("log", "--format=%h").split())
        out_c["history_non_add_changes"] = changed
    out["continuity"] = out_c
    print(json.dumps(out, indent=1, default=str))
    if a.json:
        json.dump(out, open(a.json, "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
