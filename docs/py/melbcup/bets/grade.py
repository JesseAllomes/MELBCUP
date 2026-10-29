"""Judge the picks against the official result: did each one land, and what would $1 have
returned at the price the app showed?"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product

from melbcup.bets import DayPicks, RacePicks
from melbcup.bets.exotics import Exotic
from melbcup.bets.singles import Single
from melbcup.domain import RaceResult


@dataclass
class Graded:
    label: str
    selection: str
    hit: bool
    returned: float | None  # per $1 staked; None when the dividend is unknown
    value: bool = False  # the app flagged it as a value bet

    @property
    def profit(self) -> float | None:
        return None if self.returned is None else self.returned - 1.0


@dataclass
class RaceGrade:
    race: int
    result: RaceResult
    placings: list[tuple[int, int, str, float | None]]  # position, number, name, SP
    top_pick: int | None
    top_rank_of_winner: int | None
    lines: list[Graded] = field(default_factory=list)


@dataclass
class DayGrade:
    races: list[RaceGrade]
    quaddies: list[Graded]
    multis: list[Graded]

    @property
    def graded(self) -> int:
        return len(self.races)

    @property
    def top_pick_wins(self) -> int:
        return sum(1 for r in self.races if r.top_rank_of_winner == 1)

    @property
    def top_pick_places(self) -> int:
        return sum(
            1
            for r in self.races
            if r.top_pick is not None and 0 < r.result.finish.get(r.top_pick, 99) <= 3
        )

    def tally(self, lines: list[Graded]) -> tuple[int, int, float]:
        """(bets, winners, profit per $1 each) over lines with a known return."""
        known = [g for g in lines if g.returned is not None]
        return len(known), sum(g.hit for g in known), sum(g.profit for g in known)

    @property
    def value_lines(self) -> list[Graded]:
        return [g for r in self.races for g in r.lines if g.value]

    @property
    def exotic_lines(self) -> list[Graded]:
        return [g for r in self.races for g in r.lines if g.label in ("Trifecta", "First Four")]


def _single(s: Single, result: RaceResult, places_paid: int) -> Graded:
    """Win at the win price shown; place at the place price shown, or the official fixed place
    dividend when the app had none; each way as half of each."""
    pos = result.finish.get(s.number)
    won = pos == 1
    placed = pos is not None and pos <= places_paid
    place_price = s.place_price or result.place_dividend.get(s.number)
    # A losing part returns nothing whatever its price; a winning part is unknown without one.
    win_part = (s.price if won else 0.0) if s.kind != "place" else None
    place_part = place_price if placed else 0.0
    if s.kind == "win":
        hit, ret = won, win_part
    elif s.kind == "place":
        hit, ret = placed, place_part
    else:
        hit = placed
        ret = None if win_part is None or place_part is None else 0.5 * (win_part + place_part)
    label = {"win": "Win", "place": "Place", "each_way": "Each way"}[s.kind]
    return Graded(label, f"{s.number}. {s.name}", hit, ret, s.value)


def _exotic(e: Exotic, result: RaceResult, code: str, depth: int) -> Graded:
    actual = tuple(result.placegetters(depth))
    combos = {c for c in product(*e.legs) if len(set(c)) == len(c)}
    hit = len(actual) == depth and actual in combos
    dividend = result.exotics.get(code)
    if not hit:
        ret = 0.0
    elif dividend and dividend[0] == actual:
        ret = dividend[1] / e.combos  # $1 spread across every combination (flexi)
    else:
        ret = None
    label = "Trifecta" if code == "TF" else "First Four"
    return Graded(label, f"{e.title}: {' / '.join(e.leg_labels)}", hit, ret)


def grade_race(rp: RacePicks) -> RaceGrade | None:
    race = rp.model.race
    result = race.result
    if result is None or not result.finish:
        return None
    ranked = [a.number for a in rp.model.ranked()]
    winner = next((n for n, p in result.finish.items() if p == 1), None)
    placings = [
        (pos, n, result.names.get(n, str(n)), result.sp.get(n))
        for n, pos in sorted(result.finish.items(), key=lambda kv: kv[1])
        if pos <= 4
    ]
    g = RaceGrade(
        race.number,
        result,
        placings,
        ranked[0] if ranked else None,
        ranked.index(winner) + 1 if winner in ranked else None,
    )
    for kind in ("win", "place", "each_way"):
        s = rp.best.get(kind)
        if s is not None:
            g.lines.append(_single(s, result, race.places_paid))
    for group, code, depth in ((rp.trifectas, "TF", 3), (rp.first_fours, "FF", 4)):
        rec = next((e for e in group if e.recommended), None)
        if rec is not None:
            g.lines.append(_exotic(rec, result, code, depth))
    return g


def grade_day(day: DayPicks) -> DayGrade:
    races = [g for rp in day.races if (g := grade_race(rp)) is not None]
    by_race = {rp.model.race.number: rp.model.race for rp in day.races}

    def winner(n: int) -> int | None:
        r = by_race.get(n)
        if r is None or r.result is None:
            return None
        return next((num for num, p in r.result.finish.items() if p == 1), None)

    quaddies = []
    for q in day.quaddies:
        winners = [winner(n) for n in q.races]
        if any(w is None for w in winners):
            continue
        hit = all(w in leg for w, leg in zip(winners, q.legs, strict=True))
        quaddies.append(Graded(q.title, " / ".join(q.leg_labels), hit, 0.0 if not hit else None))
    multis = []
    for m in day.multis:
        winners = [winner(leg.race) for leg in m.legs]
        if any(w is None for w in winners):
            continue
        hit = all(w == leg.number for w, leg in zip(winners, m.legs, strict=True))
        sel = " + ".join(f"R{leg.race} {leg.number}. {leg.name}" for leg in m.legs)
        multis.append(
            Graded(f"{len(m.legs)}-leg multi", sel, hit, m.price if hit else 0.0, m.value)
        )
    return DayGrade(races, quaddies, multis)
