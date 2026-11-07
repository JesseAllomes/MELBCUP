"""Bookmaker promotions as real bets (PROMOS=1).

Where a promo makes a bet better value than the race's plain Win pick, that promo bet IS the
race's Win bet: same runner slot, staked by the offers code, routed to that bookmaker and
labelled with the promo. ``PROMOS`` below is the one list to edit each day.

The value is melbcup.bets.offers' robust check: the offer is priced under six chance scenarios
and the worst expected value decides (it must clear MIN_EV_BUFFER). Every runner with the needed
price is valued; the one with the highest worst-case EV is the promo bet. It replaces the plain
Win pick only if that worst-case EV is above the plain pick's own EV.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from itertools import combinations, product

from melbcup.bets.allocate import race_picks
from melbcup.bets.multis import KIND_DIGIT, Leg, Multi, _candidates
from melbcup.bets.offers import (
    MIN_EV_BUFFER,
    MoneyBack,
    Offer,
    PaysAsWinner,
    check_offer,
)
from melbcup.bets.singles import MIN_WIN_PROB, Single
from melbcup.domain import betfair_net

# Owner-editable. Both maximum stakes are ASSUMED (the terms were not given).
PB_MAX_STAKE = 50.0
SB_MAX_STAKE = 50.0
SB_BONUS_VALUE = 0.75  # a bonus bet is worth this much per $1 of face value
# PointsBet "Daily Pay Back, Any Multi": stake back as a bonus bet if the multi loses. The
# criteria "multi loses" is ASSUMED (not given): any 2- or 3-leg multi that does not win.
PB_PAYBACK_MAX = 50.0
PB_PAYBACK_BONUS = 0.75  # the bonus bet is worth this much per $1 of stake
PB_PAYBACK_MIN_PROB = 0.25

# Betfair "Cash Back 2nd" (owner 2026-11-03: every race, cash; limit not known, so ASSUMED).
BF_CASHBACK_MAX = 50.0

ACCOUNT_OF = {"pointsbet": "pointsbet", "sportsbet": "sportsbet", "betfair": "betfair"}
BOOKMAKER_OF = {  # Single.bookmaker
    "pointsbet": "pointsbetau", "sportsbet": "sportsbet", "betfair": "betfair",
}


@dataclass(frozen=True)
class Promo:
    key: str
    bookmaker: str  # "pointsbet" | "sportsbet": the account the bet must be placed with
    label: str  # the pill reads "Promo: <label>"
    day: date
    max_stake: float
    offer: Callable[[float], Offer]  # the offer at the bookmaker's win price
    races: tuple[int, ...] = ()  # race numbers it runs in ...
    race_name: str = ""  # ... or a word in the race name, any case (e.g. "melbourne cup")
    depth: int = 3  # finishing places the offer looks at (2nd, 3rd...): keeps the check cheap

    def applies(self, race) -> bool:
        if race.race_date != self.day:
            return False
        if self.race_name and self.race_name.lower() in (race.name or "").lower():
            return True
        return race.number in self.races

    def price(self, prices) -> float | None:
        if prices is None:
            return None
        if self.bookmaker == "betfair":
            return prices.betfair_win
        return prices.pointsbet_win if self.bookmaker == "pointsbet" else prices.sportsbet_win


CUP_DAY = date(2026, 11, 3)  # Flemington, Tue 3 Nov 2026

PROMOS: tuple[Promo, ...] = (
    # PointsBet "Run 2nd, You Win": the Melbourne Cup win bet also pays as a winner if 2nd.
    Promo(
        "pb_run_2nd",
        "pointsbet",
        "Run 2nd, You Win",
        CUP_DAY,
        PB_MAX_STAKE,
        lambda price: PaysAsWinner(price, frozenset({1, 2})),
        race_name="melbourne cup",
        depth=2,
    ),
    # Sportsbet: win bet, stake back as a bonus bet (worth 0.75 per $1) if 2nd or 3rd. Races 1-2.
    Promo(
        "sb_bonus_back",
        "sportsbet",
        "bonus back 2nd-3rd",
        CUP_DAY,
        SB_MAX_STAKE,
        lambda price: MoneyBack(price, frozenset({2, 3}), SB_MAX_STAKE, SB_BONUS_VALUE),
        races=(1, 2),
    ),
    # Betfair "Cash Back 2nd": a back bet, stake back in cash if 2nd. Every race. Valued at the
    # Betfair price after commission (betfair_net); the page shows Betfair's own price.
    Promo(
        "bf_cash_back_2nd",
        "betfair",
        "cash back 2nd",
        CUP_DAY,
        BF_CASHBACK_MAX,
        lambda price: MoneyBack(betfair_net(price), frozenset({2}), BF_CASHBACK_MAX, 1.0),
        races=tuple(range(1, 13)),
        depth=2,
    ),
)


@dataclass
class PromoBet:
    promo: Promo
    number: int
    price: float
    ev: float  # worst-case EV per $1 over the scenarios
    stake: int  # sized by the offers code, capped at the promo's maximum stake

    @property
    def pill(self) -> str:
        return f"Promo: {self.promo.label}"

    @property
    def account(self) -> str:
        return ACCOUNT_OF[self.promo.bookmaker]

    @property
    def note(self) -> str:
        return (
            f"Worth {self.ev:+.2f} per $1 in the worst case, at {_bookie(self.promo.bookmaker)}'s "
            f"price (max stake ${self.promo.max_stake:g})."
        )

def _bookie(bookmaker: str) -> str:
    return {"pointsbet": "PointsBet", "betfair": "Betfair"}.get(bookmaker, "Sportsbet")


def best_promo_bet(
    model, promos, pointsbet: bool, budget: float | None
) -> PromoBet | None:
    """The best bet over ``promos`` for one race: every runner with the needed price valued, the
    highest worst-case EV that clears the buffer. A PointsBet promo needs ``pointsbet`` on."""
    if not budget or budget <= 0:
        return None
    race = model.race
    best: PromoBet | None = None
    for promo in promos:
        if not promo.applies(race) or (promo.bookmaker == "pointsbet" and not pointsbet):
            continue
        for a in model.ranked():
            price = promo.price(race.prices.get(a.number))
            if not price or price <= 1.0 or a.win < MIN_WIN_PROB:
                continue
            chk = check_offer(model, a.number, promo.offer(price), budget, places=promo.depth)
            if chk.verdict != "bet" or chk.min_ev is None or chk.min_ev < MIN_EV_BUFFER:
                continue
            stake = min(chk.stake, int(promo.max_stake))
            if stake > 0 and (best is None or chk.min_ev > best.ev):
                best = PromoBet(promo, a.number, price, chk.min_ev, stake)
    return best


def promo_win(rp, promos, pointsbet: bool, budget: float | None) -> Single | None:
    """The race's promo Win bet, or None when no promo beats the plain Win pick's EV."""
    bet = best_promo_bet(rp.model, promos, pointsbet, budget)
    if bet is None:
        return None
    plain = race_picks(rp)["win"]
    if plain is not None and plain.ev is not None and bet.ev <= plain.ev:
        return None
    race = rp.model.race
    a = rp.model.runners[bet.number]
    runner = race.runner(bet.number)
    prices = race.prices.get(bet.number)
    return Single(
        "win",
        race.number,
        bet.number,
        runner.name if runner else str(bet.number),
        a.win,
        bet.price,
        None,
        BOOKMAKER_OF[bet.promo.bookmaker],
        prices.sportsbet_win if prices else None,
        bet.ev,
        1 / a.win,
        True,
        a.reasons_for,
        stake=bet.stake,
        win_price=bet.price,
        shown=bet.price,
        promo=bet,
    )


# -- PointsBet "daily" promos (PROMOS=1 and POINTSBET=1 with a PointsBet amount) ----------------

BOOSTER_PILL = "PB booster: use here"
BOOSTER_NOTE = (
    "Use today's PointsBet racing-singles booster on this bet (biggest expected gain from a "
    "boost). Check the booster can be combined with any promo on it."
)


def booster_gain(stake: float, chance: float | None, price: float | None) -> float | None:
    """Expected gain of a single: stake x model chance x (price - 1)."""
    if not stake or not chance or not price:
        return None
    return stake * chance * (price - 1.0)


def _pointsbet_price(prices, kind: str) -> float | None:
    return prices.pointsbet_place if kind == "place" else prices.pointsbet_win


def payback_ev(prob: float, price: float) -> float:
    """EV of $1 on a multi that returns the stake as a bonus bet when it loses."""
    return prob * price + PB_PAYBACK_BONUS * (1.0 - prob) - 1.0


def _pareto(legs: list[Leg]) -> list[Leg]:
    """Legs no other leg of the race beats on both chance and price. Swapping a leg for one that
    is at least as likely and pays at least as much never lowers the multi's EV, so the others
    cannot be the best."""
    legs = sorted(legs, key=lambda g: (-g.prob, -g.price, g.number, g.kind))
    out: list[Leg] = []
    top = 0.0
    for g in legs:
        if g.price > top:
            out.append(g)
            top = g.price
    return out


def payback_multi(models) -> tuple[Multi, float] | None:
    """The 2- or 3-leg PointsBet multi (each leg a win or place bet in a different race, at
    PointsBet's prices) with the highest EV under Pay Back, chance at least PB_PAYBACK_MIN_PROB.
    Returns (multi, EV per $1), or None."""
    per_race: dict[int, list[Leg]] = {}
    for m in models:
        if legs := _pareto(_candidates(m, ("win", "place"), _pointsbet_price)):
            per_race[m.race.number] = legs
    best: tuple[tuple, Multi, float] | None = None
    for size in (2, 3):
        for races in combinations(sorted(per_race), size):
            for legs in product(*(per_race[r] for r in races)):
                prob = math.prod(g.prob for g in legs)
                if prob < PB_PAYBACK_MIN_PROB:
                    continue
                price = math.prod(g.price for g in legs)
                ev = payback_ev(prob, price)
                order = (ev, -size, tuple(-g.race for g in legs),
                         tuple(-g.number for g in legs), tuple(-KIND_DIGIT[g.kind] for g in legs))
                if best is None or order > best[0]:
                    best = (order, Multi(list(legs), prob, price, "pointsbet"), ev)
    return (best[1], best[2]) if best else None
