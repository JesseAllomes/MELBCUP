"""Settle the owner's recorded bets against the results (pure functions, no I/O).

A recorded bet (allocate.Placed) settles once its race has a result with a finish order.
Price: the price the owner took when given (the win price for win and each way, the place price
for place), otherwise the current price at that bookmaker. An each-way place half uses the
bookmaker's current place price; if there is none, 1 + (win - 1) / 4. Betfair commission comes
off profit. Today's promos (promos.PROMOS, on the races they apply to):

- Betfair "cash back 2nd": a win bet that runs 2nd gets the stake back in cash.
- PointsBet "Run 2nd, You Win": a Melbourne Cup win bet that runs 2nd pays as a winner.
- Sportsbet "bonus back 2nd-3rd": a win bet in races 1-2 that runs 2nd or 3rd earns a bonus bet
  of min(stake, 50). A bonus bet is not cash: it is reported apart, never in profit or loss.

Multis settle when every leg's race has a result. Exotics (quinella, trifecta, first four,
quaddies) are not settled by the app.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from melbcup.bets.allocate import Placed
from melbcup.bets.multis import key_legs
from melbcup.bets.promos import PROMOS, SB_MAX_STAKE
from melbcup.domain import BETFAIR_COMMISSION

NOT_SETTLED = "Not settled by the app"
HORSE_KINDS = ("win", "place", "each_way")


@dataclass(frozen=True)
class Settled:
    bet: Placed
    status: str  # "settled" | "pending" (no result yet) | "manual" (an exotic)
    returns: float = 0.0  # cash back, stake included
    bonus: float = 0.0  # bonus bet earned (not cash)
    note: str = ""

    @property
    def profit(self) -> float:
        return round(self.returns - self.bet.stake, 2) if self.status == "settled" else 0.0


def _pending(bet: Placed, note: str = "") -> Settled:
    if bet.kind in HORSE_KINDS or bet.kind == "multi":
        return Settled(bet, "pending", note=note)
    return Settled(bet, "manual", note=NOT_SETTLED)  # an exotic


def _current(race, number: int, account: str, kind: str) -> float | None:
    prices = race.prices.get(number) if race else None
    return getattr(prices, f"{account}_{kind}", None) if prices else None


def _promo(key: str, race) -> bool:
    return any(p.key == key and p.applies(race) for p in PROMOS)


def _net(account: str, stake: float, returns: float) -> float:
    """Betfair takes commission off the profit."""
    if account == "betfair" and returns > stake:
        return stake + (returns - stake) * (1.0 - BETFAIR_COMMISSION)
    return returns


def _hit(pos: int | None, kind: str, places_paid: int) -> bool:
    if pos is None:
        return False
    return pos == 1 if kind == "win" else pos <= places_paid


def _single(bet: Placed, races: dict) -> Settled:
    race = races.get(bet.race)
    result = race.result if race else None
    if result is None or not result.finish:
        return _pending(bet)
    pos = result.finish.get(bet.key)
    stake, acct = bet.stake, bet.account
    win = bet.price or _current(race, bet.key, acct, "win")
    returns, bonus, missing = 0.0, 0.0, False
    if bet.kind == "win":
        if pos == 1:
            returns, missing = (stake * win, False) if win else (0.0, True)
        elif pos == 2 and acct == "betfair" and _promo("bf_cash_back_2nd", race):
            returns = float(stake)
        elif pos == 2 and acct == "pointsbet" and _promo("pb_run_2nd", race):
            returns, missing = (stake * win, False) if win else (0.0, True)
        if pos in (2, 3) and acct == "sportsbet" and _promo("sb_bonus_back", race):
            bonus = float(min(stake, SB_MAX_STAKE))
    elif bet.kind == "place":
        if _hit(pos, "place", race.places_paid):
            place = bet.price or _current(race, bet.key, acct, "place")
            returns, missing = (stake * place, False) if place else (0.0, True)
    else:  # each way: the stake is the total of two equal halves
        half = stake / 2
        if pos == 1:
            if win:
                returns += half * win
            else:
                missing = True
        if _hit(pos, "place", race.places_paid):
            place = (
                getattr(bet, "place_price", None)
                or _current(race, bet.key, acct, "place")
                or (1 + (win - 1) / 4 if win else None)
            )
            if place:
                returns += half * place
            else:
                missing = True
    if missing:
        return _pending(bet, "No price: not settled")
    return Settled(bet, "settled", round(_net(acct, stake, returns), 2), bonus)


def _multi(bet: Placed, races: dict) -> Settled:
    legs = key_legs(bet.key)
    rs = [races.get(r) for r, _, _ in legs]
    if not legs or any(r is None or r.result is None or not r.result.finish for r in rs):
        return _pending(bet)
    won = all(
        _hit(r.result.finish.get(n), kind, r.places_paid)
        for (_, n, kind), r in zip(legs, rs, strict=True)
    )
    returns = 0.0
    if won:
        price = bet.price
        if not price:
            prices = [
                _current(r, n, "sportsbet", kind) for (_, n, kind), r in zip(legs, rs, strict=True)
            ]
            if not all(prices):
                return _pending(bet, "No price: not settled")
            price = 1.0
            for p in prices:
                price *= p
        returns = bet.stake * price
    return Settled(bet, "settled", round(returns, 2))


@dataclass(frozen=True)
class Extra:
    """Any other bet the owner recorded by hand. A "multi" has ``legs`` of (race, runner, "win" |
    "place") and the total decimal ``odds`` taken; an "other" bet (quinella, a quaddie, anything)
    has no legs and is settled by the owner typing ``result``, the total amount returned."""

    kind: str  # "multi" | "other"
    legs: tuple[tuple[int, int, str], ...]
    account: str
    stake: float
    odds: float
    label: str = ""
    result: float | None = None


def settle_extra(x: Extra, races: dict) -> Settled:
    """A multi wins (stake x odds) when every leg hits, loses as soon as one leg's race has a
    result where the leg missed, else is pending. No Betfair commission (multis are bookmaker
    bets). An "other" bet is pending until the owner types the amount returned."""
    bet = Placed(0, "extra", 0, x.account, x.stake)  # race 0: it counts in the day, not a race
    if x.kind != "multi":
        if x.result is None:
            return Settled(bet, "pending")
        return Settled(bet, "settled", round(x.result, 2))
    hits = []
    for race_no, number, kind in x.legs:
        race = races.get(race_no)
        if race is None or race.result is None or not race.result.finish:
            hits.append(None)
            continue
        hits.append(_hit(race.result.finish.get(number), kind, race.places_paid))
    if any(h is False for h in hits):
        return Settled(bet, "settled", 0.0)
    if x.legs and all(hits):
        return Settled(bet, "settled", round(x.stake * x.odds, 2))
    return Settled(bet, "pending")


def settle_bet(bet: Placed, races: dict) -> Settled:
    """``races`` maps race number -> domain.Race."""
    if bet.kind in HORSE_KINDS:
        return _single(bet, races)
    if bet.kind == "multi":
        return _multi(bet, races)
    return _pending(bet)


@dataclass
class DayResult:
    bets: list[Settled] = field(default_factory=list)

    @property
    def profit(self) -> float:
        return round(sum(b.profit for b in self.bets), 2)

    @property
    def settled(self) -> int:
        return sum(1 for b in self.bets if b.status == "settled")

    @property
    def pending(self) -> int:
        return len(self.bets) - self.settled

    @property
    def bonus(self) -> float:
        return round(sum(b.bonus for b in self.bets if b.status == "settled"), 2)

    def race(self, number: int) -> DayResult:
        """One race's own bets (a multi counts in the day, not in a race)."""
        return DayResult([b for b in self.bets if b.bet.race == number and b.bet.kind != "multi"])

    def fill(self, total: float) -> float:
        """How far the bar fills its half, 0 to 100: the day's profit or loss against ``total``
        (the day's amounts)."""
        if not self.profit:
            return 0.0
        return 100.0 if total <= 0 else min(100.0, 100.0 * abs(self.profit) / total)


def settle_all(placed: list[Placed], races: dict) -> DayResult:
    return DayResult([settle_bet(p, races) for p in placed])


def signed(x: float) -> str:
    """+$12.40, -$9.52, $0.00."""
    return f"{'+' if x > 0 else '-' if x < 0 else ''}${abs(x):,.2f}"
