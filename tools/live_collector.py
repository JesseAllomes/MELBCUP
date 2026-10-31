"""Live racing.com observer for prospective evaluation: what was on offer, and when we saw it.

Append-only JSON lines, one object per observation. Every record carries
  obs_id    unique id: <run>:<sequence number within the run>
  obs_utc   when the request was sent (UTC, ms)
  recv_utc  when the response arrived (UTC, ms)
and keeps racing.com's own timestamps untouched inside the raw payload (race `time` / `officialTime`,
odds `updated` / `placeUpdated`, `flucsWin.updateTime`, all as racing.com sends them).

Record kinds:
  start / stop  one per collector run: version (sha256 of this file), run id, cadence; why it stopped
  cycle         heartbeat each poll cycle: planned and actual time, requests ok / failed, races watched.
                A missing cycle is an outage; nothing is ever back-filled for it.
  meetings      GetRaceMeetingsByStateNew rows for one state (meeting ids are racing.com's stable codes)
  schedule      getNoCacheRacesForMeet for one meeting: race id, number, time, officialTime, raceStatus,
                bettingStatus, status
  market        GetBettingData for one race: entry ids, horse codes, scratched, isLateScratching, emergency,
                win/place price and update time from Sportsbet (sb), Ladbrokes (lb), PointsBet (pb) and
                bet365 (bt); sb/lb fluctuation series when with_flucs is true (tote prices are not kept)
  field         getNoCacheRaceForm for one watched race, every SCHEDULE_EVERY cycles: declared weight
                (weightCarried, weight, weightPrevious), apprentice and allowed claim, jockey and
                jockeyChanged, handicapRating, gearChanges, barrier, scratched, emergency
  field_post    the same query once more when a race leaves the watch (resulted, abandoned or past the
                window): the values as racing.com holds them just after the race
  error         a failed request: what, why, HTTP status

A response identical to the previous one for the same request is stored as a marker instead of again:
data_sha256 plus same_as (the obs_utc of the last record that holds that data). The observation still
happened and is still timestamped; only the duplicate payload is dropped. Restore it by following same_as.

Later data never fills an earlier gap: a price first seen at recv_utc was available to us from recv_utc,
whatever provider timestamp it carries.

Files: <out>/<UTC date>/<run>-<seq>.jsonl.gz, each written once (from a .part file) and never changed.
With --git <repo>, each closed file is committed and pushed to the `live` branch (retrying); a file that cannot be pushed stays
in the work tree and goes with the next push.
"""
import argparse, datetime, gzip, hashlib, json, os, signal, socket, subprocess, sys, threading, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

URL = "https://graphql.rmdprod.racing.com/"
KEY = "da2-6nsi4ztsynar3l3frgxf77q5fe"           # racing.com's public web key (melbcup/sources/racingcom.py)
STATES = ("VIC", "NSW", "QLD", "SA", "WA", "TAS", "NT", "ACT")
MEL = ZoneInfo("Australia/Melbourne")
CYCLE_S = 60            # one poll cycle a minute
MEETINGS_EVERY = 15     # cycles between meeting-list refreshes
SCHEDULE_EVERY = 5      # cycles between schedule refreshes per meeting
FLUCS_EVERY = 15    # cycles between fluctuation-series pulls per watched race (full series are also in post-race dumps)
WATCH_BEFORE = 75 * 60  # watch a race from 75 min before its scheduled start ...
WATCH_AFTER = 30 * 60   # ... until 30 min after it, or until it is resulted / abandoned
DONE = ("result", "abandon", "final", "paying", "closed")
ROTATE_S = 15 * 60
REQUEST_TIMEOUT_S = 30  # per HTTP request; the Azure function lowers it (azure/function/collector_runtime.py)
DEADLINE = None         # epoch seconds after which gql() fails fast; set only by the Azure function

MEETINGS = ("query($s:String!,$b:Int!,$f:Int!,$u:String!){GetRaceMeetingsByStateNew(states:$s,daysBack:$b,"
            "daysForward:$f,userDate:$u){id venue date state isTrial isJumpOut}}")
SCHEDULE = ("query($m:ID!){getNoCacheRacesForMeet(meetCode:$m){id raceNumber time officialTime raceStatus "
            "bettingStatus status meetStatus distance}}")
FIELD = ("query($m:ID!,$n:Int!){getNoCacheRaceForm(meetCode:$m,raceNumber:$n){id formRaceEntries{id raceEntryNumber "
         "horseCode barrierNumber weightCarried weight weightPrevious apprentice apprenticeAllowedClaim apprenticeCanClaim "
         "jockeyCode jockeyName jockeyChanged handicapRating gearChanges scratched emergency}}}")
BOOKS = {"sb": "SB2", "lb": "LB2", "pb": "PB3", "bt": "BT"}   # fixed-price bookmakers: Sportsbet, Ladbrokes, PointsBet, bet365
PRICE = "oddsWin oddsPlace updated placeUpdated oddsIsFavouriteWin"


def market_query(flucs):
    books = " ".join(f'{a}: oddsByProvider(providerCode:"{c}"){{{PRICE}{" flucsWin{updateTime amount}" if flucs and a in ("sb", "lb") else ""}}}'
                     for a, c in BOOKS.items())
    return ("query($m:ID!,$n:Int!){GetBettingData(meetCode:$m,raceNumber:$n){id raceStatus bettingStatus time officialTime "
            "formRaceEntries{id raceEntryNumber horseCode horseName barrierNumber scratched isLateScratching emergency raceStatus "
            + books + "}}}")


def now():
    return datetime.datetime.now(datetime.timezone.utc)


def iso(t):
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Log:
    """append-only rotating JSONL.gz files. One lock serialises writes and rotation: the poll threads
    share this log (a race between two rotations once lost a cycle, 2026-10-30 02:22 UTC)."""

    def __init__(self, out, run, git):
        self.out, self.run, self.git, self.seq = out, run, git, 0
        self.fh = self.part = None
        self.opened = 0.0
        self.n = 0
        self.lock = threading.RLock()

    def write(self, rec):
        with self.lock:
            self._write(rec)

    def _write(self, rec):
        if self.fh is None or time.time() - self.opened >= ROTATE_S:
            self._close()
            day = now().strftime("%Y-%m-%d")
            os.makedirs(os.path.join(self.out, day), exist_ok=True)
            self.seq += 1
            self.part = os.path.join(self.out, day, f"{self.run}-{self.seq:04d}.jsonl.part")
            self.fh = open(self.part, "w")
            self.opened = time.time()
        self.n += 1
        rec = {"obs_id": f"{self.run}:{self.n:07d}", **rec}
        self.fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
        self.fh.flush()

    def close(self):
        with self.lock:
            self._close()

    def _close(self):
        if self.fh is None:
            return
        self.fh.close()
        final = self.part[: -len(".part")] + ".gz"
        with open(self.part, "rb") as src, gzip.open(final + ".tmp", "wb") as dst:
            dst.write(src.read())
        os.replace(final + ".tmp", final)
        os.remove(self.part)
        self.fh = None
        if self.git:
            push(self.git, final)


def push(repo, path):
    rel = os.path.relpath(path, repo)
    run = lambda *a: subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True)
    run("add", rel)
    run("commit", "-q", "-m", f"live: {rel}")
    for i in range(4):
        if run("push", "-q", "origin", "HEAD:refs/heads/live").returncode == 0:
            return
        time.sleep(2 ** (i + 1))
    print(f"push failed for {rel}; it goes with the next push", file=sys.stderr, flush=True)


def gql(query, variables):
    """(data, error, http_status, obs_utc, recv_utc)"""
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(URL, body, {"x-api-key": KEY, "content-type": "application/json"})
    sent = now()
    timeout = REQUEST_TIMEOUT_S
    if DEADLINE is not None:
        left = DEADLINE - time.time()
        if left <= 0.5:
            return None, "cycle deadline reached", None, sent, now()
        timeout = min(timeout, left)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw, status = resp.read(), resp.status
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}", exc.code, sent, now()
    except Exception as exc:  # timeouts, resets, DNS
        return None, f"{type(exc).__name__}: {exc}"[:300], None, sent, now()
    got = now()
    try:
        d = json.loads(raw)
    except ValueError:
        return None, "invalid JSON", status, sent, got
    if d.get("errors") and not d.get("data"):
        return None, json.dumps(d["errors"])[:300], status, sent, got
    return d.get("data"), None, status, sent, got


class Collector:
    def __init__(self, log, run):
        self.log, self.run = log, run
        self.meets = {}       # meet code -> meeting row (today and tomorrow, Melbourne)
        self.races = {}       # (meet, race number) -> schedule row
        self.cycle = 0
        self.requests = 0
        self.prev_watched = set()
        self.last = {}        # request key -> (data sha256, obs_utc of the record holding the data)

    def snapshot(self):
        """JSON-safe state for resuming short serverless invocations (additive; the GitHub runner never calls it).

        `last` (the same_as map) is deliberately not saved: every invocation writes self-contained files, so a marker
        never points into an earlier file (tools/live_validate.py and live_gaps.py resolve markers per run).
        Races are kept only for meetings still listed, so the state cannot grow past today and tomorrow."""
        return {
            "meets": self.meets,
            "races": [{"meet": meet, "number": number, "row": row}
                      for (meet, number), row in self.races.items() if meet in self.meets],
            "cycle": self.cycle,
            "requests": self.requests,
            "prev_watched": [list(key) for key in sorted(self.prev_watched)],
        }

    @classmethod
    def restore(cls, log, run, state):
        """Rebuild a collector from snapshot(); absent or malformed state is a cold start."""
        collector = cls(log, run)
        if not isinstance(state, dict):
            return collector
        try:
            collector.cycle = max(0, int(state.get("cycle") or 0))
            collector.requests = max(0, int(state.get("requests") or 0))
        except (TypeError, ValueError):
            collector.cycle = collector.requests = 0
        meets = state.get("meets")
        collector.meets = meets if isinstance(meets, dict) else {}
        for item in state.get("races") or []:
            try:
                row = item["row"]
                if isinstance(row, dict):
                    collector.races[(str(item["meet"]), int(item["number"]))] = row
            except (KeyError, TypeError, ValueError):
                continue
        for item in state.get("prev_watched") or []:
            try:
                collector.prev_watched.add((str(item[0]), int(item[1])))
            except (IndexError, KeyError, TypeError, ValueError):
                continue
        return collector

    def fetch(self, kind, query, variables, **meta):
        data, err, status, sent, got = gql(query, variables)
        self.requests += 1
        rec = dict(kind=kind if err is None else "error", what=kind, obs_utc=iso(sent), recv_utc=iso(got), run=self.run,
                   **meta, http_status=status)
        if err is None:
            blob = json.dumps(data, sort_keys=True, separators=(",", ":"))
            h = hashlib.sha256(blob.encode()).hexdigest()
            key = (query, json.dumps(variables, sort_keys=True))
            rec["data_sha256"] = h
            if key in self.last and self.last[key][0] == h:
                rec["same_as"] = self.last[key][1]
            else:
                rec["data"] = data
                self.last[key] = (h, rec["obs_utc"])
        else:
            rec["error"] = err
        self.log.write(rec)
        return data, err

    def refresh_meetings(self):
        today = now().astimezone(MEL).date()
        seen = {}
        for state in STATES:
            data, err = self.fetch("meetings", MEETINGS, {"s": state, "b": 0, "f": 1, "u": today.isoformat()}, state=state)
            for m in (data or {}).get("GetRaceMeetingsByStateNew") or []:
                if not m.get("isTrial") and not m.get("isJumpOut"):
                    seen[m["id"]] = m
            if err is not None and state in {m.get("state") for m in self.meets.values()}:
                seen.update({k: v for k, v in self.meets.items() if v.get("state") == state})   # keep watching on a failed refresh
        self.meets = seen

    def refresh_schedule(self, pool):
        today = now().astimezone(MEL).date().isoformat()
        codes = [c for c, m in self.meets.items() if (m.get("date") or "")[:10] <= today]
        for code, (data, err) in zip(codes, pool.map(lambda c: self.fetch("schedule", SCHEDULE, {"m": c}, meet_code=c), codes)):
            for r in (data or {}).get("getNoCacheRacesForMeet") or []:
                self.races[(code, r["raceNumber"])] = r

    def watched(self):
        t = time.time()
        out = []
        for key, r in self.races.items():
            try:
                start = datetime.datetime.fromisoformat((r.get("officialTime") or r["time"]).replace("Z", "+00:00")).timestamp()
            except (KeyError, TypeError, ValueError):
                continue
            status = " ".join(str(r.get(k) or "") for k in ("raceStatus", "bettingStatus")).lower()
            if start - WATCH_BEFORE <= t <= start + WATCH_AFTER and not any(w in status for w in DONE):
                out.append(key)
        return out

    def poll(self, pool):
        planned = self.cycle_planned
        started = now()
        before = self.requests
        if self.cycle % MEETINGS_EVERY == 0:
            self.refresh_meetings()
        if self.cycle % SCHEDULE_EVERY == 0:
            self.refresh_schedule(pool)
        keys = self.watched()
        flucs = self.cycle % FLUCS_EVERY == 0
        q = market_query(flucs)

        def one(key):
            data, err = self.fetch("market", q, {"m": key[0], "n": key[1]}, meet_code=key[0], race_number=key[1], with_flucs=flucs)
            race = (data or {}).get("GetBettingData") or {}
            if race:   # keep the schedule's status current between schedule refreshes
                self.races[key] = {**self.races[key], **{k: race.get(k) for k in ("raceStatus", "bettingStatus") if race.get(k)}}
            return err is None

        results = list(pool.map(one, keys))
        if self.cycle % SCHEDULE_EVERY == 0:   # declared weights, claims, jockeys and gear, as they stood before the race
            list(pool.map(lambda k: self.fetch("field", FIELD, {"m": k[0], "n": k[1]}, meet_code=k[0], race_number=k[1]), keys))
        left = sorted(self.prev_watched - set(keys))   # just left the watch: the values as held after the race
        list(pool.map(lambda k: self.fetch("field_post", FIELD, {"m": k[0], "n": k[1]}, meet_code=k[0], race_number=k[1]), left))
        self.prev_watched = set(keys)
        self.log.write(dict(kind="cycle", run=self.run, cycle=self.cycle, planned_utc=iso(planned), obs_utc=iso(started),
                            recv_utc=iso(now()), meetings=len(self.meets), races_watched=len(keys),
                            market_ok=sum(results), market_failed=len(results) - sum(results), with_flucs=flucs,
                            requests=self.requests - before))
        self.cycle += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="observation folder")
    ap.add_argument("--git", help="git work tree to commit and push closed files to")
    ap.add_argument("--max-seconds", type=float, default=20400)
    ap.add_argument("--run", default=os.environ.get("GITHUB_RUN_ID", "") + "-" + os.environ.get("GITHUB_RUN_ATTEMPT", ""))
    a = ap.parse_args()
    run = f"{now().strftime('%Y%m%dT%H%M%SZ')}-{a.run.strip('-') or socket.gethostname()}"
    log = Log(a.out, run, a.git)
    version = hashlib.sha256(open(__file__, "rb").read()).hexdigest()
    log.write(dict(kind="start", run=run, obs_utc=iso(now()), version=version, host=socket.gethostname(),
                   cadence=dict(cycle_s=CYCLE_S, meetings_every=MEETINGS_EVERY, schedule_every=SCHEDULE_EVERY,
                                flucs_every=FLUCS_EVERY, watch_before_s=WATCH_BEFORE, watch_after_s=WATCH_AFTER)))
    c = Collector(log, run)
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))   # a cancelled job still writes stop
    t0 = time.time()
    reason = "max-seconds reached"
    try:
        with ThreadPoolExecutor(8) as pool:
            while time.time() - t0 < a.max_seconds:
                c.cycle_planned = now()
                try:
                    c.poll(pool)
                except Exception as exc:   # a broken cycle is logged and the next one runs
                    log.write(dict(kind="error", what="cycle", run=run, obs_utc=iso(now()), recv_utc=iso(now()),
                                   error=f"{type(exc).__name__}: {exc}"[:300]))
                    c.cycle += 1
                time.sleep(max(1.0, CYCLE_S - (now() - c.cycle_planned).total_seconds()))
    except KeyboardInterrupt:
        reason = "interrupted"
    finally:
        log.write(dict(kind="stop", run=run, obs_utc=iso(now()), reason=reason, cycles=c.cycle))
        log.close()


if __name__ == "__main__":
    main()
