"""Cross-race multis at one bookmaker (Sportsbet: multis must sit with one bookie).

``multis`` are win multis; the day's multis (``day_multis``) take each leg as a win or a place
bet. Legs are treated as independent, which they are: different races.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Iterator
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
    kind: str = "win"  # "win" | "place": the leg's bet, at its Sportsbet price


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
        return multi_key([(leg.race, leg.number, leg.kind) for leg in self.legs])


KIND_DIGIT = {"win": 1, "place": 2}
DIGIT_KIND = {v: k for k, v in KIND_DIGIT.items()}


def multi_key(legs: list[tuple[int, int, str]]) -> int:
    """An int that names a multi by its legs ((race, runner, "win" | "place")): five digits
    each, so a multi can be kept in the placed cookie, whose records hold one int key. A win leg
    and a place leg on the same runner give different keys."""
    return int("".join(f"{race:02d}{number:02d}{KIND_DIGIT[kind]}" for race, number, kind in legs))


def key_legs(key: int) -> list[tuple[int, int, str]]:
    """The (race, runner, kind) triples ``multi_key`` packed; [] for a key that is not one."""
    text = str(key)
    text = text.zfill(-(-len(text) // 5) * 5)
    legs = []
    for i in range(0, len(text), 5):
        race, number, digit = int(text[i : i + 2]), int(text[i + 2 : i + 4]), int(text[i + 4])
        if race <= 0 or number <= 0 or digit not in DIGIT_KIND:
            return []
        legs.append((race, number, DIGIT_KIND[digit]))
    return legs if 2 <= len(legs) <= 3 and len({r for r, _, _ in legs}) == len(legs) else []


def _sportsbet_price(prices, kind: str) -> float | None:
    return prices.sportsbet_place if kind == "place" else prices.sportsbet_win


def _leg(
    model: RaceModel, number: int, kind: str = "win", price_of=_sportsbet_price
) -> Leg | None:
    """``price_of(prices, kind)`` picks the bookmaker's price for the leg (Sportsbet's default)."""
    a = next((a for a in model.ranked() if a.number == number), None)
    prices = model.race.prices.get(number)
    runner = model.race.runner(number)
    price = prices and price_of(prices, kind)
    if a is None or not price or runner is None:
        return None
    return Leg(model.race.number, number, runner.name, a.place if kind == "place" else a.win,
               price, kind)


def _candidates(
    model: RaceModel, kinds: tuple[str, ...] = ("win",), price_of=_sportsbet_price
) -> list[Leg]:
    """Legs worth a multi in this race: a win and/or place bet on each runner with a price (by
    default Sportsbet's) for it and at least MIN_LEG_PROB of landing."""
    legs = (_leg(model, a.number, k, price_of) for a in model.ranked() for k in kinds)
    return [leg for leg in legs if leg is not None and leg.prob >= MIN_LEG_PROB]


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
    for race, number, kind in key_legs(key):
        leg = _leg(by_race[race], number, kind) if race in by_race else None
        if leg is None:
            return None
        legs.append(leg)
    if not legs:
        return None
    return _multi(legs)


def day_multis(models: list[RaceModel], n: int = DAY_MULTIS) -> list[Multi]:
    """The ``n`` likeliest 2- and 3-leg Sportsbet multis over the races given (the ones still to
    run), likeliest first. Each leg is a win or a place bet (mixed is fine) in a different race;
    every multi has its own legs.

    Only each race's ``n`` likeliest legs (and any tied with the n-th) can be in the answer: a
    multi using a leg with ``n`` strictly likelier legs in its race is beaten by the ``n``
    multis that swap that leg for one of them. Pruning to those keeps a big card (ten open
    races, win and place legs) to a few thousand multis instead of a few hundred thousand,
    and only the winners are built."""
    per_race: dict[int, list[Leg]] = {}
    for m in models:
        legs = sorted(_candidates(m, ("win", "place")), key=lambda g: -g.prob)
        if legs:
            floor = legs[min(n, len(legs)) - 1].prob
            per_race[m.race.number] = [g for g in legs if g.prob >= floor]

    def order(legs: tuple[Leg, ...]) -> tuple:
        # the same order as (-prob, multi_key): a shorter key is a smaller int, and keys of one
        # length compare as their (race, runner, kind digit) triples
        return (
            -math.prod(g.prob for g in legs),
            len(legs),
            tuple((g.race, g.number, KIND_DIGIT[g.kind]) for g in legs),
        )

    def every() -> Iterator[tuple[Leg, ...]]:
        for size in (2, 3):
            for races in combinations(sorted(per_race), size):
                yield from product(*(per_race[r] for r in races))

    return [_multi(list(legs)) for legs in heapq.nsmallest(n, every(), key=order)]
