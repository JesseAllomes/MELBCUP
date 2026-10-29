"""Outage report for the live observation store (tools/live_collector.py output).

Reads every observations/<date>/*.jsonl.gz and reports, from the records alone:
  runs      each collector run: start, stop (or "no stop record": crashed or killed), cycles
  gaps      heartbeat gaps: consecutive cycle records more than --gap seconds apart, within or between
            runs. A gap is a period with no live observation; nothing fills it.
  failures  failed requests by kind, and cycles where a watched race could not be fetched
Usage: python3 live_gaps.py <observations folder> [--gap 150] [--since 2026-10-29]
"""
import argparse, datetime, glob, gzip, json, os
from collections import Counter


def ts(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("store")
    ap.add_argument("--gap", type=float, default=150.0, help="seconds between heartbeats that count as an outage")
    ap.add_argument("--since", default="")
    a = ap.parse_args()
    files = sorted(f for f in glob.glob(os.path.join(a.store, "*", "*.jsonl.gz")) if os.path.basename(os.path.dirname(f)) >= a.since)
    runs, cycles, fails, partial = {}, [], Counter(), 0
    for f in files:
        with gzip.open(f, "rt") as fh:
            for line in fh:
                r = json.loads(line)
                k = r["kind"]
                if k == "start":
                    runs.setdefault(r["run"], {})["start"] = r["obs_utc"]
                    runs[r["run"]]["version"] = r.get("version", "")[:12]
                elif k == "stop":
                    runs.setdefault(r["run"], {})["stop"] = r["obs_utc"]
                    runs[r["run"]]["reason"] = r.get("reason")
                elif k == "cycle":
                    cycles.append((ts(r["obs_utc"]), r["run"]))
                    runs.setdefault(r["run"], {}).setdefault("cycles", 0)
                    runs[r["run"]]["cycles"] += 1
                    partial += r.get("market_failed", 0) > 0
                elif k == "error":
                    fails[r.get("what")] += 1
    print(f"{len(files)} files, {len(runs)} runs, {len(cycles)} heartbeats")
    print("\nruns:")
    for run, v in sorted(runs.items(), key=lambda kv: kv[1].get("start", "")):
        print(f"  {run}  start {v.get('start', '?')}  stop {v.get('stop', 'NO STOP RECORD')}  "
              f"cycles {v.get('cycles', 0)}  {v.get('reason', '')}  version {v.get('version', '?')}")
    cycles.sort()
    gaps = [(a_[0], b_[0], (b_[0] - a_[0]).total_seconds(), a_[1] != b_[1]) for a_, b_ in zip(cycles, cycles[1:])
            if (b_[0] - a_[0]).total_seconds() > a.gap]
    print(f"\ngaps over {a.gap:.0f} s: {len(gaps)} (total {sum(g[2] for g in gaps) / 60:.1f} min)")
    for s, e, d, between in gaps:
        print(f"  {s.isoformat(timespec='seconds')} -> {e.isoformat(timespec='seconds')}  {d / 60:.1f} min"
              f"  {'between runs' if between else 'within a run'}")
    print(f"\nfailed requests: {dict(fails) or 'none'}; cycles with a watched race not fetched: {partial}")


if __name__ == "__main__":
    main()
