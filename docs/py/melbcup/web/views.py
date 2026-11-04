"""Pages and actions, independent of any web framework.

The FastAPI server (app.py) and the browser build (melbcup/browser.py, GitHub Pages) both route
requests here: ``page()`` renders a path to HTML, ``action()`` does what a button asks and says
where to go next.
"""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from melbcup import history
from melbcup.bets import LABELS, PRICE_VERDICTS, VALUE_KINDS, confidence, price_verdict
from melbcup.bets.grade import grade_day
from melbcup.bets.promos import PROMOS
from melbcup.bets.settle import DayResult, settle_all, settle_bet, settle_extra, signed
from melbcup.config import MELBOURNE, Settings
from melbcup.live import LiveBoard
from melbcup.web import asynym, racecard
from melbcup.web.racecard import (
    EXTRA_COOKIE,
    KIDS_COOKIE,
    PICKS_COOKIE,
    PLACED_COOKIE,
    build_day,
    cup_note,
    final_picks,
    open_picks,
    parse_extras,
    parse_kids,
    parse_placed,
    pick_amounts,
    pick_pointsbet,
    wallet,
)

HERE = Path(__file__).parent
BOOKMAKERS = {
    "sportsbet": "Sportsbet",
    "betfair": "Betfair",
    "tab": "TAB",
    "ladbrokes_au": "Ladbrokes",
    "neds": "Neds",
    "pointsbetau": "PointsBet",
    "betright": "BetRight",
    "playup": "PlayUp",
    "betr_au": "Betr",
    "unibet_au": "Unibet",
    "bet365_au": "bet365",
    "betdeluxe": "BetDeluxe",
    "betgold": "BetGold",
    "palmerbet": "Palmerbet",
    "picklebet": "Picklebet",
    "boombet": "BoomBet",
    "SP": "SP",
}
MAX_BUDGET = 100_000
DEFAULT_BUDGET = 200.0  # used when neither ?budget= nor the budget cookie says otherwise
BUDGET_COOKIE = "budget"
CARNIVAL = (  # Flemington, Melbourne Cup Carnival 2026: one tap, no lookup
    ("Derby Day", date(2026, 10, 31)),
    ("Cup Day", date(2026, 11, 3)),
    ("Oaks Day", date(2026, 11, 5)),
    ("Stakes Day", date(2026, 11, 7)),
)


def melbourne_today() -> date:
    return datetime.now(MELBOURNE).date()


def _date(text: str | None) -> date | None:
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


def pct(p: float | None, digits: int = 0) -> str:
    return "–" if p is None else f"{100 * p:.{digits}f}%"


def money(x: float | None) -> str:
    if x is None:
        return "–"
    return f"${x:,.2f}" if x < 100 else f"${x:,.0f}"


def edge(ev: float | None) -> str:
    return "–" if ev is None else f"{100 * ev:+.0f}%"


def local_time(dt: datetime | None) -> str:
    if dt is None:
        return "–"
    t = dt.astimezone(MELBOURNE)
    return f"{t.hour % 12 or 12}:{t.minute:02d}{'am' if t.hour < 12 else 'pm'}"


def when(value) -> str:
    """A Melbourne day and time: "Today 11:00am", "Tomorrow 11:00am" or "Thu 6 Nov 11:00am".
    Takes a datetime or an ISO string (as PointsBet and ESPN send them)."""
    if not value:
        return "–"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    t = value.astimezone(MELBOURNE)
    days = (t.date() - melbourne_today()).days
    lead = {0: "Today", 1: "Tomorrow", -1: "Yesterday"}.get(days)
    if lead is None:
        lead = f"{t.strftime('%a')} {t.day} {t.strftime('%b')}"
    return f"{lead} {local_time(t)}"


# Dates without strftime's "%-d", which the browser build's C library does not support.
def day(d: date) -> str:
    return f"{d:%a} {d.day} {d:%b}"


def shortdate(d: date) -> str:
    return f"{d.day} {d:%b}"


def isoday(text: str) -> str:
    return day(date.fromisoformat(text))


def racename(name: str | None) -> str:
    """Racing Australia sends some names in capitals; show them in normal case."""
    if not name or not name.isupper():
        return name or ""
    small = {"And", "Of", "The", "At", "For", "On", "By"}
    words = [w.lower() if w[:1].isdigit() else w.capitalize() for w in name.split()]
    return " ".join(w.lower() if i and w in small else w for i, w in enumerate(words))


def longdate(d: date) -> str:
    return f"{day(d)} {d.year}"


def until(dt: datetime | None) -> str:
    if dt is None:
        return ""
    mins = int((dt - datetime.now(UTC)).total_seconds() // 60)
    if mins < -5:
        return "run"
    if mins <= 0:
        return "jumping"
    if mins < 60:
        return f"in {mins} min"
    return f"in {mins // 60} h {mins % 60:02d} min"


def book(key: str | None) -> str:
    return "–" if not key else BOOKMAKERS.get(key, key.replace("_au", "").title())


def statline(s) -> str:
    return "–" if s is None else f"{s.starts}: {s.wins}-{s.top3 - s.wins}"


@dataclass(frozen=True)
class Call:
    """One verdict for the page: bet (with its stake), hold, or skip.

    A bet is never shown without a dollar amount: a bet Call with no stake, or a stake of zero,
    becomes a hold. Build bets with ``Call.bet(stake)``.
    """

    kind: str  # "bet" | "hold" | "skip"
    stake: int | None = None

    def __post_init__(self) -> None:
        if self.kind == "bet" and not (self.stake and self.stake > 0):
            object.__setattr__(self, "kind", "hold")
        if self.kind != "bet":
            object.__setattr__(self, "stake", None)

    @classmethod
    def bet(cls, stake: int | None) -> Call:
        return cls("bet", stake)


def call(value: bool, stake: int | None, price: float | None, chance: float | None) -> Call:
    """The existing value rule says bet, and the stake makes it a bet; otherwise a price the
    verdict calls "Short: skip" is a skip and anything else is a hold. No new thresholds."""
    if value:
        return Call.bet(stake)
    verdict = price_verdict(price, chance)
    return Call("skip" if verdict and verdict.startswith(PRICE_VERDICTS[-1][1]) else "hold")


def single_call(s) -> Call:
    """Verdict for one Single (a win, place or each-way line)."""
    return call(s.value, s.stake, s.sportsbet or s.price, s.prob)


def runner_call(rp, number: int) -> Call:
    """One verdict for a runner: bet when any of its singles is value (with the stake the day's
    picks put on it), otherwise hold or skip on its win price."""
    mine = [s for s in rp.singles if s.number == number]
    value = [s for s in mine if s.value]
    if value:
        stake = next(
            (rp.best[s.kind].stake for s in value if rp.best.get(s.kind) is s and s.stake), None
        )
        return Call.bet(stake)
    a = next((a for a in rp.model.ranked() if a.number == number), None)
    prices = rp.model.race.prices.get(number)
    price = prices and (
        prices.sportsbet_win or (prices.best_win.price if prices.best_win else None)
    )
    return call(False, None, price, a.win if a else None)


def race_call(rp) -> Call:
    """One verdict for a race: bet when a win, place or each-way line is a value bet, carrying
    the dollars of those lines together; otherwise the verdict on its most likely winner.
    Exotics carry their own verdicts on their own lines."""
    lines = {id(s): s for k in VALUE_KINDS if (s := rp.best.get(k)) is not None}
    if lines:  # one runner can be the best win and the best each way: count each line once
        return Call.bet(sum(s.stake or 0 for s in lines.values()))
    top = rp.best.get("top_win")
    return runner_call(rp, top.number) if top else Call("hold")


def multis_call(picks) -> Call:
    """The summary verdict for quaddies and multis: the dollars on the recommended quaddies and
    the value multis that have stakes, or a hold when there are none."""
    total = sum(e.outlay or 0 for e in picks.quaddies if e.recommended)
    total += sum(m.stake or 0 for m in picks.multis if m.value)
    return Call.bet(total)


def open_races(picks) -> set[int]:
    """Numbers of the races still to run."""
    return {rp.model.race.number for rp in picks.races if betting_open(rp.model.race)}


def countdown(picks, now: datetime) -> list[dict]:
    """The open races that still have an advertised start ahead, soonest first: the data the
    "R2 jumps in 4:12" strip counts down to (number, start as ISO, seconds left at ``now``)."""
    if not picks:
        return []
    ahead = [
        rp.model.race
        for rp in picks.races
        if betting_open(rp.model.race)
        and rp.model.race.start_time is not None
        and rp.model.race.start_time > now
    ]
    ahead.sort(key=lambda r: r.start_time)
    return [
        {
            "n": r.number,
            "t": r.start_time.isoformat(),
            "left": int((r.start_time - now).total_seconds()),
        }
        for r in ahead
    ]


def betting_open(race) -> bool:
    """A race that has not run: no result yet and not started more than a few minutes ago."""
    return race.result is None and (race.start_time is None or until(race.start_time) != "run")


def asset_version(new_ui: bool = False) -> str:
    """Cache-buster for /static: the first 10 hex chars of the sha256 over the static assets, so a
    phone re-fetches app.css and app.js the moment either changes. Computed once per env. With
    the AsynymBet pages (ASYNYM=1) asynym.css and asynym.js count too."""
    digest = hashlib.sha256()
    names = sorted((HERE / "static").glob("app.*"))
    if new_ui:
        names += sorted((HERE / "static").glob("asynym.*"))
    for path in names:
        digest.update(path.read_bytes())
    return digest.hexdigest()[:10]


def make_env(new_ui: bool = False) -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(HERE / "templates")), autoescape=select_autoescape(["html"])
    )
    env.filters.update(
        pct=pct,
        money=money,
        edge=edge,
        local_time=local_time,
        until=until,
        book=book,
        statline=statline,
        day=day,
        shortdate=shortdate,
        longdate=longdate,
        isoday=isoday,
        racename=racename,
        confidence=confidence,
        verdict=price_verdict,
    )
    if new_ui:
        env.filters.update(ring_tone=asynym.tone, ring_pct=asynym.pct_of)
    env.globals.update(
        LABELS=LABELS,
        Call=Call,
        call_for=call,
        runner_call=runner_call,
        single_call=single_call,
        race_call=race_call,
        multis_call=multis_call,
        betting_open=betting_open,
        open_races=open_races,
    )
    env.globals["shown"] = history.shown
    env.globals["asset_v"] = asset_version(new_ui)
    env.filters.update(
        one_in=racecard.one_in,
        signed=signed,
        dollars=racecard.dollars,
        price=racecard.price_text,
        jump=racecard.jump,
        pills=racecard.pills,
        iso_time=when,
        when=when,
        before=lambda dt, minutes: local_time(dt - timedelta(minutes=minutes)) if dt else "",
    )
    return env


def parse_budget(text: str | None) -> float | None:
    raw = (text or "").strip().lstrip("$")
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if 0 < value <= MAX_BUDGET else None


def pick_budget(
    query: Mapping[str, str], cookies: Mapping[str, str] | None = None
) -> tuple[float, bool]:
    """The day budget and whether the owner chose it: ?budget=, else the budget cookie, else
    $200. A ?budget= that is blank or not a number puts the budget back to the default."""
    if "budget" in query:
        chosen = parse_budget(query["budget"])
        return (chosen or DEFAULT_BUDGET), chosen is not None
    remembered = parse_budget((cookies or {}).get(BUDGET_COOKIE))
    return (remembered or DEFAULT_BUDGET), remembered is not None


class NotFound(LookupError):
    pass


@dataclass
class TodayMoney:
    """The header's day profit or loss (today's racing bets and NBA challenge stages)."""

    profit: float

    def fill(self, total: float) -> float:
        if not self.profit:
            return 0.0
        return 100.0 if total <= 0 else min(100.0, 100.0 * abs(self.profit) / total)


def _nba_money(path, query, cookies, today):
    """The NBA challenge state (with this request's action applied on /nba) and today's money."""
    try:
        from melbcup import nba_challenge
    except ImportError:  # the phone's offline copy leaves the NBA code out
        return None, {}, 0.0
    state = nba_challenge.parse((cookies or {}).get(nba_challenge.COOKIE))
    if path == "/nba" and "ch" in query:
        state = nba_challenge.apply(state, query, today.isoformat())
    used, profit = nba_challenge.today_money(state, today.isoformat())
    return state, used, profit


class Views:
    def __init__(self, settings: Settings, board: LiveBoard, *, browser: bool = False):
        self.settings = settings
        self.board = board
        self.browser = browser  # no threads: loads run to completion before the page renders
        self.env = make_env(settings.asynym)
        self._nba = None  # NbaFeed, made on the first visit to /nba
        self._agencies_on: set[str] = set()

    def _challenge(self, query: Mapping[str, str], ctx: dict) -> dict:
        """The $10 -> $1000 challenge (cookie on the phone; app.py saves the change)."""
        try:
            from melbcup import nba_challenge, nba_legs
        except ImportError:  # the phone's offline copy leaves the NBA code out
            return {"ch": None, "ch_step": None}
        state = ctx.get("ch_state")
        if state is not None and state.get("active") is False:
            state = None  # no run on: the start screen (history and bets stay in the cookie)
        legs_now = (ctx["nba_rep"] or {}).get("all_legs") or []
        p_start = nba_challenge._money(query.get("chstart")) or 10.0
        p_goal = max(nba_challenge._money(query.get("chgoal")) or 1000.0, p_start * 2)
        p_keep = query.get("chkeep", "1") == "1" if query.get("chplan") else True
        preview = (
            []
            if state is not None
            else self._stage_preview(legs_now, nba_challenge, nba_legs, p_start, p_goal, p_keep)
        )
        best, why = nba_challenge.recommend(preview) if preview else (None, "")
        step, games, wait, push, alt_agency = None, [], None, [], None
        if state is not None:
            x = nba_challenge.next_x(state)
            # only games this stage may use: spaced from tonight's earlier stage, or a later night
            legs = [g for g in legs_now if nba_challenge.allowed(state, g.get("startsAt"))]
            if state.get("mode", "game") == "game":
                games = nba_legs.same_game_for(legs, x, stake=state["bank"])
                step = max(games, key=lambda m: m["chance"]) if games else None
                alt_agency = self._best_elsewhere(state, x, step, nba_challenge, nba_legs)
            else:
                step = nba_legs.stack_for(legs, x, stake=state["bank"])
            earliest, not_night = nba_challenge.next_window(state)
            if not step and (earliest or not_night):
                wait = {"after": earliest, "night": not_night}
            n = len(state["steps"]) + 1
            due = nba_challenge.result_due(state)
            alerts = []
            if due:
                alerts.append(
                    {
                        "n": n,
                        "t": due.isoformat(),
                        "label": f"Stage {n} result due",
                        "href": "/nba?tab=challenge",
                        "alert": 0,
                    }
                )
            elif step and step.get("startsAt"):
                alerts.append(
                    {
                        "n": n,
                        "t": step["startsAt"],
                        "label": f"Stage {n} tips off",
                        "href": "/nba?tab=challenge",
                        "alert": 900,
                    }
                )
            # the same times, for the phone alerts the Function pushes (melbcup/push_store.py)
            for a in alerts:
                when = datetime.fromisoformat(a["t"].replace("Z", "+00:00"))
                if a["label"].endswith("result due"):
                    push.append(
                        {
                            "at": when.isoformat(),
                            "title": f"Stage {n} result due",
                            "body": "Mark it won or lost and the next stage is ready.",
                            "url": "/nba?tab=challenge",
                        }
                    )
                else:
                    game = (step or {}).get("game") or "the next game"
                    push.append(
                        {
                            "at": (when - timedelta(minutes=15)).isoformat(),
                            "title": f"Stage {n} tips off in 15 min",
                            "body": f"{game}: place it now.",
                            "url": "/nba?tab=challenge",
                        }
                    )
            now = datetime.now(UTC)
            for a in alerts:
                when = datetime.fromisoformat(a["t"].replace("Z", "+00:00"))
                if when > now:
                    ctx["countdown"] = sorted(
                        ctx["countdown"] + [a | {"left": int((when - now).total_seconds())}],
                        key=lambda r: r["t"],
                    )
        return {
            "push_reminders": push,
            "ch": state,
            "ch_step": step,
            "ch_alt_agency": alt_agency,
            "ch_games": games,
            "ch_preview": preview,
            "ch_best": best,
            "ch_night": nba_challenge.night(nba_challenge._when(step.get("startsAt")))
            if (state and step and nba_challenge._when(step.get("startsAt")))
            else None,
            "ch_why": why,
            "ch_plan": {"start": p_start, "goal": p_goal, "keep": p_keep},
            "ch_wait": wait,
            "ch_finish": nba_challenge.finish_chance(
                step["chance"], state, nba_challenge.typical([g["chance"] for g in games])
            )
            if (state and step)
            else None,
            "ch_due": nba_challenge.result_due(state) if state else None,
            "ch_x": nba_challenge.next_x(state) if state else None,
            "ch_left": nba_challenge.remaining(state) if state else None,
        }

    def _best_elsewhere(self, state, x, step, nba_challenge, nba_legs) -> dict | None:
        """The same stage at the other agencies: their likeliest same-game multi for this payout.
        Returned when one beats the shown pick (owner, 2026-11-05: place where it pays most, as a
        better price means safer legs for the same stage)."""
        view = (self._nba._view[1] or {}) if self._nba else {}
        names = {"sb": "Sportsbet", "pb": "PointsBet"}
        best = None
        for code, a in (view.get("agencies") or {}).items():
            if code == getattr(self, "_nba_pick", None):
                continue
            legs = [
                g
                for g in ((a.get("report") or {}).get("all_legs") or [])
                if nba_challenge.allowed(state, g.get("startsAt"))
            ]
            found = nba_legs.same_game_for(legs, x, stake=state["bank"])
            top = max(found, key=lambda m: m["chance"]) if found else None
            if top and (best is None or top["chance"] > best["chance"]):
                best = top | {
                    "code": code,
                    "name": names.get(code, code),
                    "on": code in self._agencies_on,
                }
        if best and (step is None or best["chance"] > step["chance"] + 0.01):
            return best
        return None

    def _stage_preview(self, legs, nba_challenge, nba_legs, start=10.0, goal=1000.0, keep=True):
        """The set-up table for this start and goal (nba_challenge.plan): per stage count, the
        payout a stage, tonight's best and typical stage chance and the run's. Kept per lines and
        goal, so only a new goal does the search (about a second)."""
        key = (id(legs), len(legs), round(goal / start, 3), keep)
        cache = self.__dict__.setdefault("_plan_cache", {})
        if key not in cache:

            def chances_for(xmap):
                many = nba_legs.same_game_many(legs, list(set(xmap.values())))
                return {n: [g["chance"] for g in many[x]] for n, x in xmap.items()}

            if len(cache) > 8:
                cache.clear()
            cache[key] = nba_challenge.plan(start, goal, keep, chances_for)
        return cache[key]

    def warm_nba(self) -> None:
        """Load the NBA page data in the background when the app starts (owner: fast pages)."""
        try:
            from melbcup.nba_feed import NbaFeed

            if self._nba is None:
                self._nba = NbaFeed()
            self._nba.view()
        except Exception:  # the page loads it on first visit instead
            pass

    def _nba_view(self, query: Mapping[str, str]) -> dict:
        try:
            from melbcup.nba_feed import NbaFeed
        except ImportError:  # the phone's offline copy (GitHub Pages) leaves the live NBA code out
            v = {
                "board": None,
                "source": "",
                "stale": False,
                "games": 0,
                "priced_at": None,
                "error": "The NBA page needs the live site: open bet.asynym.dev.",
            }
            return {"nba": v, "nba_tab": "legs", "nba_rep": {}, "nba_games": {}}
        if self._nba is None:
            self._nba = NbaFeed()
        v = self._nba.view()
        tab = query.get("tab")
        tab = tab if tab in ("stacks", "challenge", "games", "same", "all") else "stacks"
        # Prices from the agency picked here (?bk=), else the first agency switched ON in Agencies
        # that has NBA lines (Sportsbet first), else whichever has lines: the chances are the
        # model's either way; the lines and prices are that agency's.
        agencies = v.get("agencies") or {}
        on = self._agencies_on
        has = [c for c in ("sb", "pb") if (agencies.get(c) or {}).get("report", {}).get("all_legs")]
        pick = query.get("bk") if query.get("bk") in agencies else None
        pick = pick or next((c for c in has if c in on), None) or (has[0] if has else None)
        pick = pick or next(iter(agencies), None)
        chosen = agencies.get(pick) or {}
        self._nba_pick = pick
        rep = chosen.get("report") or v.get("report") or {}
        games = {g["name"].replace(" at ", " @ "): g for g in (v["board"] or {}).get("games", [])}
        names = {"sb": "Sportsbet", "pb": "PointsBet"}
        chips = [
            {
                "code": c,
                "name": names.get(c, c),
                "lines": len((agencies[c].get("report") or {}).get("all_legs") or []),
                "on": c in on,
            }
            for c in ("sb", "pb")
            if c in agencies
        ]
        # With both agencies switched on: a bubble when the other one pays more for the same bet
        alt_prices, alt_code = {}, None
        other = next((c for c in ("sb", "pb") if c != pick and c in agencies), None)
        if other and other in on and pick in on:
            from melbcup.nba_legs import bet_key, better_elsewhere

            alt_code = other.upper()
            for g in (agencies[other].get("report") or {}).get("all_legs") or []:
                alt_prices[bet_key(g)] = max(g["price"], alt_prices.get(bet_key(g), 0))

            def alt_pay(item):
                return better_elsewhere(item, alt_prices, alt_code) if item else None
        else:

            def alt_pay(item):
                return None

        return {
            "alt_pay": alt_pay,
            "nba": v,
            "nba_tab": tab,
            "nba_rep": rep,
            "nba_games": games,
            "nba_agency": pick,
            "nba_agency_name": names.get(pick, "PointsBet"),
            "nba_chips": chips,
            "nba_agency_games": chosen.get("games", v.get("games")),
            "nba_agency_error": chosen.get("error"),
        }

    def _context(
        self, path: str, query: Mapping[str, str], cookies: Mapping[str, str] | None = None
    ) -> dict:
        snap = self.board.snapshot()
        now = datetime.now(UTC)
        cookies = cookies or {}
        sb, bf, chosen = pick_amounts(query, cookies)
        # PointsBet (POINTSBET=1): a third account, $0 until the owner sets an amount. It is
        # judged in the picks only once it has money, so the switch alone changes no price.
        pb = pick_pointsbet(query, cookies) if self.settings.pointsbet else None
        az = None
        if self.settings.asynym:  # ASYNYM=1: an OFF account gets $0, so nothing routes there
            az = asynym.choose(query, cookies, self.settings)
            sb, bf, pb = az.routed()
            chosen = True
        placed = parse_placed(cookies.get(PLACED_COOKIE), snap.race_date, pb is not None)
        day_total = sb + bf + (pb or 0.0)
        if snap.models and self.settings.promos:  # PROMOS=1: promos that beat the Win pick
            picks = snap.picks(day_total or None, bool(pb), PROMOS)
        elif snap.models:
            picks = snap.picks(day_total or None, True) if pb else snap.picks(day_total or None)
        else:
            picks = None
        grade = (
            grade_day(picks) if picks and any(rp.model.race.result for rp in picks.races) else None
        )
        races = (
            {rp.model.race.number: rp.model.race for rp in picks.races}
            if picks
            else {r.number: r for r in (snap.card.races if snap.card else [])}
        )
        marks = {rg.race: {g.kind: g for g in rg.lines} for rg in (grade.races if grade else [])}
        card = (
            build_day(
                picks, sb, bf, placed, open_races(picks), snap.race_date, pb, self.settings.promos
            )
            if picks
            else None
        )
        # The kids' bets (their own cookie) come off the wallet and count in the day's profit
        # and loss, but they are not the owner's own bets: nothing else treats them as placed.
        kids = parse_kids(cookies.get(KIDS_COOKIE), snap.race_date, pb is not None)
        for k in kids:
            k.settled = settle_bet(k.bet, races)
        extras = parse_extras(cookies.get(EXTRA_COOKIE), snap.race_date, pb is not None)
        for x in extras:
            x.settled = settle_extra(x.bet, races)
        mine = settle_all(placed, races)
        kids_by_race: dict[int, list] = {}
        for k in kids:
            kids_by_race.setdefault(k.bet.race, []).append(k)
        wal = wallet(sb, bf, placed + [k.bet for k in kids] + [x.settled.bet for x in extras], pb)
        if az is not None:
            az.apply_wallet(wal)
        # The header's "Today": only today's bets. A meeting from another day (yesterday's card
        # still loaded) keeps its bets on Mine but neither its loss nor its stakes count today;
        # NBA challenge stakes come off their agency and wins pay back into it.
        today = melbourne_today()
        racing_today = snap.race_date == today
        day_bets = DayResult(mine.bets + [k.settled for k in kids] + [x.settled for x in extras])
        ch_state, nba_used, nba_profit = _nba_money(path, query, cookies, today)
        if az is not None:
            for a in az.agencies:
                a.used = (a.used if racing_today else 0.0) + nba_used.get(a.code, 0.0)
        day_pnl = TodayMoney((day_bets.profit if racing_today else 0.0) + nba_profit)
        return {
            "push_key": os.environ.get("VAPID_PUBLIC_KEY", ""),  # phone alerts, in Settings
            "day_pnl": day_pnl,
            "ch_state": ch_state,
            "az": az,
            "settings": self.settings,
            "browser": self.browser,
            "snap": snap,
            "card": snap.card,
            "day": card,
            "wallet": wal,
            "pnl": DayResult(mine.bets + [k.settled for k in kids] + [x.settled for x in extras]),
            "extras": extras,
            "extra_races": {
                n: [[r.number, r.name] for r in rc.starters] for n, rc in sorted(races.items())
            },
            "pnl_own": mine,
            "kids": kids_by_race,
            "kids_in": bool(kids),
            "finals": final_picks(cookies.get(PICKS_COOKIE), snap.race_date, pb is not None, races),
            "amounts_chosen": chosen,
            "race_date_iso": snap.race_date.isoformat() if snap.race_date else "",
            "budget": day_total,
            "budget_q": "",
            "picks": picks,
            "grade": grade,
            "marks": marks,
            "checks": snap.checks,
            "today": melbourne_today(),
            "here": path,
            "can_fetch": self.board.can_fetch,
            "now": now,
            "countdown": countdown(picks, now),
            "picks_data": open_picks(card, snap.race_date),
        }

    def page(
        self, path: str, query: Mapping[str, str], cookies: Mapping[str, str] | None = None
    ) -> str:
        """HTML for a page path; raises NotFound. ``cookies`` carries the remembered budget."""
        t0 = time.perf_counter()
        ctx = self._context(path, query, cookies)
        self.timing = {"context": time.perf_counter() - t0}
        ctx["cookies"] = cookies or {}
        if self.settings.asynym and path != "/history":
            return self._asynym_page(path, query, ctx)
        if path == "/":
            return self.env.get_template("day.html").render(ctx)
        if path == "/history":
            archive = self.board.archive
            saved = archive.history() if archive is not None else []
            record = history.merge(saved, self.board.history())
            ctx.update(
                record=record,
                tallies=history.tally(record),
                by_confidence=history.by_confidence(record),
                h2h=history.head_to_head(record),
                groups=history.meetings(record),
                saved_count=len(saved),
                check_totals=self.board.check_totals(),
            )
            return self.env.get_template("history.html").render(ctx)
        if path == "/meetings":
            ctx.update(self._meetings(ctx, query))
            return self.env.get_template("meetings.html").render(ctx)
        if path.startswith("/race/"):
            self._race_context(path, ctx)
            rp = ctx["rp"]
            ctx["cup_note"] = cup_note(rp) if self.settings.pointsbet and ctx["rc"].open else None
            if ctx["cup_note"] and any(x.promo for x in ctx["rc"].board):
                ctx["cup_note"] = None  # the Win bet already is the promo bet, shown on its line
            return self.env.get_template("race.html").render(ctx)
        raise NotFound(path)

    def _meetings(self, ctx: dict, query: Mapping[str, str]) -> dict:
        """The meeting lists for a date (?date=, else the loaded meeting's): the meetings found
        for it and the Cup Carnival days."""
        pick = _date(query.get("date")) or ctx["snap"].race_date
        archive = self.board.archive
        saved = archive.venues(pick) if archive and pick < ctx["today"] else []
        return dict(
            pick=pick,
            found=saved or ctx["snap"].meetings.get(pick),
            carnival=CARNIVAL,
            here=f"/meetings?date={pick.isoformat()}",
        )

    def _asynym_page(self, path: str, query: Mapping[str, str], ctx: dict) -> str:
        """The AsynymBet pages (ASYNYM=1): Home, Race days, a meeting's races, a race, Mine."""
        day, snap = ctx["day"], ctx["snap"]
        ctx["pb_on"] = ctx["az"].get("pb").on
        ctx["tab_q"] = query.get("tab", "")
        ctx["path"] = path
        ctx["keep"] = {k: query[k] for k in ("tab", "date") if k in query}
        ctx["nav"] = {"/": "home", "/mine": "mine", "/nba": "nba"}.get(path, "days")
        if path == "/nba":
            self._agencies_on = set(ctx["az"].codes_on) if ctx.get("az") else set()
            t0 = time.perf_counter()
            ctx.update(self._nba_view(query))
            self.timing["nba"] = time.perf_counter() - t0
            if ctx["nba_tab"] == "challenge":  # the challenge lives on its own tab only (owner)
                t0 = time.perf_counter()
                ctx.update(self._challenge(query, ctx))
                self.timing["challenge"] = time.perf_counter() - t0
            return self.env.get_template("asynym/nba.html").render(ctx)
        if path == "/":
            ctx.update(self._meetings(ctx, {}))
            ctx["takes"] = asynym.home_takes(day, race_call, snap.race_date) if day else []
            return self.env.get_template("asynym/home.html").render(ctx)
        if path == "/meetings":
            ctx.update(self._meetings(ctx, query))
            today = ctx["today"]
            dates = {today, today + timedelta(days=1), ctx["pick"]}
            dates |= {d for _label, d in CARNIVAL if d >= today}
            ctx["chips"] = sorted(dates)
            ctx["carnival_names"] = {d: label for label, d in CARNIVAL}
            return self.env.get_template("asynym/meetings.html").render(ctx)
        if path == "/meeting":
            ctx["rows"] = asynym.race_rows(day, race_call, snap.race_date) if day else []
            return self.env.get_template("asynym/meeting.html").render(ctx)
        if path == "/mine":
            ctx["mine_lines"] = self._my_lines(day)
            ctx["race_objs"] = (
                {rp.model.race.number: rp.model.race for rp in ctx["picks"].races}
                if ctx["picks"]
                else {}
            )
            ctx["kids_all"] = [k for _n, ks in sorted(ctx["kids"].items()) for k in ks]
            ctx["editing"] = query.get("edit") == "1"
            return self.env.get_template("asynym/mine.html").render(ctx)
        if path.startswith("/race/"):
            self._race_context(path, ctx)
            ctx["tab"] = asynym.race_tab(query.get("tab"), ctx["rc"].open)
            takes = asynym.takes(ctx["rc"], snap.race_date) if ctx["rc"].open else []
            ctx["verdict_take"] = bool(takes) and race_call(ctx["rp"]).kind == "bet"
            ctx["takes"] = takes if ctx["verdict_take"] else []
            ctx["elsewhere"] = (
                None
                if ctx["verdict_take"]
                else asynym.best_elsewhere(day, ctx["race"].number, race_call, snap.race_date)
            )
            ctx["top_picks"] = asynym.top_picks(ctx["rc"]) if ctx["rc"].open else []
            ctx["multi"] = asynym.race_multi(day, ctx["race"].number) if ctx["rc"].open else None
            ctx["rows"] = asynym.race_rows(day, race_call, snap.race_date)
            ctx["race_extras"] = [
                x
                for x in ctx["extras"]
                if x.bet.kind == "multi" and any(leg[0] == ctx["race"].number for leg in x.bet.legs)
            ]
            ctx["my_lines"] = self._my_lines(day, ctx["race"].number)
            return self.env.get_template("asynym/race.html").render(ctx)
        raise NotFound(path)

    @staticmethod
    def _my_lines(day, race: int | None = None) -> list:
        """The owner's recorded bets (a race's, or the day's), as card lines."""
        if day is None:
            return []
        lines = [x for rc in day.races for x in rc.board + rc.exotics if x.placed]
        lines += [m for m in day.multis if m.placed]
        return [x for x in lines if race is None or x.race == race]

    def _race_context(self, path: str, ctx: dict) -> None:
        """The race page's own pieces (raises NotFound): shared by the old and new pages."""
        try:
            number = int(path.removeprefix("/race/"))
        except ValueError as exc:
            raise NotFound(path) from exc
        rp = (
            next((r for r in ctx["picks"].races if r.model.race.number == number), None)
            if ctx["picks"]
            else None
        )
        if rp is None:
            raise NotFound(f"Race {number} is not on the card yet")
        ctx["rp"] = rp
        ctx["race"] = rp.model.race
        ctx["rc"] = ctx["day"].race(number)
        ctx["check"] = ctx["checks"].get(number)

    def action(self, name: str, query: Mapping[str, str]) -> str:
        """Do what a button asks; return the path to show next."""
        board = self.board
        back = query.get("next", "/")
        if not back.startswith("/") or back.startswith("//"):
            back = "/"
        if name == "prices":
            board.refresh_prices_now()
        elif name == "results":
            board.fetch_results_now()
        elif name == "load":
            board.load_card_now(wait=self.browser)
        elif name == "auto":
            board.set_auto(query.get("on") == "1")
        elif name == "find":
            pick = _date(query.get("date"))
            if pick is None:
                return "/meetings"
            board.find_meetings(pick)
            return f"/meetings?date={pick.isoformat()}"
        elif name == "meeting":
            pick = _date(query.get("date"))
            ok = pick is not None and board.set_meeting(pick, query.get("venue", ""))
            if self.settings.asynym:  # on to the meeting's races
                return "/meeting" if ok else "/meetings"
            return "/" if ok else "/meetings"
        else:
            raise NotFound(name)
        return back
