"""FormFav: long-form career splits, speed map, class profile, model predictions,
jockey/trainer records and track barrier bias.

Predictions, stats and track bias need the Pro tier; on Free they answer 401/403 and the caller
carries on without them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import quote

import httpx

from melbcup.domain import PersonStats, StatLine, going_band
from melbcup.sources.http import JsonSource, SourceError

BASE_URL = "https://api.formfav.com"
STATS_WINDOW_DAYS = 90


def track_slug(venue: str) -> str:
    return "-".join(venue.lower().split())


def _stat(s: dict[str, Any] | None) -> StatLine | None:
    if not s or not s.get("starts"):
        return None
    wins = int(s.get("wins") or 0)
    if s.get("seconds") is not None and s.get("thirds") is not None:
        top3 = wins + int(s["seconds"]) + int(s["thirds"])
    else:
        top3 = int(s.get("places") or 0)  # documented as 1st, 2nd and 3rd
    return StatLine(int(s["starts"]), wins, top3)


def _perf(p: dict[str, Any] | None) -> StatLine | None:
    """TrackPerformance-shaped rows use totalStarts."""
    if not p or not p.get("totalStarts"):
        return None
    return StatLine(int(p["totalStarts"]), int(p.get("wins") or 0), int(p.get("places") or 0))


@dataclass
class FormFavRunner:
    number: int
    name: str
    scratched: bool
    last20: str | None
    career: StatLine | None
    track: StatLine | None
    distance: StatLine | None
    track_distance: StatLine | None
    going: StatLine | None
    first_up: StatLine | None
    second_up: StatLine | None
    running_style: str | None
    early_speed: float | None
    settling_position: float | None
    class_rating: int | None
    class_difference: int | None
    within_class_range: bool | None
    notes: list[str]


def parse_form(data: dict[str, Any]) -> list[FormFavRunner]:
    band = going_band(data.get("condition"))
    out = []
    for r in data.get("runners", []):
        stats = r.get("stats") or {}
        conditions = {str(k).lower(): v for k, v in (stats.get("conditions") or {}).items()}
        speed = r.get("speedMap") or {}
        cls = r.get("classProfile") or {}
        fit = r.get("raceClassFit") or {}
        notes = [
            f"{d.get('label')} ({d.get('sentiment')})"
            for d in r.get("decorators") or []
            if d.get("label")
        ]
        out.append(
            FormFavRunner(
                number=r["number"],
                name=r.get("name") or "",
                scratched=bool(r.get("scratched")),
                last20=r.get("last20Starts") or r.get("form"),
                career=_stat(stats.get("overall")),
                track=_stat(stats.get("track")),
                distance=_stat(stats.get("distance")),
                track_distance=_stat(stats.get("trackDistance")),
                going=_stat(conditions.get(band)) if band else None,
                first_up=_stat(stats.get("firstUp")),
                second_up=_stat(stats.get("secondUp")),
                running_style=speed.get("runningStyle"),
                early_speed=speed.get("earlySpeedIndex"),
                settling_position=speed.get("settlingPosition"),
                class_rating=cls.get("currentRating"),
                class_difference=fit.get("classDifference"),
                within_class_range=fit.get("withinOptimalRange"),
                notes=notes,
            )
        )
    return out


def parse_predictions(data: dict[str, Any]) -> dict[int, tuple[float, float]]:
    return {
        p["number"]: (float(p["winProb"]), float(p["placeProb"]))
        for p in data.get("predictions", [])
        if p.get("winProb") is not None and p.get("placeProb") is not None
    }


def parse_person(data: dict[str, Any], venue: str) -> PersonStats:
    name = data.get("jockeyName") or data.get("trainerName") or ""
    overall = None
    if data.get("totalStarts"):
        starts = int(data["totalStarts"])
        place_rate = float(data.get("overallPlaceRate") or 0)
        overall = StatLine(starts, int(data.get("totalWins") or 0), round(place_rate * starts))
    at_track = next(
        (
            _perf(t)
            for t in data.get("trackStats") or []
            if t.get("venue", "").lower() == venue.lower()
        ),
        None,
    )
    recent = None
    rs = data.get("recentStats") or {}
    if rs.get("totalStarts"):
        starts = int(rs["totalStarts"])
        place_rate = float(rs.get("overallPlaceRate") or 0)
        recent = StatLine(starts, int(rs.get("totalWins") or 0), round(place_rate * starts))
    return PersonStats(name=name, overall=overall, at_track=at_track, recent=recent)


def parse_track_bias(data: dict[str, Any], distance_m: int | None) -> dict[int, float]:
    """Barrier -> win-rate points above (+) or below (-) expectation for this distance band."""
    rows = data.get("barrierStats") or []
    if distance_m is not None:
        for band in data.get("distanceStats") or []:
            lo, hi = band.get("minDistance") or 0, band.get("maxDistance") or 0
            if lo <= distance_m <= hi and band.get("barrierStats"):
                rows = band["barrierStats"]
                break
    return {
        int(b["barrierNumber"]): float(b["advantage"])
        for b in rows
        if b.get("advantage") is not None and (b.get("totalStarts") or 0) >= 20
    }


class FormFavClient:
    def __init__(self, api_key: str, *, transport: httpx.BaseTransport | None = None):
        self.src = JsonSource("FormFav", BASE_URL, api_key, transport=transport)

    def _race_params(self, race_date: date, venue: str, race: int) -> dict[str, Any]:
        return {"date": race_date.isoformat(), "track": track_slug(venue), "race": race}

    def form(self, race_date: date, venue: str, race: int) -> list[FormFavRunner]:
        data = self.src.get("/v1/form", self._race_params(race_date, venue, race), ttl=900)
        return parse_form(data)

    def predictions(self, race_date: date, venue: str, race: int) -> dict[int, tuple[float, float]]:
        data = self.src.get("/v1/predictions", self._race_params(race_date, venue, race), ttl=600)
        return parse_predictions(data)

    def _person(self, role: str, name: str, venue: str) -> PersonStats:
        """Big stables can make FormFav's windowed query fail server-side; fall back to a
        shorter window, then to all-time figures."""
        path = f"/v1/stats/{role}/{quote(name, safe='')}"
        for window in (STATS_WINDOW_DAYS, 30):
            try:
                return parse_person(self.src.get(path, {"window": window}, ttl=6 * 3600), venue)
            except SourceError as exc:
                if exc.kind != "unavailable":
                    raise
        return parse_person(self.src.get(path, ttl=6 * 3600), venue)

    def jockey(self, name: str, venue: str) -> PersonStats:
        return self._person("jockey", name, venue)

    def trainer(self, name: str, venue: str) -> PersonStats:
        return self._person("trainer", name, venue)

    def track_bias(self, venue: str, distance_m: int | None) -> dict[int, float]:
        data = self.src.get(f"/v1/stats/track-bias/{track_slug(venue)}", ttl=6 * 3600)
        return parse_track_bias(data, distance_m)
