"""Seal already-downloaded meetings into docs/data so the app opens them without credits.

Input: pickles of ``(Race, {number: (sp, position)})`` from the backtest collection (pre-race
acceptances + FormFav form, with official SPs and placings). Each race's own result is taken
back out of the jockey and trainer figures (they were fetched afterwards), the result is
attached, and meetings are sealed with a key derived from PUNTERSEDGE_API_KEY.

    PUNTERSEDGE_API_KEY=... python tools/build_archive.py <dir-with-calib_YYYY-MM-DD.pkl>
"""

from __future__ import annotations

import glob
import os
import pickle
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from melbcup import archive  # noqa: E402
from melbcup.backtest import remove_result_leak  # noqa: E402
from melbcup.domain import Card, RaceResult  # noqa: E402
from melbcup.sources import apply_result  # noqa: E402

NOTE = "Saved meeting: judged at official starting prices; exotic dividends were not saved."


def cards_from(folder: str) -> list[Card]:
    by_meeting: dict[tuple, Card] = {}
    for path in sorted(glob.glob(os.path.join(folder, "calib_20*.pkl"))):
        for race, result in pickle.load(open(path, "rb")):
            remove_result_leak(race, result)
            finish = {n: pos for n, (_, pos) in result.items() if pos}
            sp = {n: s for n, (s, _) in result.items() if s}
            names = {r.number: r.name for r in race.runners if r.number in result}
            apply_result(race, RaceResult("final", finish, sp, names))
            key = (race.race_date, race.venue)
            card = by_meeting.setdefault(key, Card(race.venue, race.race_date, warnings=[NOTE]))
            card.condition = card.condition or race.condition
            card.races.append(race)
    for card in by_meeting.values():
        card.races.sort(key=lambda r: r.number)
    return list(by_meeting.values())


def main() -> None:
    secret = os.environ.get("PUNTERSEDGE_API_KEY")
    if not secret or len(sys.argv) != 2:
        sys.exit(__doc__)
    cards = cards_from(sys.argv[1])
    out = ROOT / "docs" / "data"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    archive.write(str(out), cards, secret)
    races = sum(len(c.races) for c in cards)
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"sealed {len(cards)} meetings, {races} races, {size / 1e6:.1f} MB into docs/data")


if __name__ == "__main__":
    main()
