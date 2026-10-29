"""Per-runner handicapping factors, each a raw number where higher means better.

A factor the data cannot support is left out (None), never guessed. Weights live here beside
the factors they apply to; they are priors, not fitted values, and are tuned in m7.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from melbcup.domain import PastRun, Race, Runner, StatLine


@dataclass(frozen=True)
class Factor:
    key: str
    label: str
    weight: float
    fn: Callable[[Runner, Race], float | None]


RECENCY = (1.0, 0.85, 0.7, 0.6, 0.5, 0.4)
ASSUMED_FIELD = 12


def _run_score(run: PastRun) -> float | None:
    if run.position is None:
        return None
    field = run.field_size or ASSUMED_FIELD
    pos = 1.0 - (min(run.position, field) - 1) / max(field - 1, 1)
    if run.margin_l is None:
        return pos
    return 0.5 * pos + 0.5 * math.exp(-run.margin_l / 4.0)


def _figures(last10: str | None) -> list[int]:
    """``x41`` -> [1, 4] newest first; ``0`` is tenth or worse; spells (``x``) skipped."""
    if not last10:
        return []
    return [10 if c == "0" else int(c) for c in reversed(last10) if c.isdigit()]


def recent_form(r: Runner, race: Race) -> float | None:
    scores = [s for s in map(_run_score, r.runs[: len(RECENCY)]) if s is not None]
    if not scores:
        figs = _figures(r.last10)[: len(RECENCY)]
        scores = [1.0 - (min(f, ASSUMED_FIELD) - 1) / (ASSUMED_FIELD - 1) for f in figs]
    if not scores:
        return None
    w = RECENCY[: len(scores)]
    return sum(a * b for a, b in zip(scores, w, strict=True)) / sum(w)


def _shrunk(stat: StatLine | None, base: float, k: float, *, place: bool = False) -> float | None:
    if stat is None or stat.starts == 0:
        return None
    hits = stat.top3 if place else stat.wins
    return (hits + k * base) / (stat.starts + k)


def _field(race: Race) -> int:
    return max(len(race.starters), 2)


def _stat_factor(
    attr: str, *, place: bool, k: float = 4.0
) -> Callable[[Runner, Race], float | None]:
    def fn(r: Runner, race: Race) -> float | None:
        n = _field(race)
        base = min(race.places_paid, n) / n if place else 1.0 / n
        return _shrunk(getattr(r, attr), base, k, place=place)

    return fn


def runs_since_spell(r: Runner) -> int | None:
    """0 = first-up, 1 = second-up. From the form figures: the digits after the last ``x``."""
    if not r.last10 or "x" not in r.last10.lower():
        return None
    return len([c for c in r.last10.lower().rsplit("x", 1)[1] if c.isdigit()])


def spell_record(r: Runner, race: Race) -> float | None:
    n = runs_since_spell(r)
    stat = r.first_up if n == 0 else r.second_up if n == 1 else None
    return _shrunk(stat, min(race.places_paid, _field(race)) / _field(race), 3.0, place=True)


def _relative(values: dict[int, float], number: int) -> float | None:
    if number not in values or len(values) < 2:
        return None
    mean = sum(values.values()) / len(values)
    return values[number] - mean


def handicap_rating(r: Runner, race: Race) -> float | None:
    return _relative({x.number: x.hcp_rating for x in race.starters if x.hcp_rating}, r.number)


def class_rating(r: Runner, race: Race) -> float | None:
    ratings = {x.number: x.class_rating for x in race.starters if x.class_rating is not None}
    rel = _relative(ratings, r.number)
    if rel is None and r.class_difference is not None:
        return -float(r.class_difference)
    return rel


def weight_relief(r: Runner, race: Race) -> float | None:
    """Kilos under the field average (allowing the apprentice claim)."""

    def eff(x: Runner) -> float | None:
        return None if x.weight_kg is None else x.weight_kg - (x.claim_kg or 0.0)

    weights = {x.number: w for x in race.starters if (w := eff(x)) is not None}
    rel = _relative(weights, r.number)
    return None if rel is None else -rel


def _person(attr: str, scope: str, base: float, k: float) -> Callable[[Runner, Race], float | None]:
    def fn(r: Runner, race: Race) -> float | None:
        stats = getattr(r, attr)
        return _shrunk(getattr(stats, scope), base, k) if stats else None

    return fn


def barrier_bias(r: Runner, race: Race) -> float | None:
    if r.barrier is None or not race.barrier_advantage:
        return None
    return race.barrier_advantage.get(r.barrier)


def track_position(r: Runner, race: Race) -> float | None:
    """Settling closer to the lead is worth more in sprints than in staying races."""
    if r.settling_position is None:
        return None
    scale = 1.0 if (race.distance_m or 1600) <= 1600 else 0.4
    return -r.settling_position * scale


def freshness(r: Runner, race: Race) -> float | None:
    last = r.last_start_date or (r.runs[0].run_date if r.runs else None)
    if last is None:
        return None
    days = (race.race_date - last).days if isinstance(race.race_date, date) else None
    if days is None or days < 0:
        return None
    if 10 <= days <= 35:
        return 1.0
    if days < 10:
        return 0.5
    return max(0.0, 1.0 - (days - 35) / 120.0)


FACTORS: tuple[Factor, ...] = (
    Factor("form", "Recent form", 0.35, recent_form),
    Factor("career_win", "Career strike rate", 0.12, _stat_factor("career", place=False, k=6)),
    Factor("career_place", "Career place rate", 0.08, _stat_factor("career", place=True, k=6)),
    Factor("track", "Track record", 0.05, _stat_factor("track", place=True)),
    Factor("distance", "Distance record", 0.08, _stat_factor("distance", place=True)),
    Factor("track_distance", "Track + distance", 0.04, _stat_factor("track_distance", place=True)),
    Factor("going", "Going record", 0.06, _stat_factor("going", place=True)),
    Factor("spell", "First/second-up record", 0.04, spell_record),
    Factor("hcp", "Handicap rating", 0.22, handicap_rating),
    Factor("class", "Class rating", 0.15, class_rating),
    Factor("weight", "Weight relief", 0.06, weight_relief),
    Factor("jockey", "Jockey form", 0.10, _person("jockey_stats", "recent", 0.1, 30)),
    Factor("jockey_track", "Jockey at track", 0.05, _person("jockey_stats", "at_track", 0.1, 30)),
    Factor("trainer", "Trainer form", 0.08, _person("trainer_stats", "recent", 0.1, 30)),
    Factor(
        "trainer_track", "Trainer at track", 0.04, _person("trainer_stats", "at_track", 0.1, 30)
    ),
    Factor("barrier", "Barrier bias", 0.06, barrier_bias),
    Factor("map", "Speed map position", 0.04, track_position),
    Factor("fresh", "Freshness", 0.03, freshness),
)


def raw_factors(race: Race) -> dict[int, dict[str, float]]:
    """Runner number -> factor key -> raw value, starters only, missing factors omitted."""
    out: dict[int, dict[str, float]] = {}
    for r in race.starters:
        vals = {}
        for f in FACTORS:
            v = f.fn(r, race)
            if v is not None and math.isfinite(v):
                vals[f.key] = float(v)
        out[r.number] = vals
    return out
