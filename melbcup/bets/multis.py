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
        return self.ev > 0.05


def _candidates(model: RaceModel) -> list[Leg]:
    out = []
    for a in model.ranked():
        prices = model.race.prices.get(a.number)
        runner = model.race.runner(a.number)
        if a.win < MIN_LEG_PROB or not prices or not prices.sportsbet_win or runner is None:
            continue
        out.append(Leg(model.race.number, a.number, runner.name, a.win, prices.sportsbet_win))
    return out


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
