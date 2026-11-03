"""Keeps the card, models and picks fresh from racing.com (free), without hammering it.

Manual mode does nothing on its own: the page's buttons load the card, refresh prices and fetch
results. A manual price or results refresh is refused within MIN_REFRESH_GAP (60 s) of the last
one, so a public page cannot be used to hammer racing.com; racing.com replies are cached for
the same time.

Auto mode (the default; PRICE_MODE=manual turns it off) keeps the page live on its own:
    the card       once, on the first tick (scratchings arrive with the prices)
    prices         the whole card every 60 s while the prices window is open and any race is
                   still to run; only meetings whose field is out are priced
    results        three minutes after each jump, then every two minutes until every placing
                   is final

Prices are racing.com's fixed odds from Sportsbet, Ladbrokes, PointsBet and bet365; the
Sportsbet price drives the Sportsbet-only multis and the price verdicts. FormFav is optional
enrichment.

Last-minute check (owner, 2026-11-01): after each price check, every race still to run has its
picks saved once 25-35 minutes before the jump ("early") and again at every check in the last
3 minutes ("late"), both at the default amounts ($150 Sportsbet, $50 Betfair). Once the race
has a result both are graded, so the History page can show which does better over many races.
Records only: nothing is placed.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

from melbcup import history
from melbcup.bets import DayPicks, build_picks
from melbcup.bets.allocate import allocate_accounts
from melbcup.bets.grade import _exotic as grade_exotic
from melbcup.config import MELBOURNE, Settings
from melbcup.domain import Card, Race, betfair_net
from melbcup.model.probability import RaceModel, assess
from melbcup.sources import apply_exchange, apply_market, apply_result, load_card
from melbcup.sources.betfair import BetfairClient
from melbcup.sources.formfav import FormFavClient
from melbcup.sources.http import SourceError
from melbcup.sources.racingcom import RacingComClient

if TYPE_CHECKING:
    from melbcup.archive import Archive

log = logging.getLogger("melbcup.live")

QUOTA_BACKOFF = timedelta(minutes=15)
OUTAGE_BACKOFF = timedelta(minutes=1)  # Auto retries a failing racing.com call no faster than this
MIN_REFRESH_GAP = timedelta(seconds=60)  # a manual price or results refresh, however often tapped
FIELD_PUBLISHED = timedelta(days=3)  # Racing Australia publishes acceptances about two days out
RESULTS_AFTER = timedelta(minutes=1)  # first results check, after each jump (owner: quicker)
RESULTS_EVERY = timedelta(seconds=45)  # then again until every placing is final
RESULTS_GAP = timedelta(seconds=20)  # a manual "Check results", however often tapped
RESULTS_GIVE_UP = timedelta(hours=2)  # stop re-checking a race that never turns final
PRICES_EVERY = timedelta(seconds=60)  # Auto prices the whole card this often
CHECK_EARLY = (timedelta(minutes=25), timedelta(minutes=35))  # saved once in this window
CHECK_LATE = timedelta(minutes=3)  # overwritten at every check this close to the jump
CHECK_AMOUNTS = (150.0, 50.0)  # Sportsbet, Betfair: the page's default day amounts
CHECK_KINDS = ("win", "place", "each_way", "quinella", "trifecta", "first_four")
EXOTIC_DEPTH = {"quinella": 2, "trifecta": 3, "first_four": 4}


@dataclass(frozen=True)
class CheckLine:
    """One saved pick: what it was, where it would go, at what price and stake."""

    kind: str
    key: str  # runner number, or the exotic's legs
    name: str
    account: str  # "sportsbet" | "betfair"
    price: float | None  # as that account shows it (Betfair before commission); EW: win price
    stake: int
    place_price: float | None = None  # each way only
    exotic: object | None = field(default=None, compare=False)

    def same(self, other: CheckLine | None) -> bool:
        return other is not None and (self.key, self.account) == (other.key, other.account)


@dataclass(frozen=True)
class RaceCheck:
    """The last-minute check for one race. Kept in memory only: a restart loses it."""

    race: int
    jump: datetime | None
    early: tuple[CheckLine, ...] | None = None
    early_at: datetime | None = None
    late: tuple[CheckLine, ...] | None = None
    late_at: datetime | None = None
    early_back: float | None = None  # dollars back from the early picks, once graded
    late_back: float | None = None
    unknown: bool = False  # some part's dividend was not known: left out of the sums
    graded: bool = False
    winner: str | None = None

    @staticmethod
    def staked(lines) -> int:
        return sum(x.stake for x in lines or ())

    def changes(self) -> list[tuple[str, CheckLine | None, CheckLine | None]]:
        """(kind, late, early) for each kind in either snapshot."""
        early = {x.kind: x for x in self.early or ()}
        late = {x.kind: x for x in self.late or ()}
        return [(k, late.get(k), early.get(k)) for k in CHECK_KINDS if k in early or k in late]

    @property
    def changed(self) -> int:
        return sum(1 for _, now, was in self.changes() if not (now and now.same(was)))


def check_lines(day: DayPicks, routed) -> dict[int, tuple[CheckLine, ...]]:
    """Routed picks as saved lines, per race (quaddies span races and are left out)."""
    out: dict[int, list[CheckLine]] = {}
    for r in routed:
        p = r.pick
        if p.kind not in CHECK_KINDS or not p.stake:
            continue
        if p.single is not None:
            s = p.single
            place = None
            if p.kind == "each_way":
                rp = next(x for x in day.races if x.model.race.number == p.race)
                prices = rp.model.race.prices.get(s.number)
                if prices is not None:
                    place = (
                        prices.betfair_place if r.account == "betfair" else prices.sportsbet_place
                    )
            line = CheckLine(p.kind, str(s.number), s.name, r.account, r.price, p.stake, place)
        else:
            e = p.exotic
            line = CheckLine(
                p.kind, " / ".join(e.leg_labels), e.title, r.account, None, p.stake, exotic=e
            )
        out.setdefault(p.race, []).append(line)
    return {n: tuple(lines) for n, lines in out.items()}


def line_return(line: CheckLine, race: Race) -> float | None:
    """Dollars back from one saved line at its saved price; None when not known."""
    result = race.result

    def at(price: float | None) -> float | None:
        if price is None:
            return None
        return betfair_net(price) if line.account == "betfair" else price

    if line.exotic is not None:
        g = grade_exotic(line.exotic, result, line.kind, EXOTIC_DEPTH[line.kind])
        return None if g.returned is None else g.returned * line.stake
    pos = result.finish.get(int(line.key))
    won = pos == 1
    placed = pos is not None and pos <= race.places_paid
    if line.kind == "win":
        return (None if at(line.price) is None else line.stake * at(line.price)) if won else 0.0
    if line.kind == "place":
        return (None if at(line.price) is None else line.stake * at(line.price)) if placed else 0.0
    half = line.stake / 2
    win_part = (None if at(line.price) is None else half * at(line.price)) if won else 0.0
    place_part = (
        (None if at(line.place_price) is None else half * at(line.place_price)) if placed else 0.0
    )
    return None if win_part is None or place_part is None else win_part + place_part


def grade_check(check: RaceCheck, race: Race) -> RaceCheck:
    unknown = False

    def back(lines) -> float | None:
        nonlocal unknown
        if lines is None:
            return None
        total = 0.0
        for x in lines:
            got = line_return(x, race)
            if got is None:
                unknown = True
            else:
                total += got
        return total

    early, late = back(check.early), back(check.late)
    first = race.result.placegetters(1)
    winner = None
    if first:
        n = first[0]
        runner = race.runner(n)
        winner = f"{n} {race.result.names.get(n) or (runner.name if runner else '')}"
    return replace(
        check,
        early_back=early,
        late_back=late,
        unknown=unknown,
        graded=race.result.status == "final",
        winner=winner.strip() if winner else None,
    )


@dataclass
class Snapshot:
    card: Card | None
    models: list[RaceModel]
    updated_at: datetime | None
    errors: list[str] = field(default_factory=list)
    auto: bool = False
    loading: bool = False
    priced_at: datetime | None = None
    form_at: datetime | None = None
    race_date: date | None = None
    venue: str = ""
    meetings: dict[date, list[str]] = field(default_factory=dict)
    results_at: datetime | None = None
    can_price: bool = False  # the meeting may have a market (see LiveBoard._prices_window)
    saved: bool = False  # a finished meeting opened from the saved copy
    field_due: date | None = None
    betfair: str | None = None  # None: no Betfair login set; else a short status line
    checks: dict[int, RaceCheck] = field(default_factory=dict)  # last-minute check per race

    def picks(self, budget: float | None, pointsbet: bool = False, promos=None) -> DayPicks:
        return build_picks(self.models, budget, pointsbet, promos)


class LiveBoard:
    def __init__(
        self,
        settings: Settings,
        ff: FormFavClient | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        archive: Archive | None = None,
        rc: RacingComClient | None = None,
        bf: BetfairClient | None = None,
    ):
        self.settings = settings
        self.rc = rc  # racing.com: field, prices, results; the app's entry points supply it
        self.ff = ff or (
            FormFavClient(settings.formfav_api_key) if settings.formfav_api_key else None
        )
        self.clock = clock
        self.archive = archive
        self.bf = bf if bf is not None else (
            BetfairClient(
                settings.betfair_username, settings.betfair_password, settings.betfair_app_key
            )
            if settings.betfair_username and settings.betfair_password
            else None
        )
        self._bf_status: str | None = "waiting for the first price check" if self.bf else None
        self._exchange: dict = {}  # race number -> betfair.RacePrices from the last check
        self.auto = settings.auto_refresh
        self.race_date = settings.race_date
        self.venue = settings.venue
        self._meetings: dict[date, list[str]] = {}
        self._results_at: datetime | None = None
        self._history: list[dict] = []  # entries for meetings graded here (not the archive)
        self._lock = threading.Lock()
        self._work = threading.Lock()  # one load or refresh at a time
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._loading = False
        self._card: Card | None = None
        self._models: dict[int, RaceModel] = {}
        self._form_at: datetime | None = None
        self._priced_at: datetime | None = None
        self._price_try: datetime | None = None  # last manual attempt, failed or not
        self._results_try: datetime | None = None
        self._paused_until: datetime | None = None
        self._errors: list[str] = []
        self._updated_at: datetime | None = None
        # Last-minute check per race. In memory only: a restart (or a new deploy) loses it.
        self._checks: dict[int, RaceCheck] = {}

    # -- reading ------------------------------------------------------------------------------

    def snapshot(self) -> Snapshot:
        with self._lock:
            return Snapshot(
                card=self._card,
                models=[self._models[n] for n in sorted(self._models)],
                updated_at=self._updated_at,
                errors=list(self._errors),
                auto=self.auto,
                loading=self._loading,
                priced_at=self._priced_at,
                form_at=self._form_at,
                race_date=self.race_date,
                venue=self.venue,
                meetings=dict(self._meetings),
                results_at=self._results_at,
                can_price=self._prices_window(self.clock()),
                saved=self._archived(self.clock()),
                field_due=self.field_due(self.clock()),
                betfair=self._bf_status,
                checks=dict(self._checks),
            )

    def check_totals(self) -> dict | None:
        """Running totals of the last-minute check over races graded with both snapshots."""
        with self._lock:
            done = [
                c for c in self._checks.values()
                if c.early is not None and c.late is not None and c.early_back is not None
            ]
        if not done:
            return None
        return {
            "races": len(done),
            "early_back": sum(c.early_back for c in done),
            "early_staked": sum(RaceCheck.staked(c.early) for c in done),
            "late_back": sum(c.late_back for c in done),
            "late_staked": sum(RaceCheck.staked(c.late) for c in done),
            "unknown": any(c.unknown for c in done),
        }

    # -- actions ------------------------------------------------------------------------------

    def _guarded(self, now: datetime, fn: Callable[[], None]) -> None:
        """Run one load/refresh, recording errors and pausing Auto after a failure: for 15
        minutes after quota, rate-limit or auth trouble, for a minute after an outage."""
        errors: list[str] = []
        try:
            fn()
        except SourceError as exc:
            log.warning("source error (%s): %s", exc.kind, exc)
            errors.append(str(exc))
            if exc.kind in ("quota", "rate_limit", "auth"):
                self._paused_until = now + QUOTA_BACKOFF
                msg = f"Paused automatic racing.com calls for 15 minutes ({exc.kind})."
                log.warning(msg)
                errors.append(msg)
            elif exc.kind in ("unavailable", "bad_response"):
                self._paused_until = now + OUTAGE_BACKOFF
        with self._lock:
            self._errors = errors

    def _melbourne_day(self, now: datetime) -> date:
        return now.astimezone(MELBOURNE).date()

    def _archived(self, now: datetime) -> bool:
        """Saved meetings stand in for live data only once the day is over: a meeting still to
        come is always fetched fresh (scratchings, race-day predictions)."""
        return (
            self.archive is not None
            and self.race_date < self._melbourne_day(now)
            and self.archive.has(self.race_date, self.venue)
        )

    def _prices_window(self, now: datetime) -> bool:
        """Any meeting whose field is out, today or later: bookmakers frame big meetings two or
        three days ahead, and racing.com is free. Picks lean on the odds: before them the
        form model alone wins far less often."""
        return (
            self.rc is not None
            and self._melbourne_day(now) <= self.race_date
            and self.field_due(now) is None
        )

    def field_due(self, now: datetime) -> date | None:
        """The day the field should appear, while it is too early to ask for it."""
        if self.race_date - self._melbourne_day(now) > FIELD_PUBLISHED:
            return self.race_date - timedelta(days=2)
        return None

    def load_due(self, now: datetime, *, manual: bool = False) -> bool:
        """A card load from the feeds is about to run: the Load button (``manual``), or Auto's
        first load. The browser uses this to fetch the load's requests side by side first."""
        if not self.can_fetch or self.field_due(now) is not None or self._archived(now):
            return False
        if manual:
            return True
        paused = self._paused_until is not None and now < self._paused_until
        return self.auto and self._card is None and not paused

    def _load_form(self, now: datetime) -> None:
        if (due := self.field_due(now)) is not None:
            raise SourceError(
                "racing.com",
                "not_yet",
                f"The field for {self.venue} is published about two days before the meeting. "
                f"It should be out on {due:%A} {due.day} {due:%B}.",
            )
        if self._archived(now):  # saved earlier: nothing to fetch
            card = self.archive.load(self.race_date, self.venue)
        else:
            card = load_card(self.rc, self.ff, self.race_date, self.venue)
        with self._lock:
            self._carry_prices(card)
            self._card = card
            self._form_at = now
            self._models = {r.number: assess(r) for r in card.races}
            self._updated_at = now

    def _load_prices(self, now: datetime) -> None:
        to_run = [r.number for r in self._card.races if r.result is None]
        snaps = self.rc.card_prices(self.race_date, self.venue, to_run)
        exchange, status = self._betfair_prices(now)
        with self._lock:
            for race in self._card.races:
                if race.number in snaps:
                    apply_market(race, snaps[race.number])
                if race.number in to_run:
                    apply_exchange(race, exchange.get(race.number))
                if race.number in snaps or race.number in exchange:
                    self._models[race.number] = assess(race)
            if status is not None:
                self._bf_status = status
            if exchange:
                self._exchange = exchange
            self._priced_at = now
            self._updated_at = now
        self._record_checks(now)

    def _record_checks(self, now: datetime) -> None:
        """Save each race's picks once 25-35 minutes before its jump, and again at every check
        in the last three minutes (overwriting), at the default amounts."""
        with self._lock:
            if self._card is None:
                return
            races = list(self._card.races)
            models = [self._models[n] for n in sorted(self._models)]
            checks = dict(self._checks)
        early, late = [], []
        for race in races:
            if race.result is not None or race.start_time is None:
                continue
            to_go = race.start_time - now
            had = checks.get(race.number)
            if CHECK_EARLY[0] <= to_go <= CHECK_EARLY[1] and (had is None or had.early is None):
                early.append(race.number)
            elif timedelta(0) <= to_go <= CHECK_LATE:
                late.append(race.number)
        if not early and not late:
            return
        day = build_picks(models, sum(CHECK_AMOUNTS))
        still = {
            r.number for r in races
            if r.result is None and (r.start_time is None or r.start_time > now)
        }
        lines = check_lines(day, allocate_accounts(day, *CHECK_AMOUNTS, races=still))
        with self._lock:
            for race in races:
                n = race.number
                if n not in early and n not in late:
                    continue
                had = self._checks.get(n) or RaceCheck(n, race.start_time)
                saved = lines.get(n, ())
                if n in early:
                    had = replace(had, early=saved, early_at=now, jump=race.start_time)
                else:
                    had = replace(had, late=saved, late_at=now, jump=race.start_time)
                self._checks[n] = had

    def _betfair_prices(self, now: datetime) -> tuple[dict, str | None]:
        """Betfair's prices for the meeting and a status line. A Betfair failure never stops
        the Sportsbet prices: it is reported on the page and tried again next check."""
        if self.bf is None:
            return {}, None
        try:
            found = self.bf.meeting(self.race_date, self.venue)
        except SourceError as exc:
            log.warning("Betfair: %s", exc)
            return {}, f"not available: {exc}"
        except Exception:  # noqa: BLE001 - an unexpected answer must not stop the price check
            log.exception("Betfair prices failed")
            return {}, "not available: unexpected answer from Betfair"
        when = now.astimezone(MELBOURNE).strftime("%-I:%M%p").lower()
        return found, f"prices {when}" if found else f"no {self.venue} markets yet ({when})"

    def load_card_now(self, *, wait: bool = False) -> bool:
        """Load the field and form (and then prices) in the background. False if already busy."""
        if not self.can_fetch or not self._work.acquire(blocking=False):
            return False
        self._loading = True

        def job() -> None:
            try:
                now = self.clock()

                def run() -> None:
                    self._load_form(now)
                    if self._prices_window(now):
                        self._load_prices(now)

                self._guarded(now, run)
            finally:
                self._loading = False
                self._work.release()

        if wait:
            job()
        else:
            threading.Thread(target=job, name="melbcup-load", daemon=True).start()
        return True

    def refresh_prices_now(self) -> bool:
        """One whole-card price check from racing.com. Ignored within MIN_REFRESH_GAP (60 s) of
        the last one."""
        if not self.can_fetch or self._card is None:
            return False
        now = self.clock()
        last = max((t for t in (self._priced_at, self._price_try) if t), default=None)
        if last is not None and now - last < MIN_REFRESH_GAP:
            return False
        if not self._work.acquire(blocking=False):
            return False
        self._price_try = now  # a failed attempt counts too
        try:
            self._guarded(now, lambda: self._load_prices(now))
        finally:
            self._work.release()
        return True

    def fetch_results_now(self) -> bool:
        """Settled results for the meeting from racing.com. Ignored within RESULTS_GAP (60 s)
        of the last fetch."""
        if not self.can_fetch or self._card is None:
            return False
        now = self.clock()
        last = max((t for t in (self._results_at, self._results_try) if t), default=None)
        if last is not None and now - last < MIN_REFRESH_GAP:
            return False
        if not self._work.acquire(blocking=False):
            return False
        self._results_try = now
        try:

            def run() -> None:
                self._load_results(now)

            self._guarded(now, run)
        finally:
            self._work.release()
        return True

    def _load_results(self, now: datetime) -> None:
        results = self.rc.results(self.race_date, self.venue, [r.number for r in self._card.races])
        with self._lock:
            for race in self._card.races:
                if race.number in results:
                    apply_result(race, results[race.number])
                    self._models[race.number] = assess(race)
                check = self._checks.get(race.number)
                if check is not None and race.result is not None and race.result.finish:
                    self._checks[race.number] = grade_check(check, race)
            self._results_at = now
            self._updated_at = now
            day = build_picks([self._models[n] for n in sorted(self._models)])
            self._history = history.merge(self._history, history.entries(day))

    def history(self) -> list[dict]:
        with self._lock:
            return list(self._history)

    def _results_due(self, now: datetime) -> bool:
        """A race jumped three minutes ago and has no result yet, or some placings are still
        interim: check again, at most every two minutes, until every placing is final. One
        call returns every race's result."""
        if self._card is None or self.race_date > self._melbourne_day(now):
            return False
        last = max((t for t in (self._results_at, self._results_try) if t), default=None)
        if last is not None and now - last < RESULTS_EVERY:
            return False
        past_day = self.race_date < self._melbourne_day(now)

        def wanted(race: Race) -> bool:
            if race.result is not None and race.result.status == "final":
                return False
            start = race.start_time
            if start is None:
                return past_day and self._results_at is None
            if now - start < RESULTS_AFTER:
                return False
            # a race that never settles (abandoned, say) is dropped once a check made two hours
            # after its jump has come back without a final placing
            return self._results_at is None or self._results_at - start < RESULTS_GIVE_UP

        return any(wanted(r) for r in self._card.races)

    def set_auto(self, on: bool) -> None:
        self.auto = on

    def set_meeting(self, race_date: date, venue: str) -> bool:
        """Switch to another meeting. The old card is dropped; nothing is fetched until Load."""
        venue = venue.strip()
        if not venue or self._loading:
            return False
        with self._work, self._lock:
            if (race_date, venue.lower()) == (self.race_date, self.venue.lower()):
                return True
            self.race_date, self.venue = race_date, venue
            self._card, self._models, self._checks = None, {}, {}
            self._form_at = self._priced_at = self._updated_at = self._results_at = None
            self._price_try = self._results_try = None
            self._errors = []
        return True

    def find_meetings(self, race_date: date) -> list[str]:
        """The day's meetings from racing.com (then cached for the day)."""
        if self.archive is not None and self.archive.venues(race_date):
            return self.archive.venues(race_date)  # saved earlier: nothing to fetch
        if not self.can_fetch:
            return []
        if race_date not in self._meetings:
            try:
                found = self.rc.meetings(race_date, self._melbourne_day(self.clock()))
            except SourceError as exc:
                log.warning("meetings lookup failed (%s): %s", exc.kind, exc)
                with self._lock:
                    self._errors = [str(exc)]
                return []
            with self._lock:
                self._meetings[race_date] = found
        return self._meetings[race_date]

    # -- automatic mode -----------------------------------------------------------------------

    def tick(self) -> None:
        """Auto mode: load the card if there is none, keep race-day form fresh, price the meeting
        on schedule, and collect results as races are run."""
        if not self.can_fetch or not self.auto:
            return
        now = self.clock()
        if self._paused_until and now < self._paused_until:
            return
        if not self._work.acquire(blocking=False):
            return
        try:

            def run() -> None:
                if self._card is None:  # loaded once; scratchings arrive with the prices
                    if self.field_due(now) is not None:
                        return  # too early: nothing to fetch yet, and no error to show
                    self._load_form(now)
                if self._prices_window(now) and self._prices_due(now):
                    self._price_try = now  # a failed attempt counts too
                    self._load_prices(now)
                if self._results_due(now):
                    self._results_try = now
                    self._load_results(now)

            self._guarded(now, run)
        finally:
            self._work.release()

    def _prices_due(self, now: datetime) -> bool:
        """The first check always runs (it also corrects start times); after that, once a
        minute while any race has yet to jump (a jumped race is waiting on its result)."""
        last = max((t for t in (self._priced_at, self._price_try) if t), default=None)
        if last is None:
            return True
        if now - last < PRICES_EVERY:
            return False
        return any(
            r.result is None and (r.start_time is None or r.start_time > now)
            for r in self._card.races
        )

    @property
    def can_fetch(self) -> bool:
        """racing.com (free, no key) is the one live source."""
        return self.rc is not None

    def _carry_prices(self, card: Card) -> None:
        """A form reload must not wipe the prices or results already fetched."""
        if self._card is None:
            return
        for race in card.races:
            old = self._card.race(race.number)
            if old is not None and old.result is not None:
                apply_result(race, old.result)
            if old is not None and old.prices and not race.prices:
                race.prices, race.places_paid = old.prices, old.places_paid
                race.prices_at = old.prices_at
                race.start_time = old.start_time or race.start_time
                for r in race.runners:
                    o = old.runner(r.number)
                    r.scratched = r.scratched or bool(o and o.scratched)

    # -- background thread --------------------------------------------------------------------

    def start(self, every_seconds: float = 15.0) -> None:
        if not self.can_fetch or self._thread is not None:
            return

        def loop() -> None:
            while not self._stop.is_set():
                try:
                    self.tick()
                except Exception:  # keep serving the last good board whatever happens
                    log.exception("refresh failed")
                self._stop.wait(every_seconds)

        self._thread = threading.Thread(target=loop, name="melbcup-live", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
