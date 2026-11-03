"""What the race card and the day page show (owner BUILD, 2026-11-01; .grok/product-ui/).

The owner bets from two accounts, Sportsbet and Betfair, each with its own amount for the day
(three with POINTSBET=1: PointsBet too, $0 until an amount is set).
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
    day_multi_list,
    race_picks,
)
from melbcup.bets.multis import Multi, key_legs
from melbcup.bets.promos import (
    BOOSTER_NOTE,
    BOOSTER_PILL,
    PB_PAYBACK_MAX,
    booster_gain,
    payback_multi,
)
from melbcup.bets.settle import settle_bet
from melbcup.config import MELBOURNE
from melbcup.domain import betfair_net
from melbcup.model.probability import top_k_probs

DEFAULT_SPORTSBET = 150.0
DEFAULT_BETFAIR = 50.0
DEFAULT_POINTSBET = 0.0  # PointsBet (POINTSBET=1) takes nothing until the owner sets an amount
MAX_AMOUNT = 100_000
SB_COOKIE, BF_COOKIE, PLACED_COOKIE = "sb_budget", "bf_budget", "placed"
PB_COOKIE = "pb_budget"
# Short codes keep the placed cookie small: [date, race, kind, runner or 0, account, stake] and
# optionally the price taken.
CODES = {
    "win": "w",
    "place": "p",
    "each_way": "e",
    "quinella": "q",
    "trifecta": "t",
    "first_four": "f",
    "quaddie": "qd",
    "early_quaddie": "eq",
    "multi": "m",
}
KIND_OF = {v: k for k, v in CODES.items()}
ACCOUNTS = {"sb": "sportsbet", "bf": "betfair"}
POINTSBET_ACCOUNTS = {"pb": "pointsbet"}  # ticks on PointsBet count only with POINTSBET=1
ACCOUNT_NAMES = {"sportsbet": "Sportsbet", "betfair": "Betfair", "pointsbet": "PointsBet"}
LABELS = {
    "win": "Win",
    "place": "Place",
    "each_way": "Each way",
    "quinella": "Quinella",
    "trifecta": "Trifecta",
    "first_four": "First Four",
    "quaddie": "Quaddie",
    "early_quaddie": "Early quaddie",
    "multi": "Multi",
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


def pick_pointsbet(query: Mapping[str, str], cookies: Mapping[str, str] | None = None) -> float:
    """PointsBet's day amount (POINTSBET=1): ?pb=, else the pb_budget cookie, else $0. A ?pb= that
    is blank or not a number puts it back to $0."""
    if "pb" in query:
        chosen = parse_amount(query.get("pb"))
    else:
        chosen = parse_amount(unquote((cookies or {}).get(PB_COOKIE) or ""))
    return DEFAULT_POINTSBET if chosen is None else chosen


def parse_placed(
    raw: str | None, race_date: date | None, pointsbet: bool = False
) -> list[Placed]:
    """The placed cookie: a URL-encoded JSON list of [date, race, kind, runner, account, stake]
    with an optional 7th element, the price taken. Records for another date, damaged records and
    repeats are ignored. Several records may share a race and kind: a record is a repeat of one
    with the same race, kind, runner and account (a multi: the same legs). ``pointsbet``
    (POINTSBET=1) accepts account "pb"; otherwise such a record is ignored."""
    accounts = ACCOUNTS | POINTSBET_ACCOUNTS if pointsbet else ACCOUNTS
    if not raw or race_date is None:
        return []
    try:
        data = json.loads(unquote(raw))
    except ValueError:
        return []
    if not isinstance(data, list):
        return []
    out: list[Placed] = []
    seen: set[tuple[int, str, int, str]] = set()
    for rec in data[:200]:
        if not isinstance(rec, list) or len(rec) not in (6, 7, 8):
            continue
        when, race, code, key, acct, stake = rec[:6]
        price = _price(rec[6]) if len(rec) >= 7 else None
        place_price = _price(rec[7]) if len(rec) == 8 else None  # each way's place price
        kind, account = KIND_OF.get(code), accounts.get(acct)
        if when != race_date.isoformat() or kind is None or account is None:
            continue
        if not all(isinstance(x, int) and not isinstance(x, bool) for x in (race, key, stake)):
            continue
        bad_multi = kind == "multi" and not key_legs(key)
        if not (0 < stake <= MAX_AMOUNT) or bad_multi:
            continue
        if kind in SPORTSBET_ONLY:
            account = "sportsbet"
            key = key if kind == "multi" else 0
        ident = (race, kind, key, account)
        if ident in seen:
            continue
        seen.add(ident)
        out.append(
            Placed(race, kind, key, account, stake, price,
                   place_price if kind == "each_way" else None)
        )
    return out


def _price(x) -> float | None:
    """The price taken (a decimal price, 1.01 to 1,001) or None when absent or not sensible."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x) if 1.01 <= x <= 1001 else None


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


def pills(prices, kind: str = "win", pointsbet: bool = False) -> list[Pill]:
    """Sportsbet (SB) and Betfair (BF) prices for one runner; the better one, with Betfair
    counted after commission, is filled. Each way shows win / place. ``pointsbet``
    (POINTSBET=1) adds a PB pill, and the filled one is the best of the three."""
    if prices is None:
        return []
    if pointsbet:
        return _pills_three(prices, kind)
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


def _pills_three(prices, kind: str) -> list[Pill]:
    """SB, BF and PB pills; the best price after commission is filled (a tie stays with the
    earlier pill)."""
    if kind == "place":
        sb, bf, pb = prices.sportsbet_place, prices.betfair_place, prices.pointsbet_place
    else:
        sb, bf, pb = prices.sportsbet_win, prices.betfair_win, prices.pointsbet_win
    pairs = (
        ("sb", sb, prices.sportsbet_place, sb),
        ("bf", bf, prices.betfair_place, betfair_net(bf)),
        ("pb", pb, prices.pointsbet_place, pb),
    )
    out, worth = [], []
    for code, price, place, comparable in pairs:
        if price:
            text = price_text(price)
            if kind == "each_way" and place:
                text += f" / {price_text(place)}"
            out.append(Pill(code, text))
            worth.append(comparable)
    if out:
        out[worth.index(max(worth))].best = True
    return out


# -- one line of the card -----------------------------------------------------------------------


@dataclass
class Line:
    """One pick or exotic as the card shows it. ``stake`` is 0 when no money is allocated to it:
    the card then shows no $ and no Placed buttons."""

    race: int
    kind: str
    stake: int = 0
    account: str | None = None  # "sportsbet" | "betfair" | "pointsbet"
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
    key: int = 0  # a multi's legs, packed (multis.multi_key): the placed record's key
    # race, number, name, "Win" | "Place"
    multi_legs: list[tuple[int, int, str, str]] = field(default_factory=list)
    price: float | None = None  # a multi's Sportsbet price
    pointsbet: bool = False  # POINTSBET=1: the Placed buttons offer PointsBet too
    promo: str = ""  # PROMOS=1: "Promo: Run 2nd, You Win" on a promo Win bet
    promo_note: str = ""  # its one-line value note
    booster: str = ""  # PROMOS=1 + PointsBet: "PB booster: use here" on the one single to boost
    booster_note: str = ""
    value_note: str = ""  # the PointsBet Pay Back multi: its value per $1 line
    taken: float | None = None  # a placed line: the price the owner took, when they gave it
    remove: str = ""  # a placed line: its own record as JSON, for its Remove button
    settled: object | None = None  # a placed line: its settle.Settled, once worked out

    @property
    def label(self) -> str:
        return LABELS[self.kind]

    @property
    def caveat(self) -> str:
        return CAVEATS.get(self.kind, "")

    @property
    def acct(self) -> str | None:
        return {"sportsbet": "sb", "betfair": "bf", "pointsbet": "pb"}.get(self.account or "")

    @property
    def account_name(self) -> str:
        return ACCOUNT_NAMES.get(self.account or "", "")


def _record(race_date: date, line: Line) -> str:
    key = line.number if line.kind in KINDS and line.number is not None else 0
    if line.kind == "multi":
        key = line.key
    return json.dumps(
        [race_date.isoformat(), line.race, CODES[line.kind], key, "", line.stake],
        separators=(",", ":"),
    )


def _mark_placed(line: Line, routed: Routed | None, race_date: date) -> None:
    """A placed line carries its own record (with account and price) for the Remove button and
    the price taken, which replaces the current price in its words."""
    if routed is None or not routed.placed or routed.record is None:
        return
    line.taken = routed.record.price
    rec = json.loads(line.record or _record(race_date, line))
    rec[4] = line.acct or ""
    if line.taken is not None:
        rec.append(line.taken)
    line.remove = json.dumps(rec, separators=(",", ":"))


def _horse_line(
    rp, kind: str, routed: Routed | None, race_date: date, pointsbet: bool = False
) -> Line | None:
    race = rp.model.race
    single = routed.pick.single if routed else race_picks(rp).get(kind)
    rec = routed.record if routed and routed.placed else None
    if single is None and rec is None:
        return None
    if single is not None:
        number, name, chance = single.number, single.name, single.prob
    else:  # a bet the owner placed on a runner the card has no line for
        runner = race.runner(rec.key)
        number, name, chance = rec.key, runner.name if runner else str(rec.key), None
    prices = race.prices.get(number)
    stake = routed.pick.stake if routed else 0
    account = routed.account if routed else None
    line = Line(
        race.number,
        kind,
        stake,
        account,
        bool(routed and routed.placed),
        routed.pick.good_price if routed else (rp.best.get(kind) is single and bool(single.stake)),
        number,
        name,
        chance,
        pills(prices, kind, pointsbet),
        sportsbet_only=False,
        pointsbet=pointsbet,
    )
    _mark_placed(line, routed, race_date)
    _horse_words(line, prices)
    if (bet := getattr(single, "promo", None)) is not None and line.account == bet.account:
        line.promo, line.promo_note = bet.pill, bet.note
        code = {"sportsbet": "sb", "pointsbet": "pb", "betfair": "bf"}[bet.account]
        for pill in line.pills:  # the bet is at the promo bookmaker: that price is the filled one
            pill.best = pill.account == code
    line.record = _record(race_date, line)
    return line


def _horse_words(line: Line, prices) -> None:
    """ "Wins 1 in 10. $2 returns $17." at the price of the account the bet goes to (Betfair
    after commission)."""
    on_bf = line.account == "betfair"
    on_pb = line.account == "pointsbet"

    def at(win: bool) -> float | None:
        if line.taken is not None:  # the price the owner took, when they gave it
            return line.taken
        if prices is None:
            return None
        if on_pb:
            return prices.pointsbet_win if win else prices.pointsbet_place
        if on_bf:
            return betfair_net(prices.betfair_win if win else prices.betfair_place)
        return prices.sportsbet_win if win else prices.sportsbet_place

    s = line.stake
    chance = None if line.chance is None else one_in(line.chance)
    if line.kind == "win":
        line.say = f"Wins {chance}." if chance else ""
        if s and (p := at(True)):
            line.bold = f"${s} returns {dollars(s * p)}."
    elif line.kind == "place":
        line.say = f"Places {chance}." if chance else ""
        if s and (p := at(False)):
            line.bold = f"${s} returns {dollars(s * p)}."
    else:
        line.say = f"Places {chance}." if chance else ""
        if s:
            half = s / 2
            line.say = f"{dollars(half)} win + {dollars(half)} place."
            w, pl = at(True), at(False)
            if w and pl and line.taken is None:
                line.bold = f"Wins: {dollars(half * (w + pl))}. Only places: {dollars(half * pl)}."
    if line.taken is not None:
        line.say = f"{line.say} Price taken {price_text(line.taken)}.".strip()


def _multi_line(
    m: Multi, routed: Routed | None, race_date: date, pointsbet: bool = False
) -> Line:
    """One day multi: its legs, the stake, and "Lands 1 in N. $S returns $R." at Sportsbet's
    price. A multi nobody has put money on (no stake) shows no $ and no Placed button."""
    stake = routed.pick.stake if routed else 0
    line = Line(
        m.race,
        "multi",
        stake,
        "sportsbet" if stake else None,
        bool(routed and routed.placed),
        m.good_price,
        chance=m.prob,
        pills=[Pill("sb", price_text(m.price), True)],
        sportsbet_only=True,
        pointsbet=pointsbet,
        key=m.key,
        multi_legs=[(leg.race, leg.number, leg.name, LABELS[leg.kind]) for leg in m.legs],
        price=m.price,
    )
    line.title = f"{len(m.legs)}-leg multi"
    line.say = f"Lands {one_in(m.prob)}."
    if stake:
        line.bold = f"${stake} returns {dollars(stake * m.price)}."
    line.record = _record(race_date, line)
    _mark_placed(line, routed, race_date)
    if line.taken is not None:
        line.bold = f"${stake} returns {dollars(stake * line.taken)}."
        line.say += f" Price taken {price_text(line.taken)}."
    return line


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
    race: int, kind: str, e, routed: Routed | None, race_date: date, pointsbet: bool = False
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
        pointsbet=pointsbet,
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
    _mark_placed(line, routed, race_date)
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
    pointsbet: float | None = None  # None: PointsBet is off (no POINTSBET=1)
    pointsbet_used: int = 0

    @property
    def total(self) -> float:
        if self.pointsbet is None:
            return self.sportsbet + self.betfair
        return self.sportsbet + self.betfair + self.pointsbet

    def accounts(self) -> list[tuple[str, str, float, float]]:
        """(code, name, amount, used) per account."""
        out = [
            ("sb", "Sportsbet", self.sportsbet, self.sportsbet_used),
            ("bf", "Betfair", self.betfair, self.betfair_used),
        ]
        if self.pointsbet is not None:
            out.append(("pb", "PointsBet", self.pointsbet, self.pointsbet_used))
        return out

    @property
    def left(self) -> float:
        left = max(0.0, self.sportsbet - self.sportsbet_used) + max(
            0.0, self.betfair - self.betfair_used
        )
        if self.pointsbet is not None:
            left += max(0.0, self.pointsbet - self.pointsbet_used)
        return left


def wallet(sb: float, bf: float, placed: list[Placed], pb: float | None = None) -> Wallet:
    """The accounts' money and what is placed in each; ``pb`` is PointsBet's day amount, None
    when PointsBet is off."""
    return Wallet(
        sb,
        bf,
        sum(p.stake for p in placed if p.account == "sportsbet"),
        sum(p.stake for p in placed if p.account == "betfair"),
        pb,
        sum(p.stake for p in placed if p.account == "pointsbet"),
    )


@dataclass
class DayCard:
    races: list[RaceCard]
    open_count: int
    multis: list[Line] = field(default_factory=list)  # "Multi picks for the day"
    payback: Line | None = None  # PROMOS=1 + PointsBet amount: "PointsBet Pay Back multi"

    def race(self, number: int) -> RaceCard | None:
        return next((r for r in self.races if r.race.number == number), None)

    @property
    def total(self) -> int:
        return sum(r.total for r in self.races) + sum(x.stake for x in self.multis)


def build_day(
    picks,
    sb: float,
    bf: float,
    placed: list[Placed],
    open_races: set[int],
    race_date: date,
    pb: float | None = None,
    promos: bool = False,
) -> DayCard:
    """Every race's lines with stakes from the two amounts and the owner's placed bets. ``pb``
    is PointsBet's day amount (POINTSBET=1); None leaves PointsBet out. ``promos`` (PROMOS=1)
    with a PointsBet amount adds the PointsBet daily promos: the booster pill and the Pay Back
    multi."""
    on = pb is not None
    day_list = day_multi_list(picks, open_races)  # worked out once: it is the costly part
    routed = allocate_accounts(
        picks, sb, bf, placed, races=open_races, multis=day_list, pointsbet_budget=pb
    )
    slot = {
        (r.pick.race, r.pick.kind): r for r in routed if r.pick.kind != "multi" and not r.placed
    }
    held: dict[tuple[int, str], list[Routed]] = {}  # placed bets: any number to a race and kind
    for r in routed:
        if r.placed and r.pick.kind != "multi":
            held.setdefault((r.pick.race, r.pick.kind), []).append(r)
    by_multi = {r.pick.multi.key: r for r in routed if r.pick.multi is not None}
    quaddies = [q for q in picks.quaddies if q.recommended and q.races]
    races = []
    for rp in picks.races:
        race = rp.model.race
        n = race.number
        is_open = n in open_races
        board = []
        for kind in KINDS:
            if mine_ := held.get((n, kind)):  # each placed bet is its own line; no new pick
                board += [x for r in mine_ if (x := _horse_line(rp, kind, r, race_date, on))]
                continue
            r = slot.get((n, kind))
            if is_open or r is not None:
                if line := _horse_line(rp, kind, r, race_date, on):
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
            if mine_ := held.get((n, kind)):
                exotics += [
                    x for r in mine_ if (x := _exotic_line(n, kind, e, r, race_date, on))
                ]
                continue
            r = slot.get((n, kind))
            if (is_open and e is not None) or r is not None:
                if line := _exotic_line(n, kind, e, r, race_date, on):
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
    # The day's likeliest multis (money or not), then any ticked as placed that have dropped out.
    lines = [_multi_line(m, by_multi.get(m.key), race_date, on) for m in day_list]
    shown = {m.key for m in day_list}
    lines += [
        _multi_line(r.pick.multi, r, race_date, on)
        for k, r in by_multi.items()
        if r.placed and k not in shown and r.pick.multi is not None
    ]
    payback = None
    if promos and pb and pb > 0:
        _mark_booster(races)
        payback = _payback_line(picks, open_races, race_date)
    _mark_settled(
        [x for rc in races for x in rc.board + rc.exotics] + lines,
        placed,
        {rp.model.race.number: rp.model.race for rp in picks.races},
    )
    return DayCard(races, len(open_races), lines, payback)


def _mark_settled(lines: list[Line], placed: list[Placed], races: dict) -> None:
    """Each placed line carries how its recorded bet settled (melbcup.bets.settle)."""
    done = {(p.race, p.kind, p.key, p.account): settle_bet(p, races) for p in placed}
    for line in lines:
        if line.placed:
            key = line.key if line.kind == "multi" else (line.number or 0)
            line.settled = done.get((line.race, line.kind, key, line.account))


def _mark_booster(races: list) -> None:
    """PointsBet "Daily Booster, Racing Singles" (one a day, boost unknown): flag the one win or
    place single routed to PointsBet in the open races with the biggest expected boosted gain,
    stake x chance x (price - 1) at PointsBet's price. Each way is skipped."""
    best, best_gain = None, 0.0
    for rc in races:
        if not rc.open:
            continue
        for line in rc.board:
            if line.account != "pointsbet" or line.kind not in ("win", "place"):
                continue
            prices = rc.race.prices.get(line.number)
            price = prices and (
                prices.pointsbet_win if line.kind == "win" else prices.pointsbet_place
            )
            gain = booster_gain(line.stake, line.chance, price)
            if gain is not None and gain > best_gain:
                best, best_gain = line, gain
    if best is not None:
        best.booster, best.booster_note = BOOSTER_PILL, BOOSTER_NOTE


def _payback_line(picks, open_races: set[int], race_date: date) -> Line | None:
    """The PointsBet Pay Back multi as a card: legs, PointsBet price, chance and value per $1.
    Not part of the day's money sharing (no stake)."""
    found = payback_multi([rp.model for rp in picks.races if rp.model.race.number in open_races])
    if found is None:
        return None
    m, ev = found
    line = Line(
        m.race,
        "multi",
        chance=m.prob,
        pills=[Pill("pb", price_text(m.price), True)],
        sportsbet_only=True,
        key=m.key,
        multi_legs=[(leg.race, leg.number, leg.name, LABELS[leg.kind]) for leg in m.legs],
        price=m.price,
    )
    line.title = f"PointsBet Pay Back multi, {len(m.legs)} legs"
    line.say = f"Lands {one_in(m.prob)}."
    line.value_note = (
        f"Worth {ev:+.2f} per $1 with the pay back (stake back as a bonus bet if it loses), "
        f"up to ${PB_PAYBACK_MAX:g} on PointsBet."
    )
    return line


# -- the Melbourne Cup offer (POINTSBET=1) ------------------------------------------------------

CUP_NAME = "melbourne cup"


@dataclass
class CupNote:
    """PointsBet's "Run 2nd, You Win": a win bet that also pays as a winner if the horse runs
    2nd. ``value`` is the runner's top-2 chance times its PointsBet win price, less 1: what $1
    is worth in the long run, if the model's chances are right."""

    number: int
    name: str
    top2: float
    price: float
    value: float


def cup_note(rp) -> CupNote | None:
    """The runner with the best value in PointsBet's Run 2nd, You Win offer on the Melbourne Cup
    (a race named with "Melbourne Cup"), or None for any other race or when PointsBet has no
    win prices. A note for the page, never a stake."""
    race = rp.model.race
    if CUP_NAME not in (race.name or "").lower():
        return None
    win = {a.number: a.win for a in rp.model.ranked()}
    priced = {
        n: p.pointsbet_win for n, p in race.prices.items() if n in win and p.pointsbet_win
    }
    if len(win) < 2 or not priced:
        return None
    top2 = top_k_probs(win, 2)
    n = max(priced, key=lambda k: (top2[k] * priced[k], k))
    runner = race.runner(n)
    name = runner.name if runner else str(n)
    return CupNote(n, name, top2[n], priced[n], top2[n] * priced[n] - 1)
