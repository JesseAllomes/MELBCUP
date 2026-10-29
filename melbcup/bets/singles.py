"""Win, Place and Each-way: expected value of the best fixed price on offer."""

from __future__ import annotations

from dataclasses import dataclass

from melbcup.model.probability import RaceModel, top_k_probs

VALUE_EDGE = 0.05  # demand a 5% edge before calling a price "value": the model is not perfect
MIN_WIN_PROB = 0.04  # ignore extreme long shots: their probabilities are the least reliable
# Estimates are least certain at big prices (the favourite-long-shot bias), so the edge a price
# must show grows with it: +5% at $2, +10% at $6, capped at +25% from $22 up.
EDGE_PER_DOLLAR = 0.01
MAX_EDGE = 0.25
# Backtest, 1,131 races (Sep-Oct 2026), held-out days: edges of +5% to +40% returned a profit at
# SP; edges above +40% and runners over $21 lost heavily. A huge edge means the model is wrong,
# not that the bet is good, so neither is ever called value.
MAX_BELIEVABLE_EDGE = 0.40
MAX_VALUE_PRICE = 21.0
# Each-way is for runners at a price where the place half matters: not favourites.
EW_MIN_PRICE = 5.0
# A place pick needs a real chance of running a place.
MIN_PLACE_PROB = 0.35


PLACE_MARGIN = 1.40  # place odds imply ~1.4x the fair place chance (measured on live quotes)


def estimate_place_price(market_place_prob: float) -> float:
    """Fixed place odds a bookmaker would offer, from the market's fair chance of placing
    (Harville on the margin-free win prices) and the place market's measured margin. Used only
    for races judged at starting prices, where no place market was recorded."""
    if market_place_prob <= 0:
        return 1.01
    return max(1.01, round(1.0 / (PLACE_MARGIN * market_place_prob), 2))


def required_edge(price: float) -> float:
    return min(MAX_EDGE, VALUE_EDGE + EDGE_PER_DOLLAR * max(0.0, price - 1.0))


def _is_value(
    ev: float | None, price: float | None, win_prob: float, win_price: float | None
) -> bool:
    return (
        ev is not None
        and price is not None
        and win_price is not None
        and win_prob >= MIN_WIN_PROB
        and win_price <= MAX_VALUE_PRICE
        and required_edge(price) <= ev <= MAX_BELIEVABLE_EDGE
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
    win_price: float | None = None
    estimated: bool = False  # the place price is estimated from the starting price


def _ev(prob: float, price: float | None) -> float | None:
    return None if price is None else prob * price - 1.0


def singles(model: RaceModel) -> list[Single]:
    race = model.race
    out: list[Single] = []
    market_place: dict[int, float] = {}
    if race.priced_from_sp:
        market = {n: p.consensus_prob for n, p in race.prices.items() if p.consensus_prob}
        if market:
            market_place = top_k_probs(market, race.places_paid)
    for a in model.ranked():
        runner = race.runner(a.number)
        prices = race.prices.get(a.number)
        name = runner.name if runner else str(a.number)
        win_q = prices.best_win if prices else None
        place_q = prices.best_place if prices else None
        win_price = win_q.price if win_q else None
        place_price = place_q.price if place_q else None
        estimated = False
        if place_price is None and a.number in market_place:
            place_price, estimated = estimate_place_price(market_place[a.number]), True
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
                _is_value(ev_win, win_price, a.win, win_price),
                a.reasons_for,
                win_price=win_price,
                estimated=estimated,
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
                _is_value(ev_place, place_price, a.win, win_price),
                a.reasons_for,
                win_price=win_price,
                estimated=estimated,
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
                _is_value(ev_ew, win_price, a.win, win_price),  # the bar follows the win price
                a.reasons_for,
                win_price=win_price,
                estimated=estimated,
            )
        )
    return out


def best(single_list: list[Single], kind: str) -> Single | None:
    """The pick of one kind in a race. Each kind answers its own question:

    win       the best win value; failing that, the top-rated runner
    place     the best place value among runners with a real chance of placing (35%+) and a
              win price of $21 or less; without place prices, the likeliest placegetter
    each way  the best each-way value among runners from $5 to $21, where the place half
              matters; none when no runner is in that range
    """
    pool = [s for s in single_list if s.kind == kind]
    if kind == "place":
        priced = [
            s
            for s in pool
            if s.price is not None
            and s.prob >= MIN_PLACE_PROB
            and (s.win_price is None or s.win_price <= MAX_VALUE_PRICE)
        ]
        if not priced:
            return max(pool, key=lambda s: s.prob) if pool else None
        pool = priced
    elif kind == "each_way":
        pool = [
            s
            for s in pool
            if s.price is not None
            and s.place_price is not None
            and EW_MIN_PRICE <= s.price <= MAX_VALUE_PRICE
        ]
    if not pool:
        return None
    value = [s for s in pool if s.value]
    if value:
        return max(value, key=lambda s: s.ev or 0.0)
    if kind == "win" or all(s.ev is None for s in pool):
        return max(pool, key=lambda s: 1 / s.fair_price)
    return max(pool, key=lambda s: s.ev if s.ev is not None else -1.0)
