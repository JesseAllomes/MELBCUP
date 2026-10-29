"""The model's record: one plain entry per resulted race, and a tally per bet type.

Entries are small dicts so they can be saved on the phone, sealed into the archive, and read
by a template without the model's objects. The pick in each category is what the app showed
before the race: its value bet when it had one, otherwise its top-rated runner.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from melbcup.bets import DayPicks
from melbcup.bets.grade import grade_day

CATEGORIES = (
    ("win", "Win"),
    ("place", "Place"),
    ("each_way", "Each way"),
    ("trifecta", "Trifecta"),
    ("first_four", "First four"),
)
_GRADE_LABELS = {
    "Win": "win",
    "Place": "place",
    "Each way": "each_way",
    "Trifecta": "trifecta",
    "First Four": "first_four",
}


def entries(day: DayPicks) -> list[dict]:
    """One entry per race that has a result."""
    grade = grade_day(day)
    by_race = {rp.model.race.number: rp for rp in day.races}
    out = []
    for g in grade.races:
        rp = by_race[g.race]
        race = rp.model.race
        picks: dict[str, dict] = {}
        for line in g.lines:
            key = _GRADE_LABELS[line.label]
            pick = {"hit": line.hit, "value": line.value, "returned": line.returned}
            if key in ("win", "place", "each_way"):
                s = rp.best[key]
                pick.update(no=s.number, name=s.name, chance=round(s.prob, 3), price=s.price)
            else:
                rec = next(
                    e
                    for e in (rp.trifectas if key == "trifecta" else rp.first_fours)
                    if e.recommended
                )
                pick.update(
                    legs=" / ".join(rec.leg_labels), combos=rec.combos, chance=round(rec.prob, 3)
                )
            picks[key] = pick
        out.append(
            {
                "date": race.race_date.isoformat(),
                "venue": race.venue,
                "race": race.number,
                "name": race.name or f"Race {race.number}",
                "distance": race.distance_m,
                "starters": len(race.starters),
                "at_sp": race.priced_from_sp,
                "placings": [[num, name, sp] for pos, num, name, sp in g.placings if pos <= 3],
                "top_rank_of_winner": g.top_rank_of_winner,
                "picks": picks,
            }
        )
    return out


def key(entry: dict) -> tuple[str, str, int]:
    return entry["date"], entry["venue"].lower(), entry["race"]


def merge(*sources: list[dict]) -> list[dict]:
    """Later sources win for the same race; newest meetings first, races in order."""
    merged: dict[tuple, dict] = {}
    for source in sources:
        for e in source:
            merged[key(e)] = e
    return sorted(merged.values(), key=lambda e: (_neg(e["date"]), e["venue"], e["race"]))


def _neg(iso: str) -> int:
    return -date.fromisoformat(iso).toordinal()


@dataclass
class Tally:
    label: str
    picks: int
    correct: int

    @property
    def failed(self) -> int:
        return self.picks - self.correct

    @property
    def rate(self) -> float | None:
        return self.correct / self.picks if self.picks else None


def tally(history: list[dict]) -> list[Tally]:
    out = []
    for cat, label in CATEGORIES:
        picked = [e["picks"][cat] for e in history if cat in e["picks"]]
        out.append(Tally(label, len(picked), sum(1 for p in picked if p["hit"])))
    return out


def meetings(history: list[dict]) -> list[tuple[str, str, list[dict]]]:
    """(date, venue, entries) groups, in the order of ``history``."""
    groups: list[tuple[str, str, list[dict]]] = []
    for e in history:
        if not groups or groups[-1][:2] != (e["date"], e["venue"]):
            groups.append((e["date"], e["venue"], []))
        groups[-1][2].append(e)
    return groups
