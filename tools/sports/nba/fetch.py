"""Download free NBA data into the raw folder (not committed).

    python3 tools/sports/nba/fetch.py [RAW_DIR]

Sources, all free, no login, no paid API:
  * sportsbookreviewsonline.com NBA scores-and-odds archive, 2007-08..2022-23 (final scores,
    open/close spread and total, closing moneyline). robots.txt allows it. 3 s between pages,
    every page cached, so a rerun downloads nothing.
  * ESPN box scores (tools/nba/espn_history.py, already in the repo) -> games.jsonl.gz: pass its
    path to build.py. Prop prices (DunkAPI, 2024-25) were bought earlier and are cached in
    dunk_cache.json; this script never calls a paid API.
"""

from __future__ import annotations

import os
import sys
import time
import urllib.request

RAW = "/tmp/claude-0/-home-user/418442d0-6a93-5b3f-a291-37c2b3744726/scratchpad/sports/nba/raw"
URL = "https://www.sportsbookreviewsonline.com/scoresoddsarchives/nba-odds-{s}"
SEASONS = [f"{y}-{str(y + 1)[2:]}" for y in range(2007, 2023)]


def get(url: str, path: str, sleep: float = 3.0) -> bool:
    if os.path.exists(path) and os.path.getsize(path) > 10000:
        return False
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (research, cached)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    with open(path, "wb") as f:
        f.write(data)
    time.sleep(sleep)
    return True


def main(raw: str = RAW) -> None:
    os.makedirs(raw, exist_ok=True)
    for s in SEASONS:
        new = get(URL.format(s=s), os.path.join(raw, f"sbro_{s}.html"))
        print(s, "downloaded" if new else "cached")


if __name__ == "__main__":
    main(*sys.argv[1:2])
