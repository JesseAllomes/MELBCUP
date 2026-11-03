"""AsynymBet (ASYNYM=1): the data behind the redesigned pages.

Everything here works from what the existing pages already work out (the day card, the picks,
the multis); nothing is invented. views.py asks for the pieces and the templates in
``templates/asynym/`` draw them.

The six agencies are switched ON or OFF on the phone (cookie ``agencies``, e.g. ``sb,bf,pb``) and
each has today's money in a cookie. ON/OFF only decides where money is tracked and which accounts
bets are shown for: the allocator knows Sportsbet, Betfair and PointsBet, so an OFF account gets a
$0 budget and nothing is routed there. TAB, Ladbrokes and Neds are display-only for now. The
model's prices are never touched.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from urllib.parse import unquote

from melbcup.bets import VALUE_KINDS
from melbcup.config import Settings
from melbcup.domain import betfair_net
from melbcup.web.racecard import (
    BF_COOKIE,
    CODES,
    LABELS,
    PB_COOKIE,
    SB_COOKIE,
    parse_amount,
    pick_amounts,
    price_text,
)

AGENCIES_COOKIE = "agencies"
# code, name, money cookie, query key (the amounts form: ?sb= ?bf= ?pb= and ?tb= ?lb= ?ne=)
AGENCIES = (
    ("sb", "Sportsbet", SB_COOKIE, "sb"),
    ("bf", "Betfair", BF_COOKIE, "bf"),
    ("pb", "PointsBet", PB_COOKIE, "pb"),
    ("tab", "TAB", "tab_budget", "tb"),
    ("lb", "Ladbrokes", "lb_budget", "lb"),
    ("neds", "Neds", "neds_budget", "ne"),
)
CODES_ALL = tuple(a[0] for a in AGENCIES)
ROUTED = ("sb", "bf", "pb")  # the accounts the allocator can send a bet to
MONEY_COOKIES = {a[3]: a[2] for a in AGENCIES if a[0] not in ROUTED}
TABS = ("bet", "field", "result", "mine")
TAB_NAMES = {"bet": "Bet", "field": "Field", "result": "Result", "mine": "Mine"}
MAX_TAKES = 4


def tone(pct: float | None) -> str:
    """The ring's colour: green from 60%, purple 30 to 59%, amber under 30%."""
    if pct is None:
        return "low"
    return "good" if pct >= 60 else "mid" if pct >= 30 else "low"


def pct_of(chance: float | None) -> int:
    return 0 if not chance else max(0, min(100, round(100 * chance)))


# -- the agencies ---------------------------------------------------------------------------------


@dataclass
class Agency:
    code: str
    name: str
    on: bool
    amount: float  # today's money, kept even while the agency is OFF
    used: float = 0.0  # placed in it today (tracked for Sportsbet, Betfair and PointsBet)

    @property
    def left(self) -> float:
        return max(0.0, self.amount - self.used)

    @property
    def routed(self) -> bool:
        return self.code in ROUTED


@dataclass
class Choice:
    agencies: list[Agency]

    @property
    def on(self) -> list[Agency]:
        return [a for a in self.agencies if a.on]

    def get(self, code: str) -> Agency:
        return next(a for a in self.agencies if a.code == code)

    @property
    def codes_on(self) -> list[str]:
        return [a.code for a in self.on]

    def routed(self) -> tuple[float, float, float | None]:
        """(Sportsbet, Betfair, PointsBet) budgets for the allocator: an OFF account gets $0, and
        PointsBet None (no third account) while it is OFF."""
        sb, bf, pb = self.get("sb"), self.get("bf"), self.get("pb")
        return (
            sb.amount if sb.on else 0.0,
            bf.amount if bf.on else 0.0,
            pb.amount if pb.on else None,
        )

    def apply_wallet(self, wallet) -> None:
        for code, _name, _amount, used in wallet.accounts():
            self.get(code).used = used

    @property
    def total(self) -> float:
        return sum(a.amount for a in self.on)

    @property
    def left(self) -> float:
        return sum(a.left for a in self.on)


def parse_codes(raw: str | None) -> list[str] | None:
    """The ``agencies`` cookie: comma separated codes. None when absent."""
    if raw is None:
        return None
    wanted = {c.strip() for c in unquote(raw).split(",")}
    return [c for c in CODES_ALL if c in wanted]


def codes_from_query(query: Mapping[str, str]) -> list[str] | None:
    """A submitted agencies form: ``ag=1`` and ``on_<code>=1`` for each switch that is ON."""
    if "ag" not in query:
        return None
    return [c for c in CODES_ALL if query.get(f"on_{c}")]


def _money(query: Mapping[str, str], cookies: Mapping[str, str], key: str, cookie: str) -> float:
    raw = query[key] if key in query else unquote(cookies.get(cookie) or "")
    value = parse_amount(raw)
    return 0.0 if value is None else value


def choose(query: Mapping[str, str], cookies: Mapping[str, str], settings: Settings) -> Choice:
    """Which agencies are ON and today's money in each. A switch or amount in the query wins over
    the cookie. With no choice made: Sportsbet and Betfair (and PointsBet with POINTSBET=1)."""
    on = codes_from_query(query)
    if on is None:
        on = parse_codes(cookies.get(AGENCIES_COOKIE))
    if on is None:
        on = ["sb", "bf"] + (["pb"] if settings.pointsbet else [])
    sb, bf, _chosen = pick_amounts(query, cookies)
    amounts = {"sb": sb, "bf": bf}
    for code, _name, cookie, key in AGENCIES[2:]:
        amounts[code] = _money(query, cookies, key, cookie)
    return Choice([Agency(c, n, c in on, amounts[c]) for c, n, _k, _q in AGENCIES])


def cookie_changes(query: Mapping[str, str]) -> dict[str, str | None]:
    """The cookies a submitted agencies or amounts form sets (None: delete). Sportsbet, Betfair
    and PointsBet amounts are the existing ones, set by the server's page route."""
    out: dict[str, str | None] = {}
    on = codes_from_query(query)
    if on is not None:
        out[AGENCIES_COOKIE] = ",".join(on)
    for key, cookie in MONEY_COOKIES.items():
        if key in query:
            value = parse_amount(query[key])
            out[cookie] = None if value is None else f"{value:g}"
    return out


# -- bets worth taking ----------------------------------------------------------------------------


def price_at(prices, code: str, kind: str) -> float | None:
    """A runner's price at one agency for a win, place or each-way bet (the win price for each
    way; Betfair before commission). Prices exist for Sportsbet, Betfair and PointsBet only."""
    if prices is None or code not in ROUTED:
        return None
    place = kind == "place"
    return {
        "sb": prices.sportsbet_place if place else prices.sportsbet_win,
        "bf": prices.betfair_place if place else prices.betfair_win,
        "pb": prices.pointsbet_place if place else prices.pointsbet_win,
    }[code]


def _comparable(code: str, price: float | None) -> float:
    return (betfair_net(price) if code == "bf" else price) or 0.0


@dataclass
class Take:
    """One bet the app says is worth taking: a good-price win, place or each-way line."""

    race: int
    start: datetime | None
    kind: str
    number: int
    name: str
    chance: float | None  # the model's chance this bet collects
    fair: float | None
    edge: float  # expected return per $1, minus the $1
    stake: int
    line: object | None  # the card's Line for it, when there is one
    prices: dict[str, float | None] = field(default_factory=dict)  # per routed agency
    prices2: dict[str, float | None] = field(default_factory=dict)  # each way: the place price
    race_date: date | None = None

    @property
    def label(self) -> str:
        return LABELS[self.kind]

    @property
    def record(self) -> str:
        """The placed-bet record the buttons add (see base.html): [date, race, kind, runner,
        account, stake]."""
        if self.line is not None and getattr(self.line, "record", ""):
            return self.line.record
        d = self.race_date.isoformat() if self.race_date else ""
        return json.dumps([d, self.race, CODES[self.kind], self.number, "", self.stake],
                          separators=(",", ":"))

    @property
    def placed_at(self) -> str | None:
        line = self.line
        return line.acct if line is not None and line.placed else None

    def shown(self, code: str) -> str:
        """The price text at an agency: "$8.50", or "$14 / $4.20" for each way, "–" when none."""
        p = self.prices.get(code)
        if not p:
            return "–"
        if self.kind == "each_way" and self.prices2.get(code):
            return f"{price_text(p)} / {price_text(self.prices2[code])}"
        return price_text(p)

    def best(self, on: list[str]) -> tuple[str | None, float | None]:
        """(agency code, price) of the best price among the ON agencies, Betfair counted after
        commission; ties keep the earlier agency."""
        best_code, best_price = None, None
        for code in ROUTED:
            p = self.prices.get(code)
            if code in on and p and (
                best_code is None or _comparable(code, p) > _comparable(best_code, best_price)
            ):
                best_code, best_price = code, p
        return best_code, best_price


def _single(rp, kind: str, number: int):
    best = rp.best.get(kind)
    if best is not None and best.number == number:
        return best
    return next((s for s in rp.singles if s.kind == kind and s.number == number), None)


def _take(rc, kind: str, number: int, stake: int, line, race_date) -> Take | None:
    s = _single(rc.rp, kind, number)
    if s is None or s.ev is None:
        return None
    prices = rc.race.prices.get(number)
    return Take(
        rc.race.number,
        rc.race.start_time,
        kind,
        number,
        s.name,
        s.prob,
        s.fair_price,
        s.ev,
        stake,
        line,
        {c: price_at(prices, c, kind) for c in ROUTED},
        {c: price_at(prices, c, "place") for c in ROUTED} if kind == "each_way" else {},
        race_date,
    )


def takes(rc, race_date: date | None = None) -> list[Take]:
    """The bets worth taking in a race still to run, biggest edge first: the card's good-price
    lines (with their stakes), or the race's value bets when no line carries a stake."""
    if rc is None or not rc.open:
        return []
    out = []
    for line in rc.board:
        if line.kind in VALUE_KINDS and line.good and line.stake > 0 and line.number is not None:
            if t := _take(rc, line.kind, line.number, line.stake, line, race_date):
                out.append(t)
    if not out:
        for kind in VALUE_KINDS:
            s = rc.rp.best.get(kind)
            if s is not None and s.value and s.stake:
                if t := _take(rc, kind, s.number, int(s.stake), None, race_date):
                    out.append(t)
    return sorted(out, key=lambda t: -t.edge)


def is_take(rc, call) -> bool:
    """The race's verdict is TAKE: the existing race verdict says bet and there is a bet to show."""
    return call.kind == "bet" and bool(takes(rc))


def best_elsewhere(day, current: int, call_of, race_date: date | None = None) -> Take | None:
    """The biggest-edge TAKE bet still open on the card, in any race but this one."""
    found = []
    for rc in day.races:
        if rc.race.number != current and rc.open and call_of(rc.rp).kind == "bet":
            found += takes(rc, race_date)
    return max(found, key=lambda t: t.edge, default=None)


def home_takes(day, call_of, race_date: date | None = None) -> list[Take]:
    """Every TAKE bet in the races still to run, in the order they jump."""
    found = []
    for rc in day.races:
        if rc.open and call_of(rc.rp).kind == "bet":
            found += takes(rc, race_date)
    return sorted(
        found,
        key=lambda t: (t.start is None, t.start.timestamp() if t.start else 0.0, t.race, -t.edge),
    )


@dataclass
class Pick:
    """One line of "Top picks worth a shot": a board pick that pays more than its chance."""

    kind: str
    number: int
    name: str
    edge: float
    stake: int
    price: str
    fair: float | None

    @property
    def label(self) -> str:
        return LABELS[self.kind]


def top_picks(rc) -> list[Pick]:
    """Up to four of the race's board picks (win, place, each way) with a positive edge, the
    biggest first."""
    out, seen = [], set()
    for line in rc.board if rc else []:
        key = (line.kind, line.number)
        if line.kind not in VALUE_KINDS or line.number is None or key in seen:
            continue
        s = _single(rc.rp, line.kind, line.number)
        if s is None or s.ev is None or s.ev <= 0:
            continue
        seen.add(key)
        pill = next((p for p in line.pills if p.best), None)
        out.append(
            Pick(
                line.kind,
                line.number,
                line.name,
                s.ev,
                line.stake,
                f"{pill.account.upper()} {pill.text}" if pill else "–",
                s.fair_price,
            )
        )
    return sorted(out, key=lambda p: -p.edge)[:MAX_TAKES]


def race_multi(day, number: int):
    """The likeliest worth-it multi (a "Good price" one) that has a leg in this race, or None."""
    mine = [
        m
        for m in day.multis
        if m.good and any(leg[0] == number for leg in m.multi_legs)
    ]
    return max(mine, key=lambda m: m.chance or 0.0, default=None)


# -- the card as a list of races ---------------------------------------------------------------


@dataclass
class RaceRow:
    rc: object
    state: str  # "take" | "none" | "done"
    takes: list[Take]

    @property
    def stake(self) -> int:
        return sum(t.stake for t in self.takes)


def race_rows(day, call_of, race_date: date | None = None) -> list[RaceRow]:
    rows = []
    for rc in day.races:
        if not rc.open:
            rows.append(RaceRow(rc, "done", []))
            continue
        t = takes(rc, race_date) if call_of(rc.rp).kind == "bet" else []
        rows.append(RaceRow(rc, "take" if t else "none", t))
    return rows


def race_tab(raw: str | None, open_: bool) -> str:
    """The race page's tab from ``?tab=``: Bet while the race can still be bet on, else Result."""
    if raw in TABS:
        return raw
    return "bet" if open_ else "result"
