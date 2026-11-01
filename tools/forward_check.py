# ruff: noqa: E501
"""Forward test of the race card's picks: T-30 against the last price before the jump, graded.

A token-free worker (run it by hand or from a schedule). It replays the live collector's observations
(tools/live_collector.py output: the `live` branch, or a folder) the way the app's last-minute check works:
for every race it takes the market snapshot nearest to 30 minutes before the start and the last one
before the jump, builds the app's chances from the four fixed-price books (margin-free consensus,
corrected by melbcup.model.probability.MARKET_ALPHA), applies the race card's pick rules
(melbcup/bets/allocate.py: win closest to fair with a 4% chance floor, likeliest placer, each way
closest to fair at $5+) at Sportsbet's price, then grades both snapshots from racing.com's results.

Usage:
  python3 tools/forward_check.py --git /path/to/repo --branch origin/live --dates 2026-11-03 2026-11-03
  python3 tools/forward_check.py --store <observations folder> --dates 2026-10-29 2026-11-07 [--meet 5195782]
Output: research/m7/forward/forward_check.json (every race, merged across runs; results are cached) and a
plain table on stdout, Melbourne time. Nothing here changes the app. One unit per bet; stakes as the app
shares them are not replayed (the day budget depends on the whole card). Betfair is not observed, so this
is the Sportsbet view only. Intervals need hundreds of races: ten Cup-day races say little either way.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import gzip
import json
import os
import subprocess
import sys
import urllib.request
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from melbcup.model.probability import corrected_market, top_k_probs  # noqa: E402

URL = "https://graphql.rmdprod.racing.com/"
KEY = "da2-6nsi4ztsynar3l3frgxf77q5fe"  # racing.com's public web key (melbcup/sources/racingcom.py)
MEL = ZoneInfo("Australia/Melbourne")
BOOKS = ("sb", "lb", "pb", "bt")
HOME = "sb"
WIN_FLOOR, EW_MIN_PRICE = 0.04, 5.0
EARLY = (25 * 60, 40 * 60)  # seconds before the start: the latest snapshot in this window is "T-30"
RESULTS = (
    "query($meetCode: ID!, $raceNumber: Int!) {"
    " getRaceForm(meetCode: $meetCode, raceNumber: $raceNumber) { status formRaceEntries {"
    " raceEntryNumber horseName finish scratched } } }"
)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research", "m7", "forward", "forward_check.json")


def money(x):
    try:
        v = float(str(x).replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return None
    return v if v > 1.0 else None


def ts(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


# --- observations ---------------------------------------------------------------------------------

def read_records(files):
    """Market records with their data, following same_as markers (data_sha256 -> last payload)."""
    by_sha: dict[str, dict] = {}
    for f in files:
        for line in gzip.open(f, "rt"):
            r = json.loads(line)
            if r.get("kind") != "market":
                continue
            data = r.get("data")
            if data is not None:
                by_sha[r.get("data_sha256", "")] = data
            elif "same_as" in r:
                data = by_sha.get(r.get("data_sha256", ""))
            if not data:
                continue
            yield r, data


def files_from_store(store, dates):
    out = []
    for d in dates:
        out += sorted(glob.glob(os.path.join(store, d, "*.jsonl.gz")))
    return out


def files_from_git(repo, branch, dates, scratch):
    """Copy the branch's observation files for the dates into scratch and return their paths."""
    listing = subprocess.run(["git", "-C", repo, "ls-tree", "-r", "--name-only", branch], check=True,
                             capture_output=True, text=True).stdout.split()
    out = []
    for path in listing:
        if not path.endswith(".jsonl.gz") or path.split("/")[-2] not in dates:
            continue
        local = os.path.join(scratch, path.replace("/", "_"))
        if not os.path.exists(local):
            with open(local, "wb") as fh:
                fh.write(subprocess.run(["git", "-C", repo, "show", f"{branch}:{path}"], check=True,
                                        capture_output=True).stdout)
        out.append(local)
    return sorted(out)


def snapshots(records, meet_filter=None):
    """race key -> list of (recv_utc, start_utc, open, runners) with runners = {no: {book: (win, place)}, ...}."""
    races: dict[tuple[str, int], list] = {}
    for r, data in records:
        meet, rn = str(r.get("meet_code")), int(r.get("race_number") or 0)
        if meet_filter and meet != meet_filter:
            continue
        bd = data.get("GetBettingData") or {}
        start = bd.get("time") or bd.get("officialTime")
        if not start or not rn:
            continue
        runners = {}
        for e in bd.get("formRaceEntries") or []:
            if e.get("scratched") or e.get("emergency"):
                continue
            n = e.get("raceEntryNumber")
            if n is None:
                continue
            prices = {}
            for b in BOOKS:
                q = (e.get(b) or [None])[0] or {}
                prices[b] = (money(q.get("oddsWin")), money(q.get("oddsPlace")))
            runners[int(n)] = dict(name=e.get("horseName") or str(n), prices=prices)
        is_open = (bd.get("bettingStatus") or "").lower() == "open"
        races.setdefault((meet, rn), []).append((ts(r["recv_utc"]), ts(start), is_open, runners))
    for v in races.values():
        v.sort(key=lambda x: x[0])
    return races


def pick_snapshots(snaps):
    """(early, late): the latest snapshot 25-40 minutes out, and the last open one before the start."""
    early = late = None
    for s in snaps:
        to_go = (s[1] - s[0]).total_seconds()
        if EARLY[0] <= to_go <= EARLY[1] and s[2] and s[3]:
            early = s
        if 0 < to_go and s[2] and s[3]:
            late = s
    return early, late


# --- chances and picks --------------------------------------------------------------------------

def chances(runners):
    """The app's chance per runner: mean over books (each margin-free) of the books that price every
    runner, then the favourite-long-shot correction. None when no book prices the whole field."""
    probs = []
    for b in BOOKS:
        q = {n: r["prices"][b][0] for n, r in runners.items()}
        if all(q.values()):
            inv = {n: 1.0 / v for n, v in q.items()}
            tot = sum(inv.values())
            probs.append({n: v / tot for n, v in inv.items()})
    if not probs:
        return None
    market = {n: sum(p[n] for p in probs) / len(probs) for n in runners}
    return corrected_market(market)


def places_paid(n: int) -> int:
    return 3 if n >= 8 else 2 if n >= 5 else 0


def picks(snapshot):
    """{'win': (no, price, chance, ev), 'place': (...), 'each_way': (...)} as the race card picks them."""
    runners = snapshot[3]
    win = chances(runners)
    if not win:
        return {}
    k = places_paid(len(runners))
    place = top_k_probs(win, k) if k else {}
    out = {}
    lines = []
    for n, r in runners.items():
        qw, qp = r["prices"][HOME]
        ev_w = None if qw is None else win[n] * qw - 1
        ev_p = None if qp is None or not place else place[n] * qp - 1
        ev_e = None if ev_w is None or ev_p is None else 0.5 * (ev_w + ev_p)
        lines.append((n, qw, qp, win[n], place.get(n, 0.0), ev_w, ev_p, ev_e))
    w = [x for x in lines if x[5] is not None and x[3] >= WIN_FLOOR]
    if w:
        n, qw, qp, pw, pp, ev_w, *_ = max(w, key=lambda x: (round(x[5], 2), x[3]))
        out["win"] = dict(no=n, name=runners[n]["name"], price=qw, chance=round(pw, 4), ev=round(ev_w, 3))
    p = [x for x in lines if x[6] is not None]
    if p:
        n, qw, qp, pw, pp, ev_w, ev_p, _ = max(p, key=lambda x: x[4])
        out["place"] = dict(no=n, name=runners[n]["name"], price=qp, chance=round(pp, 4), ev=round(ev_p, 3))
    e = [x for x in lines if x[7] is not None and x[3] >= WIN_FLOOR and x[1] >= EW_MIN_PRICE]
    if e:
        n, qw, qp, pw, pp, ev_w, ev_p, ev_e = max(e, key=lambda x: (round(x[7], 2), x[3]))
        out["each_way"] = dict(no=n, name=runners[n]["name"], price=qw, place_price=qp, chance=round(pp, 4), ev=round(ev_e, 3))
    out["_field"] = len(runners)
    return out


# --- results and grading ------------------------------------------------------------------------

def fetch_result(meet: str, rn: int):
    req = urllib.request.Request(URL, json.dumps({"query": RESULTS, "variables": {"meetCode": meet, "raceNumber": rn}}).encode(),
                                 {"x-api-key": KEY, "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        form = (json.loads(resp.read()).get("data") or {}).get("getRaceForm") or {}
    if "result" not in (form.get("status") or "").lower():
        return None
    finish = {}
    for e in form.get("formRaceEntries") or []:
        try:
            n, pos = int(e.get("raceEntryNumber")), int(e.get("finish") or 0)
        except (TypeError, ValueError):
            continue
        if pos and not e.get("scratched"):
            finish[str(n)] = pos
    return finish or None


def grade(pick: dict, kind: str, finish: dict, k: int):
    """Dollars back from one unit; None when the pick is missing."""
    if not pick:
        return None
    pos = finish.get(str(pick["no"]))
    won = pos == 1
    placed = pos is not None and pos <= k
    if kind == "win":
        return pick["price"] if won else 0.0
    if kind == "place":
        return pick["price"] if placed else 0.0
    return (0.5 * pick["price"] if won else 0.0) + (0.5 * pick["place_price"] if placed else 0.0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", help="observations folder (<UTC date>/*.jsonl.gz)")
    ap.add_argument("--git", help="repository checkout holding the live branch")
    ap.add_argument("--branch", default="origin/live")
    ap.add_argument("--dates", nargs=2, required=True, metavar=("FROM", "TO"), help="UTC dates of the observation files")
    ap.add_argument("--meet", help="only this racing.com meet code (Flemington Cup day 2026: 5195782)")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--no-fetch", action="store_true", help="do not ask racing.com for results")
    a = ap.parse_args()
    d0, d1 = (dt.date.fromisoformat(x) for x in a.dates)
    dates = [(d0 + dt.timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)]
    if a.store:
        files = files_from_store(a.store, dates)
    elif a.git:
        scratch = os.path.join(os.path.dirname(os.path.abspath(a.out)), "obs_cache")
        os.makedirs(scratch, exist_ok=True)
        files = files_from_git(a.git, a.branch, dates, scratch)
    else:
        ap.error("--store or --git is required")
    saved = {}
    if os.path.exists(a.out):
        saved = json.load(open(a.out))
    races = snapshots(read_records(files), a.meet)
    for (meet, rn), snaps in sorted(races.items()):
        key = f"{meet}/{rn}"
        row = saved.get(key) or {}
        early, late = pick_snapshots(snaps)
        if early is None and late is None:
            continue
        start = (early or late)[1]
        row.update(meet=meet, race=rn, start_mel=start.astimezone(MEL).strftime("%Y-%m-%d %H:%M"),
                   snapshots=len(snaps))
        for lab, s in (("early", early), ("late", late)):
            if s is not None:
                row[lab] = picks(s)
                row[lab + "_at_mel"] = s[0].astimezone(MEL).strftime("%H:%M:%S")
                row[lab + "_minutes_out"] = round((s[1] - s[0]).total_seconds() / 60, 1)
        if row.get("finish") is None and not a.no_fetch and start < dt.datetime.now(dt.UTC):
            try:
                row["finish"] = fetch_result(meet, rn)
            except (OSError, ValueError) as exc:
                row["result_error"] = str(exc)
        fin = row.get("finish")
        if fin:
            for lab in ("early", "late"):
                p = row.get(lab)
                if not p:
                    continue
                k = places_paid(p.get("_field", 0))
                row[lab + "_back"] = {kind: grade(p.get(kind), kind, fin, k) for kind in ("win", "place", "each_way")}
        saved[key] = row
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(saved, open(a.out, "w"), indent=1, sort_keys=True)
    report(saved)


def report(saved):
    print("race (Melbourne time)      | early win / place / each way -> late win / place / each way | back early | back late")
    tot = {lab: {k: [0.0, 0] for k in ("win", "place", "each_way")} for lab in ("early", "late")}
    changed = both = 0
    for key, row in sorted(saved.items(), key=lambda kv: kv[1].get("start_mel", "")):
        def fmt(p):
            return " / ".join(f"{p[k]['no']}@{p[k]['price']}" if p and p.get(k) else "-" for k in ("win", "place", "each_way"))
        e, lt = row.get("early"), row.get("late")
        eb, lb = row.get("early_back"), row.get("late_back")
        def back(b):
            return "-" if not b else f"${sum(v for v in b.values() if v is not None):.2f}"
        print(f"{row.get('start_mel', '?')} {key:<14} | {fmt(e):<28} -> {fmt(lt):<28} | {back(eb):>9} | {back(lb):>9}")
        if e and lt:
            both += 1
            changed += any((e.get(k) or {}).get("no") != (lt.get(k) or {}).get("no") for k in ("win", "place", "each_way"))
        for lab, b in (("early", eb), ("late", lb)):
            for k, v in (b or {}).items():
                if v is not None:
                    tot[lab][k][0] += v
                    tot[lab][k][1] += 1
    print(f"\nraces with both snapshots: {both}; picks changed between T-30 and the jump: {changed}")
    for lab in ("early", "late"):
        parts = []
        for k, (back, n) in tot[lab].items():
            if n:
                parts.append(f"{k}: {n} bets, ${back:.2f} back from ${n:.0f} ({100 * (back / n - 1):+.0f}%)")
        print(f"{lab:<5} {'; '.join(parts) or 'nothing graded yet'}")
    print("One unit a bet at Sportsbet's price; no intervals: too few races to separate from luck.")


if __name__ == "__main__":
    main()
