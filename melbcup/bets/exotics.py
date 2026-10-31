"""Quinella, Trifecta, First Four and Quaddies.

Tote dividends are not known before the race, so these report each structure's chance of
landing and its *fair* dividend (what a $1 unit must pay to break even). Compare that with the
TAB's approximate dividends on the day: a bigger approximate means the structure is value.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import permutations, product

from melbcup.model.probability import DISCOUNT, RaceModel


def seq_prob(win: dict[int, float], combo: tuple[int, ...]) -> float:
    """Probability of this exact finishing order (discounted Harville), any field size."""
    prob = 1.0
    used: set[int] = set()
    for i, n in enumerate(combo):
        exp = DISCOUNT[min(i, len(DISCOUNT) - 1)]
        denom = sum(p**exp for m, p in win.items() if m not in used)
        prob *= win[n] ** exp / denom
        used.add(n)
    return prob


@dataclass
class Exotic:
    kind: str  # quinella | trifecta | first_four | quaddie | early_quaddie
    title: str
    legs: list[list[int]]  # per finishing position, or per race for quaddies
    leg_labels: list[str]
    combos: int
    prob: float
    races: list[int]
    outlay: int | None = None
    flexi_pct: float | None = None
    recommended: bool = False

    @property
    def fair_dividend(self) -> float:
        """Break-even dividend for a $1 unit on every combination."""
        return self.combos / self.prob if self.prob > 0 else math.inf


UNORDERED = ("quinella",)  # kinds where the placegetters may finish in either order


def _ordered_combos(legs: list[list[int]]) -> list[tuple[int, ...]]:
    return [c for c in product(*legs) if len(set(c)) == len(c)]


def exotic_combos(kind: str, legs: list[list[int]]) -> set[tuple[int, ...]]:
    """Every combination a structure covers. Unordered kinds hold each set of runners once, as
    a sorted tuple, so a box of 3 is 3 quinellas and a box of 4 is 6."""
    combos = _ordered_combos(legs)
    if kind in UNORDERED:
        return {tuple(sorted(c)) for c in combos}
    return set(combos)


def combo_prob(win: dict[int, float], kind: str, combo: tuple[int, ...]) -> float:
    """Chance this combination lands: for unordered kinds, every finishing order of it."""
    if kind in UNORDERED:
        return sum(seq_prob(win, c) for c in permutations(combo))
    return seq_prob(win, combo)


def _structure(
    kind: str, title: str, win: dict[int, float], legs: list[list[int]], race: int
) -> Exotic:
    combos = sorted(exotic_combos(kind, legs))
    if all(leg == legs[0] for leg in legs):
        labels = ["Box " + ", ".join(map(str, sorted(legs[0])))]
    else:
        labels = [", ".join(map(str, leg)) for leg in legs]
    return Exotic(
        kind,
        title,
        legs,
        labels,
        len(combos),
        sum(combo_prob(win, kind, c) for c in combos),
        [race],
    )


def quinellas(model: RaceModel) -> list[Exotic]:
    win = model.win_probs()
    top = [a.number for a in model.ranked()]
    race = model.race.number
    if len(top) < 2:
        return []
    out = [_structure("quinella", "Top 2 (either order)", win, [[top[0]], [top[1]]], race)]
    if len(top) >= 3:
        out.append(_structure("quinella", "Box of top 3", win, [top[:3]] * 2, race))
    if len(top) >= 4:
        out.append(_structure("quinella", "Box of top 4", win, [top[:4]] * 2, race))
    if len(top) >= 5:
        out.append(_structure("quinella", "Standout top pick", win, [[top[0]], top[1:4]], race))
    return out


def trifectas(model: RaceModel) -> list[Exotic]:
    win = model.win_probs()
    top = [a.number for a in model.ranked()]
    race = model.race.number
    if len(top) < 3:
        return []
    out = []
    best = max(permutations(top[:5], 3), key=lambda c: seq_prob(win, c))
    out.append(
        _structure(
            "trifecta", "Straight (most likely order)", win, [[best[0]], [best[1]], [best[2]]], race
        )
    )
    if len(top) >= 4:
        out.append(_structure("trifecta", "Box of top 4", win, [top[:4]] * 3, race))
    if len(top) >= 6:
        out.append(
            _structure("trifecta", "Standout top pick", win, [[top[0]], top[1:4], top[1:6]], race)
        )
    if len(top) >= 5:
        out.append(
            _structure("trifecta", "Top 2 / top 4 / top 5", win, [top[:2], top[:4], top[:5]], race)
        )
    return out


def first_fours(model: RaceModel) -> list[Exotic]:
    win = model.win_probs()
    top = [a.number for a in model.ranked()]
    race = model.race.number
    if len(top) < 4:
        return []
    out = [_structure("first_four", "Box of top 4", win, [top[:4]] * 4, race)]
    if len(top) >= 6:
        out.append(
            _structure(
                "first_four",
                "Standout top pick",
                win,
                [[top[0]], top[1:4], top[1:6], top[1:6]],
                race,
            )
        )
    if len(top) >= 7:
        out.append(
            _structure(
                "first_four",
                "Top 2 / top 4 / top 6 / top 7",
                win,
                [top[:2], top[:4], top[:6], top[:7]],
                race,
            )
        )
    return out


def recommend(structures: list[Exotic], min_prob: float) -> Exotic | None:
    """The cheapest structure that still lands at least ``min_prob`` of the time; failing that,
    the one most likely to land. Marks it ``recommended``."""
    if not structures:
        return None
    ok = [e for e in structures if e.prob >= min_prob]
    pick = min(ok, key=lambda e: e.combos) if ok else max(structures, key=lambda e: e.prob)
    pick.recommended = True
    return pick


def quaddie(models: list[RaceModel], kind: str, title: str, max_combos: int) -> Exotic | None:
    """Pick runners per leg to maximise the chance of landing it within a combination budget.

    Greedy: keep adding the runner with the best gain in log-coverage per unit of log-combos.
    """
    if len(models) != 4 or any(not m.runners for m in models):
        return None
    ranked = [m.ranked() for m in models]
    legs = [[r[0]] for r in ranked]
    while True:
        combos = math.prod(len(leg) for leg in legs)
        best_gain, best_leg = 0.0, None
        for i, leg in enumerate(legs):
            if len(leg) >= len(ranked[i]):
                continue
            new_combos = combos // len(leg) * (len(leg) + 1)
            if new_combos > max_combos:
                continue
            cov = sum(a.win for a in leg)
            nxt = ranked[i][len(leg)]
            gain = math.log((cov + nxt.win) / cov) / math.log((len(leg) + 1) / len(leg))
            if gain > best_gain:
                best_gain, best_leg = gain, i
        if best_leg is None:
            break
        legs[best_leg].append(ranked[best_leg][len(legs[best_leg])])
    prob = math.prod(sum(a.win for a in leg) for leg in legs)
    numbers = [sorted(a.number for a in leg) for leg in legs]
    return Exotic(
        kind,
        title,
        numbers,
        [
            f"R{m.race.number}: " + ", ".join(map(str, n))
            for m, n in zip(models, numbers, strict=True)
        ],
        math.prod(len(n) for n in numbers),
        prob,
        [m.race.number for m in models],
    )


def quaddies(models: list[RaceModel]) -> list[Exotic]:
    """Main Quaddie = last four races; Early Quaddie = the four before those."""
    ordered = sorted(models, key=lambda m: m.race.number)
    out = []
    for kind, label, legs in (
        ("early_quaddie", "Early Quaddie", ordered[-8:-4]),
        ("quaddie", "Quaddie", ordered[-4:]),
    ):
        for budget in (24, 81):
            q = quaddie(legs, kind, f"{label} — up to {budget} combos", budget)
            if q:
                out.append(q)
    return out
