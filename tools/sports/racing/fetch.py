"""Download raw racing data into RAW (kept out of git).

Sources (all free, public, no login):
 1. racing.com getMeeting dumps, every Australian meeting 2022-07-01..2026-10-29. These were
    collected once with research/dataset/collect_adaptive.py and are preserved on this repo's
    `data` branch (big/meetings/). We restore them from there instead of hitting racing.com
    again (no extra load on their API).
 2. Betfair Data Scientists public ANZ thoroughbred BSP files (monthly csv / yearly zip),
    https://betfair-datascientists.github.io/data/assets/ (robots.txt allows; cached, 2 s sleep).
"""

import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import RAW  # noqa: E402

BF = "https://betfair-datascientists.github.io/data/assets/"
YEARS = range(2020, 2026)
MONTHS_2026 = range(1, 10)


def restore_meetings(repo: str) -> None:
    if os.path.isdir(os.path.join(RAW, "big", "meetings")):
        return
    subprocess.run(["git", "-C", repo, "fetch", "origin", "data"], check=True)
    os.makedirs(RAW, exist_ok=True)
    arc = subprocess.Popen(
        ["git", "-C", repo, "archive", "origin/data", "big/meetings"], stdout=subprocess.PIPE
    )
    subprocess.run(["tar", "x", "-C", RAW], stdin=arc.stdout, check=True)


def get(url: str, dest: str) -> None:
    if os.path.exists(dest) and os.path.getsize(dest) > 1000:
        return
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "melbcup-research/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest + ".part", "wb") as f:
        f.write(r.read())
    os.replace(dest + ".part", dest)
    time.sleep(2)


def fetch_betfair() -> None:
    names = [f"ANZ_Thoroughbreds_{y}.zip" for y in YEARS]
    names += [f"ANZ_Thoroughbreds_2026_{m:02d}.csv" for m in MONTHS_2026]
    for n in names:
        try:
            get(BF + n, os.path.join(RAW, "betfair", "raw", n))
        except Exception as exc:  # a missing month is not fatal
            print("skip", n, exc)


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    repo = subprocess.check_output(
        ["git", "-C", here, "rev-parse", "--show-toplevel"], text=True
    ).strip()
    restore_meetings(repo)
    fetch_betfair()
    print("raw ready under", RAW)
