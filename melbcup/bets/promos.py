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

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from melbcup.bets.allocate import race_picks
from melbcup.bets.offers import (
    MIN_EV_BUFFER,
    MoneyBack,
    Offer,
    PaysAsWinner,
    check_offer,
)
from melbcup.bets.singles import MIN_WIN_PROB, Single

# Owner-editable. Both maximum stakes are ASSUMED (the terms were not given).
PB_MAX_STAKE = 50.0
SB_MAX_STAKE = 50.0
SB_BONUS_VALUE = 0.75  # a bonus bet is worth this much per $1 of face value

ACCOUNT_OF = {"pointsbet": "pointsbet", "sportsbet": "sportsbet"}
BOOKMAKER_OF = {"pointsbet": "pointsbetau", "sportsbet": "sportsbet"}  # Single.bookmaker


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

    def applies(self, race) -> bool:
        if race.race_date != self.day:
            return False
        if self.race_name and self.race_name.lower() in (race.name or "").lower():
            return True
        return race.number in self.races

    def price(self, prices) -> float | None:
        if prices is None:
            return None
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
    return "PointsBet" if bookmaker == "pointsbet" else "Sportsbet"


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
            chk = check_offer(model, a.number, promo.offer(price), budget)
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
