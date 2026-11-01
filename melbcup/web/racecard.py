"""What the race card and the day page show (owner BUILD, 2026-11-01; .grok/product-ui/).

The owner bets from two accounts, Sportsbet and Betfair, each with its own amount for the day.
Every race still to run shows its win, place and each-way picks and its likeliest quinella and
trifecta, each with a whole-dollar stake and the account it goes to (melbcup/bets/allocate.py).
Bets the owner ticks as placed are kept in a cookie on their phone (there is no login by
design): they keep their stake and account, and the wallet bars count them.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import unquote

from melbcup.bets.allocate import (
    KINDS,
    SPORTSBET_ONLY,
    Placed,
    Routed,
    allocate_accounts,
    race_picks,
)
from melbcup.config import MELBOURNE
from melbcup.domain import betfair_net

DEFAULT_SPORTSBET = 150.0
DEFAULT_BETFAIR = 50.0
MAX_AMOUNT = 100_000
SB_COOKIE, BF_COOKIE, PLACED_COOKIE = "sb_budget", "bf_budget", "placed"
# Short codes keep the placed cookie small: [date, race, kind, runner or 0, account, stake].
CODES = {
    "win": "w",
    "place": "p",
    "each_way": "e",
    "quinella": "q",
    "trifecta": "t",
    "first_four": "f",
    "quaddie": "qd",
    "early_quaddie": "eq",
}
KIND_OF = {v: k for k, v in CODES.items()}
ACCOUNTS = {"sb": "sportsbet", "bf": "betfair"}
ACCOUNT_NAMES = {"sportsbet": "Sportsbet", "betfair": "Betfair"}
LABELS = {
    "win": "Win",
    "place": "Place",
    "each_way": "Each way",
    "quinella": "Quinella",
    "trifecta": "Trifecta",
    "first_four": "First Four",
    "quaddie": "Quaddie",
    "early_quaddie": "Early quaddie",
}
CAVEATS = {
    "quinella": "On average quinellas pay less than that.",
    "trifecta": "Trifectas lost money in testing.",
}
SUFFIX = {
    "quinella": "any two of them 1st and 2nd",
    "trifecta": "any three in the first three",
    "first_four": "any four in the first four",
}
PLACES = ("1st", "2nd", "3rd", "4th")


# -- the owner's amounts and placed bets ------------------------------------------------------


def parse_amount(text: str | None) -> float | None:
    """A day amount: $0 to $100,000 (an account may be left at $0). None if not a number."""
    raw = (text or "").strip().lstrip("$").replace(",", "")
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if 0 <= value <= MAX_AMOUNT else None


def pick_amounts(
    query: Mapping[str, str], cookies: Mapping[str, str] | None = None
) -> tuple[float, float, bool]:
    """(Sportsbet, Betfair, chosen): ?sb= and ?bf=, else ?budget= alone (all on Sportsbet),
    else the sb_budget and bf_budget cookies, else $150 and $50."""
    cookies = cookies or {}
    if "sb" in query or "bf" in query:
        sb, bf = parse_amount(query.get("sb")), parse_amount(query.get("bf"))
        return (
            DEFAULT_SPORTSBET if sb is None else sb,
            DEFAULT_BETFAIR if bf is None else bf,
            sb is not None or bf is not None,
        )
    if "budget" in query:
        chosen = parse_amount(query["budget"])
        if chosen:
            return chosen, 0.0, True
        return DEFAULT_SPORTSBET, DEFAULT_BETFAIR, False
    sb = parse_amount(unquote(cookies.get(SB_COOKIE) or ""))
    bf = parse_amount(unquote(cookies.get(BF_COOKIE) or ""))
    return (
        DEFAULT_SPORTSBET if sb is None else sb,
        DEFAULT_BETFAIR if bf is None else bf,
        sb is not None or bf is not None,
    )


def parse_placed(raw: str | None, race_date: date | None) -> list[Placed]:
    """The placed cookie: a URL-encoded JSON list of [date, race, kind, runner, account, stake].
    Records for another date, damaged records and repeats of a slot are ignored."""
    if not raw or race_date is None:
        return []
    try:
        data = json.loads(unquote(raw))
    except ValueError:
        return []
    if not isinstance(data, list):
        return []
    out: list[Placed] = []
    seen: set[tuple[int, str]] = set()
    for rec in data[:200]:
        if not isinstance(rec, list) or len(rec) != 6:
            continue
        when, race, code, key, acct, stake = rec
        kind, account = KIND_OF.get(code), ACCOUNTS.get(acct)
        if when != race_date.isoformat() or kind is None or account is None:
            continue
        if not all(isinstance(x, int) and not isinstance(x, bool) for x in (race, key, stake)):
            continue
        if not (0 < stake <= MAX_AMOUNT) or (race, kind) in seen:
            continue
        if kind in SPORTSBET_ONLY:
            account, key = "sportsbet", 0
        seen.add((race, kind))
        out.append(Placed(race, kind, key, account, stake))
    return out


# -- formatting ---------------------------------------------------------------------------------


def dollars(x: float) -> str:
    """$17, $15.60, $1,285."""
    if abs(x - round(x)) < 0.005:
        return f"${round(x):,}"
    return f"${x:,.2f}"


def price_text(x: float | None) -> str:
    if x is None:
        return "–"
    return f"${x:,.2f}" if x < 100 else f"${x:,.0f}"


def one_in(p: float | None) -> str:
    """A chance as people say it: "1 in 8", or "3 in 10" from 28% up."""
    if not p or p <= 0:
        return "–"
    if p >= 0.28:
        return f"{min(9, round(10 * p))} in 10"
    return f"1 in {max(2, round(1 / p))}"


def jump(dt) -> str:
    """Tue 3:00pm, Melbourne time."""
    if dt is None:
        return ""
    t = dt.astimezone(MELBOURNE)
    return f"{t:%a} {t.hour % 12 or 12}:{t.minute:02d}{'am' if t.hour < 12 else 'pm'}"


# -- price pills --------------------------------------------------------------------------------


@dataclass
class Pill:
    account: str  # "sb" | "bf"
    text: str
    best: bool = False


def pills(prices, kind: str = "win") -> list[Pill]:
    """Sportsbet (SB) and Betfair (BF) prices for one runner; the better one, with Betfair
    counted after commission, is filled. Each way shows win / place."""
    if prices is None:
        return []
    if kind == "place":
        sb, bf = prices.sportsbet_place, prices.betfair_place
    else:
        sb, bf = prices.sportsbet_win, prices.betfair_win
    out = []
    if sb:
        text = price_text(sb)
        if kind == "each_way" and prices.sportsbet_place:
            text += f" / {price_text(prices.sportsbet_place)}"
        out.append(Pill("sb", text))
    if bf:
        text = price_text(bf)
        if kind == "each_way" and prices.betfair_place:
            text += f" / {price_text(prices.betfair_place)}"
        out.append(Pill("bf", text))
    if len(out) == 2:
        out[1 if betfair_net(bf) > sb else 0].best = True
    elif out:
        out[0].best = True
    return out


# -- one line of the card -----------------------------------------------------------------------


@dataclass
class Line:
    """One pick or exotic as the card shows it. ``stake`` is 0 when no money is allocated to it:
    the card then shows no $ and no Placed buttons."""

    race: int
    kind: str
    stake: int = 0
    account: str | None = None  # "sportsbet" | "betfair"
    placed: bool = False
    good: bool = False
    number: int | None = None
    name: str = ""
    chance: float | None = None
    pills: list[Pill] = field(default_factory=list)
    say: str = ""  # plain part of the chance and return line
    bold: str = ""  # bold part
    legs: list[tuple[str, list[int], str]] = field(default_factory=list)
    title: str = ""
    record: str = ""  # JSON for the Placed buttons: [date, race, kind, runner, account, stake]
    sportsbet_only: bool = False

    @property
    def label(self) -> str:
        return LABELS[self.kind]

    @property
    def caveat(self) -> str:
        return CAVEATS.get(self.kind, "")

    @property
    def acct(self) -> str | None:
        return {"sportsbet": "sb", "betfair": "bf"}.get(self.account or "")

    @property
    def account_name(self) -> str:
        return ACCOUNT_NAMES.get(self.account or "", "")


def _record(race_date: date, line: Line) -> str:
    key = line.number if line.kind in KINDS and line.number is not None else 0
    return json.dumps(
        [race_date.isoformat(), line.race, CODES[line.kind], key, "", line.stake],
        separators=(",", ":"),
    )


def _horse_line(rp, kind: str, routed: Routed | None, race_date: date) -> Line | None:
    race = rp.model.race
    single = routed.pick.single if routed else race_picks(rp).get(kind)
    if single is None:
        return None
    prices = race.prices.get(single.number)
    stake = routed.pick.stake if routed else 0
    account = routed.account if routed else None
    line = Line(
        race.number,
        kind,
        stake,
        account,
        bool(routed and routed.placed),
        routed.pick.good_price if routed else (rp.best.get(kind) is single and bool(single.stake)),
        single.number,
        single.name,
        single.prob,
        pills(prices, kind),
        sportsbet_only=False,
    )
    _horse_words(line, prices)
    line.record = _record(race_date, line)
    return line


def _horse_words(line: Line, prices) -> None:
    """ "Wins 1 in 10. $2 returns $17." at the price of the account the bet goes to (Betfair
    after commission)."""
    on_bf = line.account == "betfair"

    def at(win: bool) -> float | None:
        if prices is None:
            return None
        if on_bf:
            return betfair_net(prices.betfair_win if win else prices.betfair_place)
        return prices.sportsbet_win if win else prices.sportsbet_place

    s = line.stake
    if line.kind == "win":
        line.say = f"Wins {one_in(line.chance)}."
        if s and (p := at(True)):
            line.bold = f"${s} returns {dollars(s * p)}."
    elif line.kind == "place":
        line.say = f"Places {one_in(line.chance)}."
        if s and (p := at(False)):
            line.bold = f"${s} returns {dollars(s * p)}."
    else:
        line.say = f"Places {one_in(line.chance)}."
        if s:
            half = s / 2
            line.say = f"{dollars(half)} win + {dollars(half)} place."
            w, pl = at(True), at(False)
            if w and pl:
                line.bold = f"Wins: {dollars(half * (w + pl))}. Only places: {dollars(half * pl)}."


def _legs(kind: str, e) -> list[tuple[str, list[int], str]]:
    legs = e.legs
    if kind in ("quaddie", "early_quaddie"):
        return [(f"R{r}", leg, "") for r, leg in zip(e.races, legs, strict=True)]
    same = all(leg == legs[0] for leg in legs)
    if same or (kind == "quinella" and all(len(leg) == 1 for leg in legs)):
        numbers = sorted({n for leg in legs for n in leg})
        return [("Box", numbers, SUFFIX[kind])]
    if kind == "quinella":
        return [("Pick", legs[0], ""), ("With", legs[1], "")]
    return [(PLACES[i], leg, "") for i, leg in enumerate(legs)]


def _exotic_line(
    race: int, kind: str, e, routed: Routed | None, race_date: date
) -> Line | None:
    if routed is not None and routed.pick.exotic is not None:
        e = routed.pick.exotic
    if e is None and routed is None:
        return None
    stake = routed.pick.stake if routed else 0
    line = Line(
        race,
        kind,
        stake,
        "sportsbet" if stake else None,
        bool(routed and routed.placed),
        chance=e.prob if e is not None else None,
        sportsbet_only=True,
    )
    if e is not None:
        line.legs = _legs(kind, e)
        if kind in ("quinella", "trifecta"):
            line.say = f"Lands {one_in(e.prob)}."
            if stake:
                share = stake / e.combos
                buys = f"{share:.0%} of the dividend"
                if share >= 1:
                    buys = f"{share:.1f} times the dividend"
                line.say += f" ${stake} buys {buys}."
            if e.prob > 0:
                over = dollars(round(e.fair_dividend))
                line.bold = f"Worth a try only if Sportsbet's estimate is over {over}."
    if kind == "first_four":
        line.title = f"First Four, race {race}"
    elif kind in ("quaddie", "early_quaddie") and e is not None:
        name = "Quaddie" if kind == "quaddie" else "Early quaddie"
        line.title = f"{name} starts here, races {e.races[0]} to {e.races[-1]}"
    else:
        line.title = LABELS[kind]
    line.record = _record(race_date, line)
    return line


# -- the day -----------------------------------------------------------------------------------


@dataclass
class QuaddieLeg:
    title: str  # "Quaddie" | "Early quaddie"
    leg: int
    numbers: list[int]
    first: int
    last: int


@dataclass
class RaceCard:
    race: object  # domain.Race
    rp: object  # RacePicks
    open: bool
    board: list[Line]
    exotics: list[Line]  # First Four, quaddies starting here, quinella, trifecta
    quaddie_legs: list[QuaddieLeg]
    mine: set[int]  # runner numbers in this race's horse picks

    @property
    def total(self) -> int:
        return sum(x.stake for x in self.board + self.exotics)

    @property
    def placed_count(self) -> int:
        return sum(1 for x in self.board + self.exotics if x.placed)


@dataclass
class Wallet:
    sportsbet: float
    betfair: float
    sportsbet_used: int
    betfair_used: int

    @property
    def total(self) -> float:
        return self.sportsbet + self.betfair

    def accounts(self) -> list[tuple[str, str, float, float]]:
        """(code, name, amount, used) per account."""
        return [
            ("sb", "Sportsbet", self.sportsbet, self.sportsbet_used),
            ("bf", "Betfair", self.betfair, self.betfair_used),
        ]

    @property
    def left(self) -> float:
        return max(0.0, self.sportsbet - self.sportsbet_used) + max(
            0.0, self.betfair - self.betfair_used
        )


def wallet(sb: float, bf: float, placed: list[Placed]) -> Wallet:
    return Wallet(
        sb,
        bf,
        sum(p.stake for p in placed if p.account == "sportsbet"),
        sum(p.stake for p in placed if p.account == "betfair"),
    )


@dataclass
class DayCard:
    races: list[RaceCard]
    open_count: int

    def race(self, number: int) -> RaceCard | None:
        return next((r for r in self.races if r.race.number == number), None)

    @property
    def total(self) -> int:
        return sum(r.total for r in self.races)


def build_day(
    picks, sb: float, bf: float, placed: list[Placed], open_races: set[int], race_date: date
) -> DayCard:
    """Every race's lines with stakes from the two amounts and the owner's placed bets."""
    routed = allocate_accounts(picks, sb, bf, placed, races=open_races)
    slot = {(r.pick.race, r.pick.kind): r for r in routed}
    quaddies = [q for q in picks.quaddies if q.recommended and q.races]
    races = []
    for rp in picks.races:
        race = rp.model.race
        n = race.number
        is_open = n in open_races
        board = []
        for kind in KINDS:
            r = slot.get((n, kind))
            if is_open or r is not None:
                if line := _horse_line(rp, kind, r, race_date):
                    board.append(line)
        exotics = []
        ff = next((e for e in rp.first_fours if e.recommended), None)
        candidates = [("first_four", ff)]
        candidates += [(q.kind, q) for q in quaddies if q.races[0] == n]
        candidates += [
            ("quinella", max(rp.quinellas, key=lambda e: e.prob, default=None)),
            ("trifecta", max(rp.trifectas, key=lambda e: e.prob, default=None)),
        ]
        for kind, e in candidates:
            r = slot.get((n, kind))
            if (is_open and e is not None) or r is not None:
                if line := _exotic_line(n, kind, e, r, race_date):
                    exotics.append(line)
        legs = [
            QuaddieLeg(
                "Quaddie" if q.kind == "quaddie" else "Early quaddie",
                q.races.index(n) + 1,
                q.legs[q.races.index(n)],
                q.races[0],
                q.races[-1],
            )
            for q in quaddies
            if n in q.races[1:]
        ]
        mine = {x.number for x in board if x.number is not None}
        races.append(RaceCard(race, rp, is_open, board, exotics, legs, mine))
    return DayCard(races, len(open_races))
