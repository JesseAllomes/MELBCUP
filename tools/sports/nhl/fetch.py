"""Download free NHL data into the raw folder (not committed).

    python3 tools/sports/nhl/fetch.py [RAW_DIR]

Sources, all free, no login, no paid API:
  * sportsbookreviewsonline.com NHL scores-and-odds archive (final score, open/close moneyline,
    puck line with price, open/close total with price). robots.txt does not bar it. 3 s between
    pages. (aussportsbetting.com is behind a Cloudflare challenge: not fetched, not bypassed.)
  * api-web.nhle.com public NHL API, weekly schedule/score pages: regulation/OT/shootout flag
    and cross-check of scores. 4 parallel workers, 0.6 s pause after each call.
Every page is cached, so a rerun downloads nothing. No free historical NHL player-prop prices
exist, so no prop dataset is built.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

RAW = "/tmp/claude-0/-home-user/418442d0-6a93-5b3f-a291-37c2b3744726/scratchpad/sports/nhl/raw"
URL = "https://www.sportsbookreviewsonline.com/scoresoddsarchives/nhl-odds-{s}/"
API = "https://api-web.nhle.com/v1/schedule/{d}"
SEASONS = [f"{y}-{str(y + 1)[2:]}" for y in range(2007, 2023)]  # archive ends in Nov 2022
SLUG = {"2020-21": "2021"}  # the archive's odd name for the 2020-21 season page
UA = {"User-Agent": "Mozilla/5.0 (research, cached)"}


def get(url: str, path: str, sleep: float, min_size: int = 200, need: bytes = b"") -> bool:
    if os.path.exists(path) and os.path.getsize(path) > min_size:
        return False
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
            data = r.read()
    except Exception as e:  # missing season page etc.
        print("  skip", url, e)
        return False
    if need and need not in data:  # e.g. a redirect to the home page: do not cache it
        print("  skip (no table)", url)
        return False
    with open(path, "wb") as f:
        f.write(data)
    time.sleep(sleep)
    return True


def season_weeks(season: str):
    y = int(season[:4])
    d = dt.date(y, 9, 25)
    end = dt.date(y + 1, 6, 30)
    while d <= end:
        yield d
        d += dt.timedelta(days=7)


def main(raw: str = RAW) -> None:
    os.makedirs(os.path.join(raw, "api"), exist_ok=True)
    for s in SEASONS:
        new = get(URL.format(s=SLUG.get(s, s)), os.path.join(raw, f"sbro_nhl_{s}.html"), 3.0, 10000,
                  b"<td")
        print(s, "downloaded" if new else "cached/none", flush=True)
    days = [d for s in SEASONS for d in season_weeks(s)]
    # 4 workers, each pausing 0.6 s after every call: a few calls a second at most
    with ThreadPoolExecutor(4) as ex:
        n = sum(ex.map(lambda d: get(API.format(d=d), os.path.join(raw, "api", f"{d}.json"),
                                     0.6), days))
    print("api weeks downloaded", n, "of", len(days), flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:2])
