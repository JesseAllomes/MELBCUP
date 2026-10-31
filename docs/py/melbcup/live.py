"""Keeps the card, models and picks fresh from racing.com (free), without hammering it.

Manual mode does nothing on its own: the page's buttons load the card, refresh prices and fetch
results. A manual price or results refresh is refused within MIN_REFRESH_GAP (60 s) of the last
one, so a public page cannot be used to hammer racing.com; racing.com replies are cached for
the same time.

Auto mode (the phone's default) does the same on a fixed plan:
    the card       once, when the meeting is opened (scratchings arrive with the prices)
    prices         60, 30, 15, 5 and 2 minutes before each race; checks that fall in the
                   same minute are shared, and only meetings whose field is out are priced
    results        ten minutes after each race, plus one late sweep for interim placings

Prices are racing.com's fixed odds from Sportsbet, Ladbrokes, PointsBet and bet365; the
Sportsbet price drives the Sportsbet-only multis and the price verdicts. FormFav is optional
enrichment.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

from melbcup import history
from melbcup.bets import DayPicks, build_picks
from melbcup.config import MELBOURNE, Settings
from melbcup.domain import Card, Race
from melbcup.model.probability import RaceModel, assess
from melbcup.sources import apply_market, apply_result, load_card
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
RESULTS_AFTER = timedelta(minutes=10)  # results usually settle within ten minutes of the jump
RESULTS_EVERY = timedelta(minutes=10)
FINAL_AFTER = timedelta(minutes=40)  # placings turn "final" after thirty stable minutes


PRICE_CHECKS = (60, 30, 15, 5, 2)  # minutes before each jump


def price_check_times(races: list[Race]) -> list[datetime]:
    """When Auto checks prices: at each race's checkpoints. One call prices the whole card,
    so checkpoints from different races that fall in the same minute share a call."""
    times = {
        (race.start_time - timedelta(minutes=m)).replace(second=0, microsecond=0)
        for race in races
        if race.start_time is not None
        for m in PRICE_CHECKS
    }
    return sorted(times)


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

    def picks(self, budget: float | None) -> DayPicks:
        return build_picks(self.models, budget)


class LiveBoard:
    def __init__(
        self,
        settings: Settings,
        ff: FormFavClient | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        archive: Archive | None = None,
        rc: RacingComClient | None = None,
    ):
        self.settings = settings
        self.rc = rc  # racing.com: field, prices, results; the app's entry points supply it
        self.ff = ff or (
            FormFavClient(settings.formfav_api_key) if settings.formfav_api_key else None
        )
        self.clock = clock
        self.archive = archive
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
            )

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
        with self._lock:
            for race in self._card.races:
                if race.number in snaps:
                    apply_market(race, snaps[race.number])
                    self._models[race.number] = assess(race)
            self._priced_at = now
            self._updated_at = now

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
        """Settled results for the meeting from racing.com. Ignored within MIN_REFRESH_GAP (60 s)
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
            self._results_at = now
            self._updated_at = now
            day = build_picks([self._models[n] for n in sorted(self._models)])
            self._history = history.merge(self._history, history.entries(day))

    def history(self) -> list[dict]:
        with self._lock:
            return list(self._history)

    def _results_due(self, now: datetime) -> bool:
        """A race jumped ten minutes ago and has no result yet; or every race is in but some
        only as interim placings, and the last race jumped over forty minutes ago (one final
        sweep). One call returns every race's result."""
        if self._card is None or self.race_date > self._melbourne_day(now):
            return False
        if self._results_at is not None and now - self._results_at < RESULTS_EVERY:
            return False
        past_day = self.race_date < self._melbourne_day(now)

        def jumped(race: Race, after: timedelta) -> bool:
            return past_day or (race.start_time is not None and now - race.start_time >= after)

        races = self._card.races
        if any(r.result is None and jumped(r, RESULTS_AFTER) for r in races):
            return True
        interim = [r for r in races if r.result is not None and r.result.status != "final"]
        last_sweep_done = self._results_at is not None and all(
            r.start_time is not None and self._results_at - r.start_time >= FINAL_AFTER
            for r in races
        )
        return bool(interim) and all(jumped(r, FINAL_AFTER) for r in races) and not last_sweep_done

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
            self._card, self._models = None, {}
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
                    self._load_prices(now)
                if self._results_due(now):
                    self._load_results(now)

            self._guarded(now, run)
        finally:
            self._work.release()

    def _prices_due(self, now: datetime) -> bool:
        """The first check always runs (it also corrects start times); after that, whenever a
        checkpoint has passed since the last check."""
        if self._priced_at is None:
            return True
        return any(self._priced_at < t <= now for t in price_check_times(self._card.races))

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
