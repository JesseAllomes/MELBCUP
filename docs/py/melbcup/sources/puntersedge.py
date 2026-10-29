"""PuntersEdge: the day's acceptances (with owners), recent field form and bookmaker prices.

Credit costs (per the vendor docs): acceptances 2, form 3, next-to-go 2 for the whole card.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from melbcup.config import MELBOURNE
from melbcup.domain import (
    Card,
    PastRun,
    Quote,
    Race,
    RaceResult,
    Runner,
    RunnerPrices,
    StatLine,
    parse_margin,
)

if TYPE_CHECKING:
    import httpx

from melbcup.sources.http import JsonSource

BASE_URL = "https://api.puntersedge.online"
SPORTSBET = "sportsbet"


def _date(text: str | None) -> date | None:
    try:
        return date.fromisoformat(text[:10]) if text else None
    except ValueError:
        return None


def _utc(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _local_time(race_date: date, text: str | None) -> datetime | None:
    """Acceptances give ``2:45PM`` in the track's local time. Read as Melbourne time, which is
    right for Victorian tracks; prices replace it with the exact UTC start."""
    if not text:
        return None
    try:
        t = datetime.strptime(text.strip().upper(), "%I:%M%p").time()
    except ValueError:
        return None
    return datetime.combine(race_date, t, tzinfo=MELBOURNE)


def parse_acceptances(data: dict[str, Any], venue: str, race_date: date) -> Card:
    card = Card(venue=venue, race_date=race_date)
    meeting = next(
        (m for m in data.get("meetings", []) if m.get("venue", "").lower() == venue.lower()),
        None,
    )
    if meeting is None:
        card.warnings.append(f"No acceptances published for {venue} on {race_date}")
        return card
    track = meeting.get("track") or {}
    card.rail = track.get("rail")
    card.condition = track.get("track_condition")
    for r in sorted(meeting.get("races", []), key=lambda x: x.get("race_number", 0)):
        race = Race(
            venue=venue,
            race_date=race_date,
            number=r["race_number"],
            name=r.get("race_name"),
            race_id=r.get("race_id"),
            distance_m=r.get("distance_m"),
            condition=card.condition,
            race_class=r.get("race_class"),
            prize_total=r.get("prize_total"),
            start_time=_local_time(race_date, r.get("start_time_local")),
        )
        for x in r.get("runners", []):
            race.runners.append(
                Runner(
                    number=x["number"],
                    name=x.get("runner_name") or x.get("name") or f"No. {x['number']}",
                    barrier=x.get("barrier"),
                    jockey=x.get("jockey"),
                    trainer=x.get("trainer"),
                    owner=x.get("owner"),
                    weight_kg=x.get("weight_kg"),
                    claim_kg=x.get("claim_kg"),
                    scratched=bool(x.get("scratched")),
                    emergency=bool(x.get("emergency")),
                    age=x.get("age"),
                    sex=x.get("sex"),
                    sire=x.get("sire"),
                    dam=x.get("dam"),
                    gear_changes=x.get("gear_changes"),
                    last10=x.get("last10"),
                    hcp_rating=x.get("hcp_rating"),
                    last_start_date=_date(x.get("last_start_date")),
                    last_start_position=x.get("last_start_position"),
                    last_start_weight_kg=x.get("last_start_weight_kg"),
                    last_start_rating=x.get("last_start_rating"),
                )
            )
        card.races.append(race)
    return card


def parse_form(data: dict[str, Any]) -> dict[int, tuple[list[PastRun], StatLine | None]]:
    """Runner number -> (recent runs newest first, record over every run the feed holds)."""
    out: dict[int, tuple[list[PastRun], StatLine | None]] = {}
    for x in data.get("runners", []):
        runs: list[PastRun] = []
        for run in x.get("runs", []):
            run_date = _date(run.get("date"))
            if run_date is None or run.get("status") not in (None, "ran"):
                continue
            runs.append(
                PastRun(
                    run_date=run_date,
                    venue=run.get("venue") or "",
                    distance_m=run.get("distance_m"),
                    condition=run.get("track_condition"),
                    position=run.get("position"),
                    field_size=run.get("field_size"),
                    margin_l=0.0 if run.get("position") == 1 else parse_margin(run.get("margin")),
                    sp=run.get("sp"),
                    weight_kg=run.get("carried_kg") or run.get("weight_kg"),
                    jockey=run.get("jockey"),
                    race_class=run.get("race_class"),
                )
            )
        runs.sort(key=lambda p: p.run_date, reverse=True)
        s = x.get("stats") or {}
        stat = None
        if s.get("starts"):
            # The feed's `places` is finishes in the first three, wins included.
            stat = StatLine(int(s["starts"]), int(s.get("wins") or 0), int(s.get("places") or 0))
        out[x["number"]] = (runs, stat)
    return out


def _no_vig(book_prices: dict[int, float]) -> dict[int, float]:
    inv = {n: 1.0 / p for n, p in book_prices.items() if p and p > 1.0}
    total = sum(inv.values())
    return {n: v / total for n, v in inv.items()} if total else {}


@dataclass
class MarketSnapshot:
    prices: dict[int, RunnerPrices]
    places_paid: int
    observed_at: datetime | None
    scratched: set[int]
    start_time: datetime | None = None


def parse_race_prices(race: dict[str, Any]) -> MarketSnapshot:
    """One next-to-go race -> best win/place price per runner, Sportsbet's, and a consensus.

    Stale quotes (older than the feed's own freshness threshold) are dropped. Consensus: each
    book's win market is normalised to 100%, then the median probability per runner across
    books, renormalised. Only books quoting at least 80% of the field count.
    """
    scratched = {s.get("number") for s in race.get("scratchings") or [] if s.get("number")}
    prices: dict[int, RunnerPrices] = {}
    book_win: dict[str, dict[int, float]] = {}
    latest: datetime | None = None
    for runner in race.get("runners", []):
        n = runner.get("number")
        if n is None or n in scratched:
            continue
        rp = prices.setdefault(n, RunnerPrices(number=n))
        for q in runner.get("bookmakers", []):
            if q.get("stale"):
                continue
            key = q.get("key") or "?"
            win, place = q.get("win_price"), q.get("place_price")
            seen = _utc(q.get("last_update"))
            if seen and (latest is None or seen > latest):
                latest = seen
            if win and win > 1.0:
                book_win.setdefault(key, {})[n] = float(win)
                if rp.best_win is None or win > rp.best_win.price:
                    rp.best_win = Quote(float(win), key)
            if place and place > 1.0 and (rp.best_place is None or place > rp.best_place.price):
                rp.best_place = Quote(float(place), key)
            if key == SPORTSBET:
                rp.sportsbet_win = float(win) if win else None
                rp.sportsbet_place = float(place) if place else None

    field = len(prices)
    per_runner: dict[int, list[float]] = {}
    for quoted in book_win.values():
        if field and len(quoted) >= 0.8 * field:
            for n, p in _no_vig(quoted).items():
                per_runner.setdefault(n, []).append(p)
    medians = {n: statistics.median(ps) for n, ps in per_runner.items()}
    total = sum(medians.values())
    for n, p in medians.items():
        prices[n].consensus_prob = p / total if total else None
        prices[n].books = len(per_runner[n])
    places_paid = int(race.get("places_paid") or 3)
    return MarketSnapshot(prices, places_paid, latest, scratched, _utc(race.get("start_time")))


def parse_next_to_go(
    data: list[dict[str, Any]], venue: str, race_date: date
) -> dict[int, MarketSnapshot]:
    """Race number -> prices, for this venue's races on this (Melbourne) date."""
    out = {}
    for race in data:
        start = _utc(race.get("start_time"))
        if (race.get("venue") or "").lower() != venue.lower() or start is None:
            continue
        if start.astimezone(MELBOURNE).date() != race_date:
            continue
        out[int(race["race_number"])] = parse_race_prices(race)
    return out


def _int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def parse_result(item: dict[str, Any]) -> RaceResult:
    finish, sp, names = {}, {}, {}
    for r in item.get("runners") or item.get("placings") or []:
        n = r.get("number")
        if n is None or r.get("status", "ran") != "ran":
            continue
        names[n] = r.get("name") or str(n)
        if r.get("position"):
            finish[n] = int(r["position"])
        if r.get("sp"):
            sp[n] = float(r["sp"])
    div = item.get("dividends") or {}
    place_div = {
        d["number"]: float(d["amount"])
        for d in div.get("straight") or []
        if d.get("market") == "PLC" and d.get("product") == "FIXED" and d.get("amount")
    }
    exotics: dict[str, tuple[tuple[int, ...], float]] = {}
    for d in div.get("exotics") or []:
        code, sel = d.get("code"), d.get("selection") or ""
        if code and d.get("amount") and code not in exotics:
            try:
                exotics[code] = (tuple(int(x) for x in sel.split(",")), float(d["amount"]))
            except ValueError:
                continue
    return RaceResult(item.get("status") or "interim", finish, sp, names, place_div, exotics)


def parse_results(data: list[dict[str, Any]], venue: str, race_date: date) -> dict[int, RaceResult]:
    out = {}
    for item in data:
        start = _utc(item.get("start_time"))
        if (item.get("venue") or "").lower() != venue.lower() or start is None:
            continue
        if start.astimezone(MELBOURNE).date() != race_date or not item.get("runners"):
            continue
        out[int(item["race_number"])] = parse_result(item)
    return out


class PuntersEdgeClient:
    def __init__(self, api_key: str, *, transport: httpx.BaseTransport | None = None):
        self.src = JsonSource("PuntersEdge", BASE_URL, api_key, transport=transport)
        self._credits: tuple[int | None, int | None] = (None, None)

    @property
    def credits_remaining(self) -> int | None:
        """From the latest response's X-Credits-Remaining header (or the last balance read)."""
        h = self.src.last_headers
        if "x-credits-remaining" in h:
            return _int(h["x-credits-remaining"])
        return self._credits[0]

    @property
    def credits_limit(self) -> int | None:
        h = self.src.last_headers
        if "x-credits-limit" in h:
            return _int(h["x-credits-limit"])
        return self._credits[1]

    def read_credits(self) -> None:
        """Balance check; /v1/keys/info costs no credits."""
        info = self.src.get("/v1/keys/info")
        self._credits = (_int(info.get("credits_remaining")), _int(info.get("credits_limit")))
        self.src.last_headers = {}

    def _acceptances(self, race_date: date) -> dict[str, Any]:
        """Every meeting's acceptances for the day in one call (2 credits), cached 10 minutes so
        finding meetings and then loading one costs a single call."""
        return self.src.get("/v1/racing/acceptances", {"date": race_date.isoformat()}, ttl=600)

    def acceptances(self, race_date: date, venue: str) -> Card:
        return parse_acceptances(self._acceptances(race_date), venue, race_date)

    def meetings(self, race_date: date) -> list[str]:
        """Venue names with published acceptances on this day."""
        data = self._acceptances(race_date)
        return sorted(m["venue"] for m in data.get("meetings", []) if m.get("venue"))

    def field_form(
        self, race_date: date, venue: str, race_number: int
    ) -> dict[int, tuple[list[PastRun], StatLine | None]]:
        data = self.src.get(
            "/v1/racing/form",
            {
                "venue": venue,
                "meeting_date": race_date.isoformat(),
                "race_number": race_number,
                "runs": 10,
            },
            ttl=3600,
        )
        return parse_form(data)

    def results(self, race_date: date, venue: str) -> dict[int, RaceResult]:
        """The meeting's settled results with SPs and dividends (2 credits)."""
        data = self.src.get(
            "/v1/racing/results",
            {"date": race_date.isoformat(), "venue": venue, "country": "AU", "category": "horse"},
        )
        return parse_results(data if isinstance(data, list) else [], venue, race_date)

    def card_prices(self, race_date: date, venue: str) -> dict[int, MarketSnapshot]:
        """Every priced race at the meeting in one call (2 credits on every plan).

        Bookmakers frame a race about 16 hours before the jump; races not framed yet are absent.
        """
        data = self.src.get(
            "/v1/racing/next-to-go",
            {
                "venue": venue,
                "categories": "horse",
                "country": "AU",
                "include_unresolved": "true",
                "num_races": 20,
            },
        )
        return parse_next_to_go(data if isinstance(data, list) else [], venue, race_date)
