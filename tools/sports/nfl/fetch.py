"""Download free public NFL data (raw) into a cache dir outside git.

Sources (all free, no login, no paid API):
  * nflverse/nfldata games.csv on GitHub: results + closing moneyline/spread/total with prices.
  aussportsbetting.com/historical_data/nfl.xlsx was tried first but sits behind a Cloudflare
  challenge (HTTP 403 to non-browsers); we do not try to bypass that, so it is not used.
  No free historical player-prop lines exist, so player stats are not fetched.
Usage: python3 -m tools.sports.nfl.fetch [--raw DIR] [--refresh]
"""
from __future__ import annotations

import argparse
import hashlib
import time
from pathlib import Path

import httpx

RAW_DEFAULT = Path(
    "/tmp/claude-0/-home-user/418442d0-6a93-5b3f-a291-37c2b3744726/scratchpad/sports/nfl/raw"
)
SOURCES = {
    "games.csv": "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv",
}
UA = "melbcup-research/0.1 (polite, cached, one request per source)"


def fetch(raw: Path = RAW_DEFAULT, refresh: bool = False, sleep: float = 2.0) -> dict:
    raw.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, url in SOURCES.items():
        path = raw / name
        if path.exists() and not refresh:
            out[name] = path
            continue
        r = httpx.get(url, headers={"User-Agent": UA}, timeout=60, follow_redirects=True)
        r.raise_for_status()
        path.write_bytes(r.content)
        out[name] = path
        time.sleep(sleep)
    return out


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=RAW_DEFAULT)
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    for n, p in fetch(a.raw, a.refresh).items():
        print(n, p.stat().st_size, sha256(p)[:16])
