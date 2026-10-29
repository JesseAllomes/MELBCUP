"""The model's record: one plain entry per resulted race, and a tally per bet type.

Entries are small dicts so they can be saved on the phone, sealed into the archive, and read
by a template without the model's objects. The picks are what the app showed before the race:
the runners most likely to win and to place, whatever their price, and the value bets, which
exist only when a price beat the runner's chance by enough.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from melbcup.bets import CONFIDENCE, KINDS, LABELS, VALUE_KINDS, DayPicks, confidence
from melbcup.bets.grade import grade_day

CATEGORIES = tuple(LABELS.items())


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
            key = line.kind
            pick = {"hit": line.hit, "value": line.value, "returned": line.returned}
            if key in KINDS:
                s = rp.best[key]
                pick.update(
                    no=s.number,
                    name=s.name,
                    chance=round(s.prob, 3),
                    price=s.price,
                    place_price=s.place_price if key not in ("win", "top_win") else None,
                    estimated=s.estimated,
                )
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
    returned: float | None = None  # total back from $1 on every pick; None if a dividend is unknown

    @property
    def failed(self) -> int:
        return self.picks - self.correct

    @property
    def rate(self) -> float | None:
        return self.correct / self.picks if self.picks else None

    @property
    def profit(self) -> float | None:
        """Return per $1 staked, after the stake: +0.05 means 5c profit per dollar."""
        if self.returned is None or not self.picks:
            return None
        return self.returned / self.picks - 1.0


def shown(entry: dict, cat: str) -> dict | None:
    """The entry's pick in one category, if the app made one. Value categories hold only
    value bets: entries saved before the two lines split also kept a fallback there."""
    pick = entry["picks"].get(cat)
    if pick is None or (cat in VALUE_KINDS and not pick.get("value")):
        return None
    return pick


def tally(history: list[dict]) -> list[Tally]:
    """One row per pick type."""
    out = []
    for cat, label in CATEGORIES:
        picked = [p for e in history if (p := shown(e, cat)) is not None]
        valued = [p for p in picked if p.get("returned") is not None]
        unknown_wins = sum(1 for p in picked if p["hit"] and p.get("returned") is None)
        # A stray missing price is left out; missing dividends throughout (exotics on saved
        # races) leave the figure blank rather than count only the losses.
        returned = None
        if valued and unknown_wins <= 0.02 * len(picked):
            returned = sum(p["returned"] for p in valued) * len(picked) / len(valued)
        out.append(Tally(label, len(picked), sum(1 for p in picked if p["hit"]), returned))
    return out


def by_confidence(history: list[dict]) -> list[Tally]:
    """The most likely winner's record in each confidence band (from its chance)."""
    out = []
    for _, label in CONFIDENCE:
        picked = [
            p
            for e in history
            if (p := e["picks"].get("top_win")) and confidence(p["chance"]) == label
        ]
        valued = [p["returned"] for p in picked if p.get("returned") is not None]
        returned = sum(valued) * len(picked) / len(valued) if valued else None
        out.append(
            Tally(f"{label} confidence", len(picked), sum(p["hit"] for p in picked), returned)
        )
    return out


def meetings(history: list[dict]) -> list[tuple[str, str, list[dict]]]:
    """(date, venue, entries) groups, in the order of ``history``."""
    groups: list[tuple[str, str, list[dict]]] = []
    for e in history:
        if not groups or groups[-1][:2] != (e["date"], e["venue"]):
            groups.append((e["date"], e["venue"], []))
        groups[-1][2].append(e)
    return groups
