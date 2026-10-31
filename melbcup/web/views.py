"""Pages and actions, independent of any web framework.

The FastAPI server (app.py) and the browser build (melbcup/browser.py, GitHub Pages) both route
requests here: ``page()`` renders a path to HTML, ``action()`` does what a button asks and says
where to go next.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from melbcup import history
from melbcup.bets import LABELS, PRICE_VERDICTS, VALUE_KINDS, confidence, price_verdict
from melbcup.bets.grade import grade_day
from melbcup.config import MELBOURNE, Settings
from melbcup.live import LiveBoard

HERE = Path(__file__).parent
BOOKMAKERS = {
    "sportsbet": "Sportsbet",
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
    """One verdict for the page: bet (with the stake when there is one), hold, or skip."""

    kind: str  # "bet" | "hold" | "skip"
    stake: int | None = None


def call(value: bool, stake: int | None, price: float | None, chance: float | None) -> Call:
    """The existing value rule says bet; otherwise a price the verdict calls "Short: skip" is a
    skip and anything else is a hold. No new thresholds."""
    if value:
        return Call("bet", stake)
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
        return Call("bet", stake)
    a = next((a for a in rp.model.ranked() if a.number == number), None)
    prices = rp.model.race.prices.get(number)
    price = prices and (
        prices.sportsbet_win or (prices.best_win.price if prices.best_win else None)
    )
    return call(False, None, price, a.win if a else None)


def race_call(rp) -> Call:
    """One verdict for a race: bet when a win, place or each-way line is a value bet, otherwise
    the verdict on its most likely winner. Exotics carry their own verdicts on their own lines."""
    if any(rp.best.get(k) for k in VALUE_KINDS):
        return Call("bet")
    top = rp.best.get("top_win")
    return runner_call(rp, top.number) if top else Call("hold")


def open_races(picks) -> set[int]:
    """Numbers of the races still to run."""
    return {rp.model.race.number for rp in picks.races if betting_open(rp.model.race)}


def betting_open(race) -> bool:
    """A race that has not run: no result yet and not started more than a few minutes ago."""
    return race.result is None and (race.start_time is None or until(race.start_time) != "run")


def make_env() -> Environment:
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
    env.globals.update(
        LABELS=LABELS,
        Call=Call,
        call_for=call,
        runner_call=runner_call,
        single_call=single_call,
        race_call=race_call,
        betting_open=betting_open,
        open_races=open_races,
    )
    env.globals["shown"] = history.shown
    return env


def parse_budget(text: str | None) -> float | None:
    raw = (text or "").strip().lstrip("$")
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if 0 < value <= MAX_BUDGET else None


class NotFound(LookupError):
    pass


class Views:
    def __init__(self, settings: Settings, board: LiveBoard, *, browser: bool = False):
        self.settings = settings
        self.board = board
        self.browser = browser  # no threads: loads run to completion before the page renders
        self.env = make_env()

    def _context(self, path: str, query: Mapping[str, str]) -> dict:
        snap = self.board.snapshot()
        budget = parse_budget(query.get("budget"))
        picks = snap.picks(budget) if snap.models else None
        grade = (
            grade_day(picks) if picks and any(rp.model.race.result for rp in picks.races) else None
        )
        marks = {rg.race: {g.kind: g for g in rg.lines} for rg in (grade.races if grade else [])}
        return {
            "settings": self.settings,
            "browser": self.browser,
            "snap": snap,
            "card": snap.card,
            "budget": budget,
            "budget_q": f"?budget={budget:g}" if budget else "",
            "picks": picks,
            "grade": grade,
            "marks": marks,
            "today": melbourne_today(),
            "here": path + (f"?budget={budget:g}" if budget else ""),
            "can_fetch": self.board.can_fetch,
            "now": datetime.now(UTC),
        }

    def page(self, path: str, query: Mapping[str, str]) -> str:
        """HTML for a page path; raises NotFound."""
        ctx = self._context(path, query)
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
            )
            return self.env.get_template("history.html").render(ctx)
        if path == "/meetings":
            pick = _date(query.get("date")) or ctx["snap"].race_date
            archive = self.board.archive
            saved = archive.venues(pick) if archive and pick < ctx["today"] else []
            ctx.update(
                pick=pick,
                found=saved or ctx["snap"].meetings.get(pick),
                carnival=CARNIVAL,
                here=f"/meetings?date={pick.isoformat()}",
            )
            return self.env.get_template("meetings.html").render(ctx)
        if path.startswith("/race/"):
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
            return self.env.get_template("race.html").render(ctx)
        raise NotFound(path)

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
            return "/" if ok else "/meetings"
        else:
            raise NotFound(name)
        return back
