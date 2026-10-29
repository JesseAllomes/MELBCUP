"""Keeps the card, models and picks fresh in the background.

Form changes slowly and is reloaded hourly. One PuntersEdge call (2 credits) prices the whole
card; it is made at the tightest interval any race still to run needs:

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
from datetime import UTC, datetime, timedelta

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
    credits_used: int = 0

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
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
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
                credits_used=self.pe.src.calls if self.pe else 0,
            )

    # -- one refresh pass ---------------------------------------------------------------------

    def tick(self) -> None:
        """One pass: reload form if due, then poll whichever races' prices are due."""
        if self.pe is None:
            return
        now = self.clock()
        if self._paused_until and now < self._paused_until:
            return
        errors: list[str] = []
        try:
            if self._card is None or self._form_at is None or now - self._form_at >= FORM_REFRESH:
                card = load_card(self.pe, self.ff, self.settings.race_date, self.settings.venue)
                with self._lock:
                    self._carry_prices(card)
                    self._card = card
                    self._form_at = now
                    self._models = {r.number: assess(r) for r in card.races}
                    self._updated_at = now
            due = self._prices_due(now)
            if due:
                snaps = self.pe.card_prices(self.settings.race_date, self.settings.venue)
                with self._lock:
                    for race in self._card.races:
                        if race.number in snaps:
                            apply_market(race, snaps[race.number])
                            self._models[race.number] = assess(race)
                    self._priced_at = now
                    self._updated_at = now
        except SourceError as exc:
            errors.append(str(exc))
            if exc.kind in ("quota", "rate_limit", "auth"):
                self._paused_until = now + QUOTA_BACKOFF
                errors.append(f"Paused PuntersEdge polling for 15 minutes ({exc.kind}).")
        with self._lock:
            self._errors = errors

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
                for r in race.runners:
                    o = old.runner(r.number)
                    r.scratched = r.scratched or bool(o and o.scratched)

    # -- background thread --------------------------------------------------------------------

    def start(self, every_seconds: float = 15.0) -> None:
        if self.pe is None or self._thread is not None:
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
