"""Cross-race win multis at one bookmaker (Sportsbet: multis must sit with one bookie).

Legs are treated as independent, which they are: different races.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations, product

from melbcup.model.probability import RaceModel

MIN_LEG_PROB = 0.15  # multis built on long shots are lottery tickets, not edges
MIN_MULTI_PROB = {2: 0.08, 3: 0.03}
MULTI_EDGE = 0.05  # a multi is value (a "Good price") when price x chance beats 1 by this much
DAY_MULTIS = 5  # "Multi picks for the day"


@dataclass
class Leg:
    race: int
    number: int
    name: str
    prob: float
    price: float


@dataclass
class Multi:
    legs: list[Leg]
    prob: float
    price: float
    bookmaker: str
    stake: int | None = None

    @property
    def ev(self) -> float:
        return self.prob * self.price - 1.0

    @property
    def value(self) -> bool:
        return self.ev > MULTI_EDGE

    @property
    def good_price(self) -> bool:
        """Price x chance is at least 1 plus the value edge the multis use."""
        return self.prob * self.price >= 1.0 + MULTI_EDGE

    @property
    def race(self) -> int:
        """The first leg's race: where the multi counts toward a race's share of the day."""
        return self.legs[0].race

    @property
    def key(self) -> int:
        return multi_key([(leg.race, leg.number) for leg in self.legs])


def multi_key(legs: list[tuple[int, int]]) -> int:
    """An int that names a multi by its legs ((race, runner) pairs): two digits each, so a
    multi can be kept in the placed cookie, whose records hold one int key."""
    return int("".join(f"{race:02d}{number:02d}" for race, number in legs))


def key_legs(key: int) -> list[tuple[int, int]]:
    """The (race, runner) pairs ``multi_key`` packed; [] for a key that is not one."""
    text = str(key)
    text = text.zfill(-(-len(text) // 4) * 4)
    legs = [(int(text[i : i + 4][:2]), int(text[i : i + 4][2:])) for i in range(0, len(text), 4)]
    return legs if 2 <= len(legs) <= 3 and all(r > 0 and n > 0 for r, n in legs) else []


def _leg(model: RaceModel, number: int) -> Leg | None:
    a = next((a for a in model.ranked() if a.number == number), None)
    prices = model.race.prices.get(number)
    runner = model.race.runner(number)
    if a is None or not prices or not prices.sportsbet_win or runner is None:
        return None
    return Leg(model.race.number, number, runner.name, a.win, prices.sportsbet_win)


def _candidates(model: RaceModel) -> list[Leg]:
    legs = (_leg(model, a.number) for a in model.ranked() if a.win >= MIN_LEG_PROB)
    return [leg for leg in legs if leg is not None]


def multis(models: list[RaceModel], *, max_results: int = 3) -> list[Multi]:
    """Best 2- and 3-leg Sportsbet win multis by expected value, value or not."""
    per_race = {m.race.number: c for m in models if (c := _candidates(m))}
    out: list[Multi] = []
    for size in (2, 3):
        best_for_size: list[Multi] = []
        for races in combinations(sorted(per_race), size):
            for legs in product(*(per_race[r] for r in races)):
                prob = math.prod(leg.prob for leg in legs)
                if prob < MIN_MULTI_PROB[size]:
                    continue
                price = math.prod(leg.price for leg in legs)
                best_for_size.append(Multi(list(legs), prob, price, "sportsbet"))
        best_for_size.sort(key=lambda m: m.ev, reverse=True)
        out.extend(best_for_size[:max_results])
    return out


def _multi(legs: list[Leg]) -> Multi:
    return Multi(
        legs, math.prod(g.prob for g in legs), math.prod(g.price for g in legs), "sportsbet"
    )


def build_multi(models: list[RaceModel], key: int) -> Multi | None:
    """The Sportsbet multi a key names, at today's chances and prices; None if a leg's race or
    price is gone."""
    by_race = {m.race.number: m for m in models}
    legs = []
    for race, number in key_legs(key):
        leg = _leg(by_race[race], number) if race in by_race else None
        if leg is None:
            return None
        legs.append(leg)
    if not legs:
        return None
    return _multi(legs)


def day_multis(models: list[RaceModel], n: int = DAY_MULTIS) -> list[Multi]:
    """The ``n`` likeliest 2- and 3-leg Sportsbet win multis over the races given (the ones
    still to run), likeliest first. Each leg is a different race; every multi has its own legs."""
    per_race = {m.race.number: c for m in models if (c := _candidates(m))}
    found: dict[int, Multi] = {}
    for size in (2, 3):
        for races in combinations(sorted(per_race), size):
            for legs in product(*(per_race[r] for r in races)):
                m = _multi(list(legs))
                found[m.key] = m
    return sorted(found.values(), key=lambda m: (-m.prob, m.key))[:n]
