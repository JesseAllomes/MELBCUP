"""Win, Place and Each-way: expected value of the best fixed price on offer."""

from __future__ import annotations

from dataclasses import dataclass

from melbcup.model.probability import RaceModel

VALUE_EDGE = 0.05  # demand a 5% edge before calling a price "value": the model is not perfect
MIN_WIN_PROB = 0.04  # ignore extreme long shots: their probabilities are the least reliable
# Estimates are least certain at big prices (the favourite-long-shot bias), so the edge a price
# must show grows with it: +5% at $2, +10% at $6, capped at +25% from $22 up.
EDGE_PER_DOLLAR = 0.01
MAX_EDGE = 0.25


def required_edge(price: float) -> float:
    return min(MAX_EDGE, VALUE_EDGE + EDGE_PER_DOLLAR * max(0.0, price - 1.0))


def _is_value(ev: float | None, price: float | None, win_prob: float) -> bool:
    return (
        ev is not None
        and price is not None
        and win_prob >= MIN_WIN_PROB
        and ev >= required_edge(price)
    )


@dataclass
class Single:
    kind: str  # "win" | "place" | "each_way"
    race: int
    number: int
    name: str
    prob: float  # chance this bet collects (win, place; each-way: place)
    price: float | None  # win price, or place price for "place"
    place_price: float | None
    bookmaker: str | None
    sportsbet: float | None
    ev: float | None  # expected return per $1 staked, minus the $1
    fair_price: float
    value: bool
    reasons: list[str]
    stake: int | None = None


def _ev(prob: float, price: float | None) -> float | None:
    return None if price is None else prob * price - 1.0


def singles(model: RaceModel) -> list[Single]:
    race = model.race
    out: list[Single] = []
    for a in model.ranked():
        runner = race.runner(a.number)
        prices = race.prices.get(a.number)
        name = runner.name if runner else str(a.number)
        win_q = prices.best_win if prices else None
        place_q = prices.best_place if prices else None
        win_price = win_q.price if win_q else None
        place_price = place_q.price if place_q else None
        sb_win = prices.sportsbet_win if prices else None
        sb_place = prices.sportsbet_place if prices else None

        ev_win = _ev(a.win, win_price)
        ev_place = _ev(a.place, place_price)
        out.append(
            Single(
                "win",
                race.number,
                a.number,
                name,
                a.win,
                win_price,
                place_price,
                win_q.bookmaker if win_q else None,
                sb_win,
                ev_win,
                1 / a.win,
                _is_value(ev_win, win_price, a.win),
                a.reasons_for,
            )
        )
        out.append(
            Single(
                "place",
                race.number,
                a.number,
                name,
                a.place,
                place_price,
                place_price,
                place_q.bookmaker if place_q else None,
                sb_place,
                ev_place,
                1 / a.place if a.place else float("inf"),
                _is_value(ev_place, place_price, a.win),
                a.reasons_for,
            )
        )
        # Each-way at fixed odds: half the stake on each part, each at the best price for it.
        ev_ew = None if ev_win is None or ev_place is None else 0.5 * (ev_win + ev_place)
        out.append(
            Single(
                "each_way",
                race.number,
                a.number,
                name,
                a.place,
                win_price,
                place_price,
                win_q.bookmaker if win_q else None,
                sb_win,
                ev_ew,
                1 / a.win,
                _is_value(ev_ew, win_price, a.win),  # the bar follows the win price
                a.reasons_for,
            )
        )
    return out


def best(single_list: list[Single], kind: str) -> Single | None:
    """Best bet of one kind in a race: the highest-EV value bet; if none, the top-rated runner
    so the page can say "no value at current prices" rather than show nothing."""
    pool = [s for s in single_list if s.kind == kind]
    if not pool:
        return None
    value = [s for s in pool if s.value]
    if value:
        return max(value, key=lambda s: s.ev or 0.0)
    # Without a value bet: win and each-way follow the win chance, place follows place chance.
    return max(pool, key=lambda s: s.prob if kind == "place" else 1 / s.fair_price)
