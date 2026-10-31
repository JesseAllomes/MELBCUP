"""Quinella bar backtest: coverage gate.

Goal: choose the quinella minimum-chance bar (melbcup/bets MIN_HIT["quinella"]) from saved
meetings by settling the app's own recommended quinella at the real QN dividend.

This script first audits the saved meetings in docs/data (read through melbcup.archive) for
what the backtest needs: pre-race prices, placings and a stored quinella (QN) dividend. If no QN
dividend is stored it says so and stops with exit status 2. It never estimates a dividend.
The settlement and fit/test split are deliberately not written until real dividends exist, so
nothing here can be tuned on invented numbers.

Run from the repo root:  python research/quinella_bar.py [archive_root]
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from zoneinfo import ZoneInfo

from melbcup.archive import Archive

MELB = ZoneInfo("Australia/Melbourne")
QN_CODES = ("QN", "QU", "QUINELLA", "Q")  # key spellings the feed could use for the quinella


def main(root: str = "docs/data") -> int:
    base = Path(root)

    def read(p: str) -> str | None:
        f = base / p
        return f.read_text() if f.is_file() else None

    arch = Archive(read)
    if not arch.open:
        print(f"no archive at {base}")
        return 1
    days = sorted(arch._index)
    c = Counter()
    exotic_keys: Counter = Counter()
    price_times: Counter = Counter()
    for day in days:
        for venue in arch.venues(day):
            card = arch.load(day, venue)
            c["meetings"] += 1
            for race in card.races:
                c["races"] += 1
                res = race.result
                if res is None:
                    continue
                c["with result"] += 1
                if res.finish:
                    c["with placings"] += 1
                if res.place_dividend:
                    c["with place dividends"] += 1
                exotic_keys.update(res.exotics)
                if race.prices:
                    c["with prices"] += 1
                if race.priced_from_sp:
                    c["prices are the official SP (post-race)"] += 1
                if race.prices_at is not None:
                    price_times[race.prices_at.astimezone(MELB).strftime("%H:%M")] += 1
                    c["with a price timestamp"] += 1
                if race.start_time is not None:
                    c["with a start time"] += 1
    print(f"saved meeting days (Melbourne dates): {days[0]} to {days[-1]}, {len(days)} days")
    for k, v in c.items():
        print(f"  {k}: {v}")
    print(f"  exotic dividend codes stored on any race: {dict(exotic_keys) or 'none'}")
    print(f"  price timestamps: {dict(price_times) or 'none stored'}")
    qn = sum(n for k, n in exotic_keys.items() if k.upper() in QN_CODES)
    if not qn:
        print(
            "\nSTOP: no quinella (QN) dividend is stored on any saved race "
            "(tools/build_archive.py: 'exotic dividends were not saved'). "
            "Settling quinellas would need invented dividends, so no bar is chosen."
        )
        return 2
    print(f"\n{qn} races have a QN dividend, but the backtest is not implemented in this audit.")
    return 3


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:2]))
