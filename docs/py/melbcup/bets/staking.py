"""Fractional Kelly stakes from an optional day budget. Advice only: nothing is ever placed."""

from __future__ import annotations

KELLY_FRACTION = 0.25
MAX_SHARE_PER_BET = 0.05
EXOTIC_SHARE = 0.01


def kelly_fraction(prob: float, price: float) -> float:
    """Share of bankroll for a bet at decimal ``price`` with win chance ``prob``."""
    if price <= 1.0 or prob <= 0.0:
        return 0.0
    edge = prob * price - 1.0
    if edge <= 0:
        return 0.0
    return min(MAX_SHARE_PER_BET, KELLY_FRACTION * edge / (price - 1.0))


def stake(budget: float | None, prob: float, price: float | None) -> int | None:
    """Whole-dollar stake, or None when there is no budget, no price or no edge."""
    if not budget or budget <= 0 or price is None:
        return None
    dollars = int(budget * kelly_fraction(prob, price))
    return dollars if dollars >= 1 else None


def each_way_stake(
    budget: float | None,
    p_win: float,
    win_price: float | None,
    p_place: float,
    place_price: float | None,
) -> int | None:
    """Total each-way outlay (half win, half place), sized on the weaker of the two parts."""
    if not budget or win_price is None or place_price is None:
        return None
    share = min(kelly_fraction(p_win, win_price), kelly_fraction(p_place, place_price))
    dollars = int(budget * share * 2) // 2 * 2  # an even number so it splits evenly
    return dollars if dollars >= 2 else None


def exotic_stake(budget: float | None, combos: int) -> tuple[int, float] | None:
    """(outlay, flexi %) for an exotic: a small fixed share of the budget spread over combos."""
    if not budget or combos <= 0:
        return None
    outlay = int(budget * EXOTIC_SHARE)
    if outlay < 1:
        return None
    return outlay, round(100.0 * outlay / combos, 1)


def scale_to_budget(stakes: list[int], budget: float | None) -> list[int]:
    """Shrink every stake in proportion when together they would exceed the budget."""
    total = sum(stakes)
    if not budget or total <= budget:
        return stakes
    factor = budget / total
    return [int(x * factor) for x in stakes]
