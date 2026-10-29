"""Turn race models into the day's picks, one place for the web layer to read."""

from __future__ import annotations

from dataclasses import dataclass

from melbcup.bets.exotics import Exotic, first_fours, quaddies, recommend, trifectas
from melbcup.bets.multis import Multi, multis
from melbcup.bets.singles import Single, best, singles
from melbcup.bets.staking import each_way_stake, exotic_stake, scale_to_budget, stake
from melbcup.model.probability import RaceModel

KINDS = ("top_win", "top_place", "win", "place", "each_way")
VALUE_KINDS = ("win", "place", "each_way")
LABELS = {
    "top_win": "Most likely win",
    "top_place": "Most likely place",
    "win": "Value win",
    "place": "Value place",
    "each_way": "Value each way",
    "trifecta": "Trifecta",
    "first_four": "First four",
}
# How sure the top pick is, from its own chance. Held out on 1,131 races (Sep-Oct 2026) the top
# pick won 50% at 40%+, 33% at 30-40% and 26% under 30%. Requiring the odds, the form model
# and FormFav to agree made the High band smaller, not more accurate, so it is not used.
CONFIDENCE = ((0.40, "High"), (0.30, "Medium"), (0.0, "Low"))


def confidence(chance: float) -> str:
    return next(label for floor, label in CONFIDENCE if chance >= floor)


MIN_HIT = {"trifecta": 0.15, "first_four": 0.06, "quaddie": 0.12, "early_quaddie": 0.12}


@dataclass
class RacePicks:
    model: RaceModel
    best: dict[str, Single | None]
    singles: list[Single]
    trifectas: list[Exotic]
    first_fours: list[Exotic]


@dataclass
class DayPicks:
    races: list[RacePicks]
    quaddies: list[Exotic]
    multis: list[Multi]
    budget: float | None


def _single_stake(s: Single, budget: float | None) -> int | None:
    if not s.value:
        return None
    if s.kind == "each_way":
        return each_way_stake(budget, 1.0 / s.fair_price, s.price, s.prob, s.place_price)
    return stake(budget, s.prob, s.price)


def _size_exotic(e: Exotic, budget: float | None) -> None:
    sized = exotic_stake(budget, e.combos)
    e.outlay, e.flexi_pct = sized if sized else (None, None)


def build_picks(models: list[RaceModel], budget: float | None = None) -> DayPicks:
    races = []
    for m in sorted(models, key=lambda m: m.race.number):
        sl = singles(m)
        rp = RacePicks(
            model=m,
            best={k: best(sl, k) for k in KINDS},
            singles=sl,
            trifectas=trifectas(m),
            first_fours=first_fours(m),
        )
        for s in rp.best.values():
            if s is not None:
                s.stake = _single_stake(s, budget)
        for group in (rp.trifectas, rp.first_fours):
            if chosen := recommend(group, MIN_HIT[group[0].kind] if group else 0):
                _size_exotic(chosen, budget)
        races.append(rp)
    q = quaddies(models)
    for kind in ("early_quaddie", "quaddie"):
        if chosen := recommend([e for e in q if e.kind == kind], MIN_HIT[kind]):
            _size_exotic(chosen, budget)
    mu = multis(models)
    for x in mu:
        x.stake = stake(budget, x.prob, x.price) if x.value else None
    day = DayPicks(races=races, quaddies=q, multis=mu, budget=budget)
    _fit_budget(day)
    return day


def _staked(day: DayPicks) -> list[tuple[object, str]]:
    """Every object carrying a stake, with the attribute that holds it."""
    out: list[tuple[object, str]] = []
    for rp in day.races:
        out += [(s, "stake") for s in rp.best.values() if s is not None and s.stake]
        out += [(e, "outlay") for e in rp.trifectas + rp.first_fours if e.outlay]
    out += [(e, "outlay") for e in day.quaddies if e.outlay]
    out += [(m, "stake") for m in day.multis if m.stake]
    # one runner can be best win and best each-way: count each object once
    seen, unique = set(), []
    for obj, attr in out:
        if id(obj) not in seen:
            seen.add(id(obj))
            unique.append((obj, attr))
    return unique


def _fit_budget(day: DayPicks) -> None:
    items = _staked(day)
    scaled = scale_to_budget([getattr(o, a) for o, a in items], day.budget)
    for (obj, attr), value in zip(items, scaled, strict=True):
        setattr(obj, attr, value or None)
        if attr == "outlay" and isinstance(obj, Exotic):
            obj.flexi_pct = round(100.0 * value / obj.combos, 1) if value else None
