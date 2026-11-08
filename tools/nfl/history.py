"""Download free NFL player weekly game logs (nflverse release CSVs) to data/nfl/*.csv.gz.

Token-free, repeatable:  python tools/nfl/history.py [--from 2018] [--to 2026]
The current season is re-downloaded every run; finished seasons are kept once fetched.
Source: nflverse-data release "stats_player" (free, public).
"""

from __future__ import annotations

import argparse
import gzip
import sys
import urllib.error
import urllib.request
from pathlib import Path

URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{}.csv"
DIR = Path(__file__).resolve().parents[2] / "data" / "nfl"


def fetch(year: int, force: bool = False) -> Path | None:
    out = DIR / f"stats_player_week_{year}.csv.gz"
    if out.exists() and not force:
        return out
    try:
        raw = urllib.request.urlopen(URL.format(year), timeout=180).read()
    except urllib.error.URLError as e:
        print(f"{year}: {e}", file=sys.stderr)
        return None
    DIR.mkdir(parents=True, exist_ok=True)
    out.write_bytes(gzip.compress(raw, 9))
    print(f"{year}: {len(raw) // 1024} KB -> {out.name} ({out.stat().st_size // 1024} KB gz)")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="a", type=int, default=2018)
    ap.add_argument("--to", dest="b", type=int, default=2026)
    ap.add_argument("--refresh", action="store_true", help="re-download every season")
    a = ap.parse_args()
    for y in range(a.a, a.b + 1):
        fetch(y, force=a.refresh or y == a.b)


if __name__ == "__main__":
    main()
