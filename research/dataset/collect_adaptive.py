"""Every Australian race meeting (no trials or jump-outs) from racing.com, newest month first,
with self-tuning speed: start at 20 requests in flight, add 2 after every 100 clean requests,
drop 1 (and pause that worker) whenever racing.com throttles or errors. Resumable."""
import gzip, json, os, sys, threading, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rcq

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "meetings")
os.makedirs(OUT, exist_ok=True)
START, STEP_UP, STEP_DOWN, CLEAN_RUN, MIN, MAX = 100, 2, 1, 100, 2, 100


class Throttle:
    """How many requests may be in flight; grows while clean, shrinks on trouble."""

    def __init__(self):
        self.limit, self.active, self.clean = START, 0, 0
        self.cv = threading.Condition()

    def __enter__(self):
        with self.cv:
            while self.active >= self.limit:
                self.cv.wait()
            self.active += 1

    def __exit__(self, *exc):
        with self.cv:
            self.active -= 1
            self.cv.notify_all()

    def ok(self):
        with self.cv:
            self.clean += 1
            if self.clean >= CLEAN_RUN and self.limit < MAX:
                self.limit, self.clean = self.limit + STEP_UP, 0
                print(f"speed up -> {self.limit} in flight", flush=True)
                self.cv.notify_all()

    def trouble(self, why):
        with self.cv:
            self.limit, self.clean = max(MIN, self.limit - STEP_DOWN), 0
            print(f"throttled ({why}) -> {self.limit} in flight", flush=True)


T = Throttle()


def post(query, variables):
    """(data, trouble): trouble is a short reason when racing.com refused, throttled or failed."""
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(rcq.URL, body, {"x-api-key": rcq.KEY, "content-type": "application/json"})
    try:
        with T:
            with urllib.request.urlopen(req, timeout=60) as resp:
                d = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except Exception as exc:  # timeouts, resets
        return None, type(exc).__name__
    errs = d.get("errors") or []
    if any("throttl" in json.dumps(e).lower() or "rate" in json.dumps(e).lower() for e in errs):
        return None, "rate limited"
    return d, None


def get(query, variables):
    for attempt in range(6):
        d, why = post(query, variables)
        if why is None:
            T.ok()
            return d
        T.trouble(why)
        time.sleep(3 * (attempt + 1))
    return {}


def fetch(meet):
    path = os.path.join(OUT, f"{meet['date'][:10]}_{meet['id']}.json.gz")
    if os.path.exists(path):
        return 0
    data = (get(rcq.MEET, {"m": meet["id"]}).get("data") or {}).get("getMeeting")
    if data is None:
        print("no data", meet["id"], meet["venueName"], flush=True)
        return 0
    with gzip.open(path, "wt") as fh:
        json.dump(data, fh)
    return 1


months = []
y, m = 2026, 10
while (y, m) >= (2022, 7):
    months.append((y, m))
    y, m = (y, m - 1) if m > 1 else (y - 1, 12)
with ThreadPoolExecutor(MAX) as pool:  # threads wait on the throttle; it sets the real speed
    for y, m in months:
        listing = (get(rcq.MONTH, {"y": y, "m": m}).get("data") or {}).get("GetMeetingByMonth") or []
        meets = [x for x in listing if not x["isTrial"] and not x["isJumpOut"] and x["date"][:10] <= "2026-10-29"]
        t = time.time()
        got = sum(pool.map(fetch, meets))
        print(f"{y}-{m:02d}: {len(meets)} meetings, {got} new in {time.time() - t:.0f}s at {T.limit} in flight", flush=True)
print("done", flush=True)
