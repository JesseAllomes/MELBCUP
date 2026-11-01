"""Betting on Betfair for the owner: one bet by hand, and Auto in the last minute before a jump.

Safety, in the order it is checked:
- Every betting action needs the PIN (BET_PIN, from Key Vault). Five wrong PINs lock betting
  for 15 minutes. With no PIN set, betting is off.
- Practice mode is the default: it records what it would bet and places nothing. Only
  BET_MODE=live places real bets, and Betfair refuses those until the account's live app key
  is in use.
- Auto runs only on races the owner switches it on for, each with its own limit (owner,
  2026-11-01). Every race starts off, and every switch is cleared by a restart. What auto has
  spent on a race is the larger of this app's record and Betfair's own record for that race's
  auto bets, so a restart cannot reset it.
- Auto only bets win, place and each-way lines that are a BET at Betfair's latest price after
  commission (Sportsbet's prices are taken out before the recheck), sized as if the race's
  limit were the day's budget. Exotics pay tote dividends, which Betfair does not offer, so
  auto never places them.
"""

from __future__ import annotations

import copy
import hmac
import logging
import threading
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta

from melbcup.bets import build_picks
from melbcup.config import MELBOURNE, Settings
from melbcup.domain import Race
from melbcup.sources import apply_exchange
from melbcup.sources.http import SourceError

log = logging.getLogger(__name__)

WINDOW = timedelta(seconds=60)  # auto bets in the last minute before the advertised jump
MIN_STAKE = 5.0  # Betfair Australia's smallest back bet; smaller stakes are skipped, not raised
MAX_HAND_STAKE = 500.0  # one bet by hand, a typo guard
MAX_PIN_FAILS = 5
PIN_LOCKOUT = timedelta(minutes=15)
HAND = "melbcup-hand"
MAX_RACE_LIMIT = 10_000.0


def auto_strategy(race: int) -> str:
    """Betfair's tag for one race's auto bets (15 characters at most)."""
    return f"melbcup-auto{race}"


class PinError(PermissionError):
    """Wrong or missing PIN, or betting locked after too many wrong PINs."""


class BetError(ValueError):
    """A bet that cannot be made (no price, no such runner, over a limit)."""


@dataclass
class Placed:
    at: datetime
    race: int
    number: int
    name: str
    kind: str  # "win" | "place"
    price: float
    stake: float
    mode: str  # "practice" | "live"
    source: str  # "auto" | "hand"
    status: str  # "practice", "placed", "matched", "skipped" or Betfair's failure code
    note: str = ""

    def counts(self) -> bool:
        return self.status in ("practice", "placed", "matched")


class Betting:
    def __init__(self, settings: Settings, board, clock=None):
        self._pin = settings.bet_pin
        self.live = settings.bet_live
        self.default_limit = settings.auto_limit  # suggested in the form, never applied alone
        self.armed: dict[tuple[date, int], float] = {}  # (day, race) -> that race's limit
        self.board = board
        self.clock = clock or board.clock
        self.ledger: list[Placed] = []
        self._done: set[tuple[date, int]] = set()
        self._fails: list[datetime] = []
        self._lock = threading.Lock()

    @property
    def mode(self) -> str:
        return "live" if self.live else "practice"

    # -- PIN ----------------------------------------------------------------------------------
    def check_pin(self, pin: str | None) -> None:
        now = self.clock()
        with self._lock:
            self._fails = [t for t in self._fails if now - t < PIN_LOCKOUT]
            if self._pin is None:
                raise PinError("Betting is off: no PIN is set in Key Vault.")
            if len(self._fails) >= MAX_PIN_FAILS:
                raise PinError("Too many wrong PINs. Betting is locked for 15 minutes.")
            if not pin or not hmac.compare_digest(pin.encode(), self._pin.encode()):
                self._fails.append(now)
                raise PinError("Wrong PIN.")
            self._fails.clear()

    # -- settings and status ------------------------------------------------------------------
    def set_auto(
        self, pin: str | None, race: int, on: bool, limit: float | None = None
    ) -> dict:
        """Switch auto on for one race with that race's limit, or off. Needs the PIN."""
        self.check_pin(pin)
        day = self._day(self.clock())
        key = (day, race)
        if not on:
            self.armed.pop(key, None)
            return self.status()
        if self.board.bf is None:
            raise BetError("Auto needs the Betfair login in Key Vault.")
        if limit is None or not 0 < limit <= MAX_RACE_LIMIT:
            raise BetError(f"Enter this race's auto limit, up to ${MAX_RACE_LIMIT:,.0f}.")
        snap = self.board.snapshot()
        found = next((r for r in snap.card.races if r.number == race), None) if snap.card else None
        if found is None or found.result is not None:
            raise BetError(f"Race {race} is not open.")
        if key in self._done:
            raise BetError(f"Auto has already run on race {race}.")
        self.armed[key] = float(limit)
        return self.status()

    def _day(self, now: datetime) -> date:
        return now.astimezone(MELBOURNE).date()

    def _mine(self, day: date, source: str, race: int | None = None) -> float:
        return sum(
            p.stake for p in self.ledger
            if p.source == source and p.counts() and self._day(p.at) == day
            and p.mode == self.mode and (race is None or p.race == race)
        )

    def spent_on_race(self, race: int) -> float:
        """Dollars auto has put on ``race`` today: this app's record, or Betfair's if higher."""
        day = self._day(self.clock())
        mine = self._mine(day, "auto", race)
        if self.live and self.board.bf is not None:
            try:
                return max(mine, self.board.bf.staked_today(day, auto_strategy(race)))
            except SourceError as exc:
                log.warning("Betfair staked_today: %s", exc)
                raise BetError("Could not check this race's spend on Betfair, so no bet.") from exc
        return mine

    def status(self) -> dict:
        day = self._day(self.clock())
        return {
            "mode": self.mode,
            "pin_set": self._pin is not None,
            "betfair": self.board.bf is not None,
            "default_limit": self.default_limit,
            "auto_races": [
                {"race": race, "limit": limit, "spent": self._mine(day, "auto", race),
                 "done": (d, race) in self._done}
                for (d, race), limit in sorted(self.armed.items()) if d == day
            ],
            "bets": [
                {**asdict(p), "at": p.at.astimezone(MELBOURNE).strftime("%-I:%M:%S%p").lower()}
                for p in self.ledger[-50:]
            ],
        }

    # -- prices -------------------------------------------------------------------------------
    def _fresh(self, race_date: date, venue: str) -> dict:
        try:
            return self.board.bf.meeting(race_date, venue)
        except SourceError as exc:
            raise BetError(f"No Betfair prices right now ({exc.kind}).") from exc

    @staticmethod
    def betfair_lines(model, exchange, budget: float) -> list:
        """The win, place and each-way BET lines at Betfair's own prices only. The chances are
        the model's (they come from the books' consensus, not from these prices)."""
        r = copy.deepcopy(model.race)
        apply_exchange(r, exchange)
        for p in r.prices.values():
            p.sportsbet_win = p.sportsbet_place = None
        rp = build_picks([replace(model, race=r)], budget=budget).races[0]
        lines, seen = [], set()
        for kind in ("each_way", "win", "place"):  # each way first: it holds a win part too
            s = rp.best.get(kind)
            if s is None or not s.value or not s.stake or s.bookmaker != "betfair":
                continue
            if s.number in seen:
                continue
            seen.add(s.number)
            lines.append(s)
        return lines

    # -- placing ------------------------------------------------------------------------------
    def _order(self, race: Race, exchange, number: int, kind: str, stake: float, source: str,
               now: datetime) -> Placed:
        runner = race.runner(number)
        name = runner.name if runner else str(number)
        prices = exchange.win if kind == "win" else exchange.place
        market = exchange.win_market if kind == "win" else exchange.place_market
        price = prices.get(number)
        sel = exchange.selections.get(number)
        if price is None or market is None or sel is None:
            return Placed(now, race.number, number, name, kind, 0.0, stake, self.mode, source,
                          "skipped", "no Betfair price")
        if stake < MIN_STAKE:
            return Placed(now, race.number, number, name, kind, price, stake, self.mode, source,
                          "skipped", f"under Betfair's ${MIN_STAKE:g} minimum")
        if not self.live:
            return Placed(now, race.number, number, name, kind, price, stake, self.mode, source,
                          "practice", "practice: nothing placed")
        ref = f"{source[0]}{now:%y%m%d}r{race.number}n{number}{kind[0]}{now:%H%M%S}"
        try:
            tag = auto_strategy(race.number) if source == "auto" else HAND
            order = self.board.bf.place(market, sel, price, stake, ref, tag)
        except SourceError as exc:
            return Placed(now, race.number, number, name, kind, price, stake, self.mode, source,
                          exc.kind, str(exc))
        if order.status != "SUCCESS":
            return Placed(now, race.number, number, name, kind, price, stake, self.mode, source,
                          order.status, "refused by Betfair")
        status = "matched" if order.matched >= stake - 0.01 else "placed"
        note = f"matched ${order.matched:.2f}" + (f" at ${order.price}" if order.price else "")
        return Placed(now, race.number, number, name, kind, price, stake, self.mode, source,
                      status, note)

    def bet_by_hand(self, pin: str | None, race_no: int, number: int, kind: str,
                    stake: float) -> Placed:
        self.check_pin(pin)
        if kind not in ("win", "place"):
            raise BetError("Choose win or place.")
        if not 0 < stake <= MAX_HAND_STAKE:
            raise BetError(f"The stake must be between $0 and ${MAX_HAND_STAKE:g}.")
        if self.board.bf is None:
            raise BetError("Betting needs the Betfair login in Key Vault.")
        snap = self.board.snapshot()
        race = next((r for r in snap.card.races if r.number == race_no), None) if snap.card else None
        if race is None or race.result is not None:
            raise BetError(f"Race {race_no} is not open.")
        if race.runner(number) is None:
            raise BetError(f"No runner {number} in race {race_no}.")
        now = self.clock()
        exchange = self._fresh(snap.race_date, snap.venue).get(race_no)
        if exchange is None:
            raise BetError(f"Betfair has no market for race {race_no}.")
        placed = self._order(race, exchange, number, kind, float(stake), "hand", now)
        self.ledger.append(placed)
        return placed

    # -- auto ---------------------------------------------------------------------------------
    def tick(self) -> list[Placed]:
        """Bet each race auto is on for, once, in the last minute before its jump."""
        if not self.armed or self.board.bf is None:
            return []
        now = self.clock()
        snap = self.board.snapshot()
        if snap.card is None:
            return []
        day = self._day(now)
        due = [
            r for r in snap.card.races
            if r.result is None and r.start_time is not None
            and timedelta(0) < r.start_time - now <= WINDOW
            and (day, r.number) in self.armed and (day, r.number) not in self._done
        ]
        if not due:
            return []
        try:
            fresh = self._fresh(snap.race_date, snap.venue)
        except BetError as exc:
            log.warning("auto: %s", exc)
            return []  # tried again on the next tick, while the window lasts
        models = {m.race.number: m for m in snap.models}
        out: list[Placed] = []
        for race in due:
            self._done.add((day, race.number))
            exchange = fresh.get(race.number)
            if exchange is None or race.number not in models:
                continue
            limit = self.armed[(day, race.number)]
            for s in self.betfair_lines(models[race.number], exchange, limit):
                parts = (
                    [("win", s.stake / 2), ("place", s.stake / 2)]
                    if s.kind == "each_way" else [(s.kind, float(s.stake))]
                )
                for kind, stake in parts:
                    try:
                        left = limit - self.spent_on_race(race.number)
                    except BetError as exc:
                        out.append(Placed(now, race.number, s.number, s.name, kind, 0.0, stake,
                                          self.mode, "auto", "skipped", str(exc)))
                        continue
                    if left < MIN_STAKE:
                        out.append(Placed(now, race.number, s.number, s.name, kind, 0.0, stake,
                                          self.mode, "auto", "skipped", "race limit reached"))
                        continue
                    placed = self._order(race, exchange, s.number, kind, min(stake, left), "auto", now)
                    self.ledger.append(placed)
                    out.append(placed)
        for p in out:
            if p not in self.ledger:
                self.ledger.append(p)
        return out


def start_loop(betting: Betting, every_seconds: float = 10.0) -> threading.Event:
    """Run auto's check in the background. Set the returned event to stop it."""
    stop = threading.Event()

    def loop() -> None:
        while not stop.wait(every_seconds):
            try:
                betting.tick()
            except Exception:  # noqa: BLE001 - one bad tick must not end auto
                log.exception("auto tick failed")

    threading.Thread(target=loop, name="auto-bet", daemon=True).start()
    return stop


__all__ = ["BetError", "Betting", "PinError", "Placed", "start_loop"]
