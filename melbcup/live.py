"""Keeps the card, models and picks fresh, spending PuntersEdge credits only when asked.

Manual mode (the default) spends nothing on its own: the page's buttons load the card
(about 2 + 3 per race credits) and refresh prices (2 credits for the whole card).

Auto mode loads the card, reloads form hourly, and prices the whole card at the tightest
interval any race still to run needs:

    more than 90 min to go   every 15 min
    20-90 min to go          every 5 min
    under 20 min             every POLL_SECONDS (default 60 s)
    jumped 5+ min ago        no longer counts
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from melbcup.bets import DayPicks, build_picks
from melbcup.config import Settings
from melbcup.domain import Card, Race
from melbcup.model.probability import RaceModel, assess
from melbcup.sources import apply_market, load_card
from melbcup.sources.formfav import FormFavClient
from melbcup.sources.http import SourceError
from melbcup.sources.puntersedge import PuntersEdgeClient

log = logging.getLogger("melbcup.live")

FORM_REFRESH = timedelta(hours=1)
QUOTA_BACKOFF = timedelta(minutes=15)
MIN_MANUAL_GAP = timedelta(seconds=15)  # a double tap must not spend twice


def price_interval(race: Race, now: datetime, poll_seconds: int) -> timedelta | None:
    """How often to poll this race's prices now; None once it has run."""
    if race.start_time is None:
        return timedelta(minutes=15)
    to_go = race.start_time - now
    if to_go < timedelta(minutes=-5):
        return None
    if to_go <= timedelta(minutes=20):
        return timedelta(seconds=poll_seconds)
    if to_go <= timedelta(minutes=90):
        return timedelta(minutes=5)
    return timedelta(minutes=15)


@dataclass
class Snapshot:
    card: Card | None
    models: list[RaceModel]
    updated_at: datetime | None
    errors: list[str] = field(default_factory=list)
    credits_remaining: int | None = None
    credits_limit: int | None = None
    auto: bool = False
    loading: bool = False
    priced_at: datetime | None = None
    form_at: datetime | None = None
    race_date: date | None = None
    venue: str = ""
    meetings: dict[date, list[str]] = field(default_factory=dict)

    def picks(self, budget: float | None) -> DayPicks:
        return build_picks(self.models, budget)


class LiveBoard:
    def __init__(
        self,
        settings: Settings,
        pe: PuntersEdgeClient | None = None,
        ff: FormFavClient | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.settings = settings
        self.pe = pe or (
            PuntersEdgeClient(settings.puntersedge_api_key)
            if settings.puntersedge_api_key
            else None
        )
        self.ff = ff or (
            FormFavClient(settings.formfav_api_key) if settings.formfav_api_key else None
        )
        self.clock = clock
        self.auto = settings.auto_refresh
        self.race_date = settings.race_date
        self.venue = settings.venue
        self._meetings: dict[date, list[str]] = {}
        self._lock = threading.Lock()
        self._work = threading.Lock()  # one load or refresh at a time
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._loading = False
        self._card: Card | None = None
        self._models: dict[int, RaceModel] = {}
        self._form_at: datetime | None = None
        self._priced_at: datetime | None = None
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
                credits_remaining=self.pe.credits_remaining if self.pe else None,
                credits_limit=self.pe.credits_limit if self.pe else None,
                auto=self.auto,
                loading=self._loading,
                priced_at=self._priced_at,
                form_at=self._form_at,
                race_date=self.race_date,
                venue=self.venue,
                meetings=dict(self._meetings),
            )

    # -- actions ------------------------------------------------------------------------------

    def _guarded(self, now: datetime, fn: Callable[[], None]) -> None:
        """Run one load/refresh, recording errors and pausing after quota or auth trouble."""
        errors: list[str] = []
        try:
            fn()
        except SourceError as exc:
            errors.append(str(exc))
            if exc.kind in ("quota", "rate_limit", "auth"):
                self._paused_until = now + QUOTA_BACKOFF
                errors.append(f"Paused automatic PuntersEdge calls for 15 minutes ({exc.kind}).")
        with self._lock:
            self._errors = errors

    def _load_form(self, now: datetime) -> None:
        card = load_card(self.pe, self.ff, self.race_date, self.venue)
        with self._lock:
            self._carry_prices(card)
            self._card = card
            self._form_at = now
            self._models = {r.number: assess(r) for r in card.races}
            self._updated_at = now

    def _load_prices(self, now: datetime) -> None:
        snaps = self.pe.card_prices(self.race_date, self.venue)
        with self._lock:
            for race in self._card.races:
                if race.number in snaps:
                    apply_market(race, snaps[race.number])
                    self._models[race.number] = assess(race)
            self._priced_at = now
            self._updated_at = now

    def load_card_now(self, *, wait: bool = False) -> bool:
        """Load the field and form (and then prices) in the background. False if already busy."""
        if self.pe is None or not self._work.acquire(blocking=False):
            return False
        self._loading = True

        def job() -> None:
            try:
                now = self.clock()
                self._guarded(now, lambda: (self._load_form(now), self._load_prices(now)))
            finally:
                self._loading = False
                self._work.release()

        if wait:
            job()
        else:
            threading.Thread(target=job, name="melbcup-load", daemon=True).start()
        return True

    def refresh_prices_now(self) -> bool:
        """One whole-card price call (2 credits). Ignored within 15 s of the last one."""
        if self.pe is None or self._card is None:
            return False
        now = self.clock()
        if self._priced_at is not None and now - self._priced_at < MIN_MANUAL_GAP:
            return False
        if not self._work.acquire(blocking=False):
            return False
        try:
            self._guarded(now, lambda: self._load_prices(now))
        finally:
            self._work.release()
        return True

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
            self._form_at = self._priced_at = self._updated_at = None
            self._errors = []
        return True

    def find_meetings(self, race_date: date) -> list[str]:
        """The day's meetings (2 credits, then cached for this day)."""
        if self.pe is None:
            return []
        if race_date not in self._meetings:
            try:
                found = self.pe.meetings(race_date)
            except SourceError as exc:
                with self._lock:
                    self._errors = [str(exc)]
                return []
            with self._lock:
                self._meetings[race_date] = found
        return self._meetings[race_date]

    def check_credits(self) -> None:
        """Read the balance once (free) so the page can show it before anything is spent."""
        if self.pe is None:
            return
        try:
            self.pe.read_credits()
        except SourceError as exc:
            log.warning("could not read PuntersEdge credits: %s", exc)

    # -- automatic mode -----------------------------------------------------------------------

    def tick(self) -> None:
        """Auto mode only: load form if missing or an hour old, then prices if due."""
        if self.pe is None or not self.auto:
            return
        now = self.clock()
        if self._paused_until and now < self._paused_until:
            return
        if not self._work.acquire(blocking=False):
            return
        try:

            def run() -> None:
                if (
                    self._card is None
                    or self._form_at is None
                    or now - self._form_at >= FORM_REFRESH
                ):
                    self._load_form(now)
                if self._prices_due(now):
                    self._load_prices(now)

            self._guarded(now, run)
        finally:
            self._work.release()

    def _prices_due(self, now: datetime) -> bool:
        """One call prices the whole card, so poll at the tightest interval any race needs.
        The first poll always runs: it also corrects start times."""
        if self._priced_at is None:
            return True
        intervals = [
            i
            for race in self._card.races
            if (i := price_interval(race, now, self.settings.poll_seconds)) is not None
        ]
        if not intervals:
            return False
        return now - self._priced_at >= min(intervals)

    def _carry_prices(self, card: Card) -> None:
        """A form reload must not wipe the prices already fetched."""
        if self._card is None:
            return
        for race in card.races:
            old = self._card.race(race.number)
            if old is not None and old.prices:
                race.prices, race.places_paid = old.prices, old.places_paid
                race.prices_at = old.prices_at
                race.start_time = old.start_time or race.start_time
                for r in race.runners:
                    o = old.runner(r.number)
                    r.scratched = r.scratched or bool(o and o.scratched)

    # -- background thread --------------------------------------------------------------------

    def start(self, every_seconds: float = 15.0) -> None:
        if self.pe is None or self._thread is not None:
            return

        def loop() -> None:
            self.check_credits()
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
