"""Assemble one race card from both feeds.

PuntersEdge is required: it supplies the field (acceptances, owners, scratchings) and the prices.
FormFav is enrichment: every FormFav call may fail (tier, quota, outage) and the card is still
built, with a warning naming what is missing.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from melbcup.domain import Card, PersonStats, Race
from melbcup.sources.formfav import FormFavClient
from melbcup.sources.http import SourceError
from melbcup.sources.puntersedge import MarketSnapshot, PuntersEdgeClient


def _try[T](card: Card, what: str, fn: Callable[[], T]) -> T | None:
    try:
        return fn()
    except SourceError as exc:
        msg = f"{what} unavailable ({exc.kind})"
        if msg not in card.warnings:
            card.warnings.append(msg)
        return None


def load_card(pe: PuntersEdgeClient, ff: FormFavClient | None, race_date: date, venue: str) -> Card:
    card = pe.acceptances(race_date, venue)
    people: dict[tuple[str, str], PersonStats | None] = {}
    bias_by_distance: dict[int | None, dict[int, float] | None] = {}

    for race in card.races:
        form = _try(
            card,
            "Recent form (PuntersEdge)",
            lambda r=race: pe.field_form(race_date, venue, r.number),
        )
        for runner in race.runners:
            if form and runner.number in form:
                runner.runs, record = form[runner.number]
                runner.career = runner.career or record
        if ff is None:
            continue
        enrich_from_formfav(card, ff, race, people, bias_by_distance)
    if ff is None:
        card.warnings.append("FormFav key not set: career splits, speed maps and ratings missing")
    return card


def enrich_from_formfav(
    card: Card,
    ff: FormFavClient,
    race: Race,
    people: dict[tuple[str, str], PersonStats | None],
    bias_by_distance: dict[int | None, dict[int, float] | None],
) -> None:
    venue, race_date = race.venue, race.race_date
    ff_form = _try(
        card, "Long-form history (FormFav)", lambda: ff.form(race_date, venue, race.number)
    )
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

    preds = _try(
        card, "FormFav predictions (Pro)", lambda: ff.predictions(race_date, venue, race.number)
    )
    for number, (win, place) in (preds or {}).items():
        r = race.runner(number)
        if r is not None:
            r.feed_win_prob, r.feed_place_prob = win, place

    if race.distance_m not in bias_by_distance:
        bias_by_distance[race.distance_m] = _try(
            card, "Track bias (FormFav Pro)", lambda: ff.track_bias(venue, race.distance_m)
        )
    race.barrier_advantage = bias_by_distance[race.distance_m] or {}

    for runner in race.runners:
        for role, name in (("jockey", runner.jockey), ("trainer", runner.trainer)):
            if not name:
                continue
            key = (role, name)
            if key not in people:
                fetch = ff.jockey if role == "jockey" else ff.trainer
                people[key] = _try(
                    card,
                    f"{role.title()} stats (FormFav Pro)",
                    lambda f=fetch, n=name: f(n, venue),
                )
            if role == "jockey":
                runner.jockey_stats = people[key]
            else:
                runner.trainer_stats = people[key]


def apply_market(race: Race, snap: MarketSnapshot) -> None:
    race.prices = snap.prices
    race.places_paid = snap.places_paid
    race.prices_at = snap.observed_at or race.prices_at
    for runner in race.runners:
        if runner.number in snap.scratched:
            runner.scratched = True
