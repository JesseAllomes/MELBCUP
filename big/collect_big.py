"""Every Australian race meeting (no trials or jump-outs) from racing.com, newest month first:
fields, results, positions, sectionals, stewards' comments, final prices and Sportsbet and
Ladbrokes price histories. One gzipped JSON per meeting; resumable. 20 at a time."""
import gzip, json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rcq

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "meetings")
os.makedirs(OUT, exist_ok=True)
months = []
y, m = 2026, 10
while (y, m) >= (2022, 7):
    months.append((y, m))
    y, m = (y, m - 1) if m > 1 else (y - 1, 12)


def fetch(meet):
    path = os.path.join(OUT, f"{meet['date'][:10]}_{meet['id']}.json.gz")
    if os.path.exists(path):
        return 0
    d = rcq.gql(rcq.MEET, {"m": meet["id"]})
    data = (d.get("data") or {}).get("getMeeting")
    if data is None:
        print("no data", meet["id"], meet["venueName"], json.dumps(d.get("errors"))[:150], flush=True)
        return 0
    with gzip.open(path, "wt") as fh:
        json.dump(data, fh)
    time.sleep(0.3)
    return 1


for y, m in months:
    listing = (rcq.gql(rcq.MONTH, {"y": y, "m": m}).get("data") or {}).get("GetMeetingByMonth") or []
    meets = [x for x in listing if not x["isTrial"] and not x["isJumpOut"] and x["date"][:10] <= "2026-10-29"]
    with ThreadPoolExecutor(20) as pool:
        got = sum(pool.map(fetch, meets))
    print(f"{y}-{m:02d}: {len(meets)} meetings, {got} new", flush=True)
print("done", flush=True)
