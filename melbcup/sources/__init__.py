"""Assemble one race card from both feeds.

PuntersEdge is required: it supplies the field (acceptances, owners, scratchings) and the prices.
FormFav is enrichment: every FormFav call may fail (tier, quota, outage) and the card is still
built, with a warning naming what is missing.

Calls run on a small thread pool: a full card is about 120 requests, which one at a time took
close to three minutes.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from melbcup.domain import Card, PersonStats, Race
from melbcup.sources.formfav import FormFavClient, FormFavRunner
from melbcup.sources.http import SourceError
from melbcup.sources.puntersedge import MarketSnapshot, PuntersEdgeClient

WORKERS = 8
_warn_lock = threading.Lock()


def _try[T](card: Card, what: str, fn: Callable[[], T]) -> T | None:
    try:
        return fn()
    except SourceError as exc:
        msg = f"{what} unavailable ({exc.kind})"
        with _warn_lock:
            if msg not in card.warnings:
                card.warnings.append(msg)
        return None


def load_card(pe: PuntersEdgeClient, ff: FormFavClient | None, race_date: date, venue: str) -> Card:
    card = pe.acceptances(race_date, venue)
    with ThreadPoolExecutor(WORKERS) as pool:
        forms = pool.map(
            lambda r: _try(
                card, "Recent form (PuntersEdge)", lambda: pe.field_form(race_date, venue, r.number)
            ),
            card.races,
        )
        for race, form in zip(card.races, forms, strict=True):
            for runner in race.runners:
                if form and runner.number in form:
                    runner.runs, record = form[runner.number]
                    runner.career = runner.career or record
        if ff is None:
            card.warnings.append(
                "FormFav key not set: career splits, speed maps and ratings missing"
            )
        else:
            enrich_from_formfav(card, ff, pool)
    return card


def _apply_ff_form(race: Race, ff_form: list[FormFavRunner] | None) -> None:
    by_number = {r.number: r for r in ff_form or []}
    for runner in race.runners:
        f = by_number.get(runner.number)
        if f is None:
            continue
        runner.scratched = runner.scratched or f.scratched
        runner.career = f.career or runner.career
        runner.track, runner.distance = f.track, f.distance
        runner.track_distance, runner.going = f.track_distance, f.going
        runner.first_up, runner.second_up = f.first_up, f.second_up
        runner.running_style, runner.early_speed = f.running_style, f.early_speed
        runner.settling_position = f.settling_position
        runner.class_rating, runner.class_difference = f.class_rating, f.class_difference
        runner.within_class_range = f.within_class_range
        runner.notes = f.notes
        if f.last20 and not runner.last10:
            runner.last10 = f.last20[-10:]


def enrich_from_formfav(card: Card, ff: FormFavClient, pool: ThreadPoolExecutor) -> None:
    venue, race_date, races = card.venue, card.race_date, card.races

    ff_forms = pool.map(
        lambda r: _try(
            card, "Long-form history (FormFav)", lambda: ff.form(race_date, venue, r.number)
        ),
        races,
    )
    preds = pool.map(
        lambda r: _try(
            card,
            "FormFav predictions (open to Pro the day before the races)",
            lambda: ff.predictions(race_date, venue, r.number),
        ),
        races,
    )
    distances = sorted({r.distance_m for r in races}, key=lambda d: d or 0)
    bias = dict(
        zip(
            distances,
            pool.map(
                lambda d: _try(card, "Track bias (FormFav Pro)", lambda: ff.track_bias(venue, d)),
                distances,
            ),
            strict=True,
        )
    )

    for race, form, pred in zip(races, ff_forms, preds, strict=True):
        _apply_ff_form(race, form)
        for number, (win, place) in (pred or {}).items():
            if (r := race.runner(number)) is not None:
                r.feed_win_prob, r.feed_place_prob = win, place
        race.barrier_advantage = bias.get(race.distance_m) or {}

    wanted = sorted(
        {
            (role, name)
            for race in races
            for r in race.runners
            for role, name in (("jockey", r.jockey), ("trainer", r.trainer))
            if name
        }
    )

    def fetch(key: tuple[str, str]) -> PersonStats | None:
        role, name = key
        getter = ff.jockey if role == "jockey" else ff.trainer
        return _try(card, f"{role.title()} stats (FormFav Pro)", lambda: getter(name, venue))

    people = dict(zip(wanted, pool.map(fetch, wanted), strict=True))
    for race in races:
        for r in race.runners:
            r.jockey_stats = people.get(("jockey", r.jockey)) if r.jockey else None
            r.trainer_stats = people.get(("trainer", r.trainer)) if r.trainer else None


def apply_market(race: Race, snap: MarketSnapshot) -> None:
    race.prices = snap.prices
    race.places_paid = snap.places_paid
    race.prices_at = snap.observed_at or race.prices_at
    # The feed's UTC start beats the acceptance card's local clock time, which is the track's
    # own time zone (a WA meeting would otherwise be three hours out).
    race.start_time = snap.start_time or race.start_time
    for runner in race.runners:
        if runner.number in snap.scratched:
            runner.scratched = True
