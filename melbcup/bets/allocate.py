"""Share the owner's day budget over every pick of the day (owner, 2026-11-01).

Each race has three horse picks, whether or not the price is good:
- Win: the win line paying closest to fair, among runners with at least a 4% chance (ties go to
  the likelier runner).
- Place: the runner most likely to place.
- Each way: the each-way line paying closest to fair, at a win price of $5 or more.

Money goes out in this order, and the day never goes over the budget:
1. Good-price lines (the model's value BETs) keep the model's own stake.
2. Recommended exotics keep their outlay (the quaddie counts in its first race).
3. What is left is shared over the remaining picks in proportion to the chance each pays
   (win: wins; place and each way: places), with no race taking more than RACE_CAP of the
   budget. Each way is rounded to an even number of dollars so it splits evenly.
"""

from __future__ import annotations

from dataclasses import dataclass

from melbcup.bets.singles import MIN_WIN_PROB, Single

RACE_CAP = 0.20
EW_MIN_WIN_PRICE = 5.0
KINDS = ("win", "place", "each_way")


@dataclass
class Pick:
    race: int
    kind: str  # "win" | "place" | "each_way"
    single: Single
    good_price: bool  # the model's value rule says BET at this price
    stake: int = 0

    @property
    def chance(self) -> float:
        """The chance this bet pays something: wins for a win bet, places otherwise."""
        return self.single.prob


def _closest_to_fair(lines: list[Single]) -> Single | None:
    priced = [s for s in lines if s.ev is not None]
    return max(priced, key=lambda s: (round(s.ev, 2), s.prob), default=None)


def race_picks(rp) -> dict[str, Single | None]:
    """The race's win, place and each-way picks, good price or not."""
    win_p = {a.number: a.win for a in rp.model.ranked()}
    wins = [s for s in rp.singles if s.kind == "win" and win_p.get(s.number, 0) >= MIN_WIN_PROB]
    places = [s for s in rp.singles if s.kind == "place" and s.price is not None]
    ews = [
        s for s in rp.singles
        if s.kind == "each_way" and (s.price or 0) >= EW_MIN_WIN_PRICE
        and win_p.get(s.number, 0) >= MIN_WIN_PROB
    ]
    return {
        "win": _closest_to_fair(wins),
        "place": max(places, key=lambda s: s.prob, default=None),
        "each_way": _closest_to_fair(ews),
    }


def _fixed(day) -> dict[int, float]:
    """Dollars already committed per race: value BETs and recommended exotics."""
    out: dict[int, float] = {}
    for rp in day.races:
        n = rp.model.race.number
        lines = {id(s): s for k in KINDS if (s := rp.best.get(k)) is not None and s.stake}
        out[n] = sum(s.stake for s in lines.values())
        out[n] += sum(e.outlay or 0 for e in rp.first_fours + rp.trifectas if e.recommended)
    for q in day.quaddies:
        if q.recommended and q.outlay and q.races:
            out[q.races[0]] = out.get(q.races[0], 0) + q.outlay
    return out


def allocate(day, budget: float) -> list[Pick]:
    """Every race's win, place and each-way pick with a whole-dollar stake from ``budget``."""
    fixed = _fixed(day)
    cap = RACE_CAP * budget
    picks: list[Pick] = []
    for rp in day.races:
        if rp.model.race.result is not None:
            continue
        n = rp.model.race.number
        for kind, s in race_picks(rp).items():
            if s is None:
                continue
            value = rp.best.get(kind)
            good = value is not None and value is s and bool(s.stake)
            picks.append(Pick(n, kind, s, good, int(s.stake) if good else 0))

    left = budget - sum(fixed.values())
    shared = [p for p in picks if not p.good_price]
    room = {n: max(0.0, cap - f) for n, f in fixed.items()}
    want = {id(p): 0.0 for p in shared}
    # Water-fill: share by chance, clamp races at their cap, share the rest again.
    open_ = list(shared)
    while left > 0.5 and open_:
        weight = sum(p.chance for p in open_)
        if weight <= 0:
            break
        spill = 0.0
        by_race: dict[int, list[Pick]] = {}
        for p in open_:
            by_race.setdefault(p.race, []).append(p)
        next_open: list[Pick] = []
        for race, group in by_race.items():
            ask = sum(left * p.chance / weight for p in group)
            give = min(ask, room.get(race, cap))
            for p in group:
                want[id(p)] += give * p.chance / sum(q.chance for q in group)
            room[race] = room.get(race, cap) - give
            spill += ask - give
            if room[race] > 0.5:
                next_open.extend(group)
        left = spill
        open_ = next_open
    for p in shared:
        dollars = want[id(p)]
        p.stake = int(dollars // 2 * 2) if p.kind == "each_way" else int(dollars)
    _spend_rounding(shared, want, budget - sum(fixed.values()), fixed, cap)
    return [p for p in picks if p.stake > 0]


def _spend_rounding(shared: list[Pick], want: dict, pot: float, fixed: dict, cap: float) -> None:
    """Rounding down leaves whole dollars unspent: give them back one at a time, first to any
    pick still at $0, then by the largest shortfall, never past a race's cap or the budget."""
    spare = int(pot - sum(p.stake for p in shared))
    in_race = {}
    for p in shared:
        in_race[p.race] = in_race.get(p.race, 0) + p.stake
    while spare > 0:
        fits = [
            p for p in shared
            if (step := 2 if p.kind == "each_way" else 1) <= spare
            and fixed.get(p.race, 0) + in_race[p.race] + step <= cap
        ]
        if not fits:
            return
        p = max(fits, key=lambda p: (p.stake == 0, want[id(p)] - p.stake))
        step = 2 if p.kind == "each_way" else 1
        p.stake += step
        in_race[p.race] += step
        spare -= step
