"""Normalised racing data. Every source maps into these types; nothing downstream sees raw JSON."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True)
class StatLine:
    """A starts/wins/top-three record. ``top3`` includes wins."""

    starts: int
    wins: int
    top3: int

    @property
    def win_rate(self) -> float | None:
        return self.wins / self.starts if self.starts else None

    @property
    def place_rate(self) -> float | None:
        return self.top3 / self.starts if self.starts else None


@dataclass(frozen=True)
class PersonStats:
    """Jockey or trainer record: overall, at today's track, and over a recent window."""

    name: str
    overall: StatLine | None = None
    at_track: StatLine | None = None
    recent: StatLine | None = None
    by_going: dict[str, StatLine] | None = None  # career record on each going band

    def on_going(self, condition: str | None) -> StatLine | None:
        band = going_band(condition)
        return (self.by_going or {}).get(band) if band else None


@dataclass(frozen=True)
class PastRun:
    run_date: date
    venue: str
    distance_m: int | None
    condition: str | None
    position: int | None
    field_size: int | None
    margin_l: float | None
    sp: float | None
    weight_kg: float | None
    jockey: str | None
    race_class: str | None


@dataclass(frozen=True)
class RunNote:
    """One past run as racing.com records it, with the stewards' comment if there was one."""

    run_date: date
    venue: str
    distance_m: int | None
    condition: str | None
    finish: int | None
    settled: int | None
    stewards: str | None


@dataclass
class Runner:
    number: int
    name: str
    barrier: int | None = None
    jockey: str | None = None
    trainer: str | None = None
    owner: str | None = None
    weight_kg: float | None = None
    claim_kg: float | None = None
    scratched: bool = False
    emergency: bool = False
    age: int | None = None
    sex: str | None = None
    sire: str | None = None
    dam: str | None = None
    gear_changes: str | None = None
    last10: str | None = None
    hcp_rating: int | None = None
    last_start_date: date | None = None
    last_start_position: int | None = None
    last_start_weight_kg: float | None = None
    last_start_rating: int | None = None
    runs: list[PastRun] = field(default_factory=list)
    career: StatLine | None = None
    track: StatLine | None = None
    distance: StatLine | None = None
    track_distance: StatLine | None = None
    going: StatLine | None = None  # record on today's going band
    going_records: dict[str, StatLine] | None = None  # record on every band, from FormFav
    first_up: StatLine | None = None
    second_up: StatLine | None = None
    running_style: str | None = None
    early_speed: float | None = None
    settling_position: float | None = None
    class_rating: int | None = None
    class_difference: int | None = None
    within_class_range: bool | None = None
    feed_win_prob: float | None = None
    feed_place_prob: float | None = None
    jockey_stats: PersonStats | None = None
    trainer_stats: PersonStats | None = None
    notes: list[str] = field(default_factory=list)
    run_notes: list[RunNote] | None = None  # racing.com, newest first, before this race

    @property
    def last_start_note(self) -> str | None:
        return self.run_notes[0].stewards if self.run_notes else None


@dataclass(frozen=True)
class Quote:
    price: float
    bookmaker: str


@dataclass
class RunnerPrices:
    number: int
    best_win: Quote | None = None
    best_place: Quote | None = None
    sportsbet_win: float | None = None
    sportsbet_place: float | None = None
    consensus_prob: float | None = None
    books: int = 0


@dataclass
class RaceResult:
    """Official result: finishing positions, starting prices and $1 dividends."""

    status: str  # "final" | "interim"
    finish: dict[int, int]  # runner number -> position, starters only
    sp: dict[int, float]
    names: dict[int, str]
    place_dividend: dict[int, float] = field(default_factory=dict)  # fixed place, per $1
    exotics: dict[str, tuple[tuple[int, ...], float]] = field(default_factory=dict)  # TF/FF/...

    def placegetters(self, n: int = 4) -> list[int]:
        return [num for num, pos in sorted(self.finish.items(), key=lambda kv: kv[1]) if pos <= n]


@dataclass
class Race:
    venue: str
    race_date: date
    number: int
    name: str | None = None
    race_id: str | None = None
    distance_m: int | None = None
    condition: str | None = None
    condition_was: str | None = None  # the condition at card load, once the feed has changed it
    weather: str | None = None
    race_class: str | None = None
    prize_total: int | None = None
    start_time: datetime | None = None
    places_paid: int = 3
    runners: list[Runner] = field(default_factory=list)
    prices: dict[int, RunnerPrices] = field(default_factory=dict)
    barrier_advantage: dict[int, float] = field(default_factory=dict)
    prices_at: datetime | None = None
    result: RaceResult | None = None
    priced_from_sp: bool = False

    def runner(self, number: int) -> Runner | None:
        return next((r for r in self.runners if r.number == number), None)

    @property
    def starters(self) -> list[Runner]:
        return [r for r in self.runners if not r.scratched and not r.emergency]


@dataclass
class Card:
    venue: str
    race_date: date
    races: list[Race] = field(default_factory=list)
    rail: str | None = None
    condition: str | None = None
    warnings: list[str] = field(default_factory=list)

    def race(self, number: int) -> Race | None:
        return next((r for r in self.races if r.number == number), None)


_SHORT_MARGINS = {"NS": 0.05, "NOSE": 0.05, "SHD": 0.1, "SH": 0.1, "HD": 0.2, "HH": 0.3}
_SHORT_MARGINS |= {"NK": 0.3, "1/2NK": 0.25, "LNK": 0.4, "DH": 0.0}
_LENGTHS = re.compile(r"^(\d+(?:\.\d+)?)\s*L?$")


def parse_margin(text: str | None) -> float | None:
    """Lengths behind the winner from strings like ``1.8L``, ``HD`` or ``NK``."""
    if not text:
        return None
    t = text.strip().upper()
    if t in _SHORT_MARGINS:
        return _SHORT_MARGINS[t]
    m = _LENGTHS.match(t)
    return float(m.group(1)) if m else None


_GOING = re.compile(r"(firm|good|soft|heavy|synthetic)", re.IGNORECASE)
_RATING = re.compile(r"(\d+)")


def going_band(condition: str | None) -> str | None:
    """``Soft (6)`` -> ``soft``. Unknown text -> None."""
    if not condition:
        return None
    m = _GOING.search(condition)
    return m.group(1).lower() if m else None


def same_going(a: str | None, b: str | None) -> bool:
    """``Good 4`` and ``Good4`` are the same going; ``Soft 6`` is not."""
    return (going_band(a), going_rating(a)) == (going_band(b), going_rating(b))


def going_rating(condition: str | None) -> int | None:
    """``Soft (6)`` or ``Soft 6`` -> 6."""
    if not condition:
        return None
    m = _RATING.search(condition)
    return int(m.group(1)) if m else None


def parse_distance(text: str | int | None) -> int | None:
    """``3200m`` / ``3200`` -> 3200."""
    if text is None:
        return None
    if isinstance(text, int):
        return text
    m = _RATING.search(text.replace(",", ""))
    return int(m.group(1)) if m else None
