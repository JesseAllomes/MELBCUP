"""Download the free AFL results + bookmaker odds workbook (cached, polite, one request).

Source: the aussportsbetting.com "historical AFL results and odds" workbook. The site itself
answers scripted clients with a Cloudflare 403, and we do not try to evade that. A public
GitHub mirror (dclaz/bscores, data/afl.xlsx) carries a copy of the same file, so that is what
we fetch. The workbook's terms say "personal use only, do not make this data available on
another website": raw files and odds-bearing tables are therefore never committed or published.
Columns: results, average-of-books h2h odds, and single-book open/close (Pinnacle until
2018-04-02, bet365 after) for head-to-head, line and total.
Usage: python -m tools.sports.afl.fetch [--force]
"""

import argparse
import time
import urllib.request

from tools.sports.afl.paths import RAW

URL = "https://raw.githubusercontent.com/dclaz/bscores/main/data/afl.xlsx"
DEST = RAW / "afl_mirror.xlsx"
UA = "melbcup-research/0.1 (personal research; single cached download)"


def fetch(force: bool = False, sleep: float = 2.0) -> str:
    RAW.mkdir(parents=True, exist_ok=True)
    if DEST.exists() and not force:
        return str(DEST)
    time.sleep(sleep)
    req = urllib.request.Request(URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        DEST.write_bytes(r.read())
    return str(DEST)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    print(fetch(ap.parse_args().force))
