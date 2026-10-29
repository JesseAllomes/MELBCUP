"""PuntersEdge: the day's acceptances (with owners), recent field form and bookmaker prices.

Credit costs (per the vendor docs): acceptances 2, form 3, markets 2.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import httpx

from melbcup.config import MELBOURNE
from melbcup.domain import (
    Card,
    PastRun,
    Quote,
    Race,
    Runner,
    RunnerPrices,
    StatLine,
    parse_margin,
)
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
    """Acceptances give ``2:45PM`` in local time."""
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


def parse_markets(data: dict[str, Any]) -> MarketSnapshot:
    """Best win/place price per runner, Sportsbet's price, and a margin-free consensus.

    Consensus: each book's win market is normalised to 100%, then the median probability per
    runner across books, renormalised. Only books quoting at least 80% of the field count.
    """
    race = data.get("race") or {}
    places_paid = int(race.get("places_paid") or 3)
    scratched = {s.get("number") for s in data.get("scratchings") or []}
    prices: dict[int, RunnerPrices] = {}

    def slot(n: int) -> RunnerPrices:
        return prices.setdefault(n, RunnerPrices(number=n))

    latest: datetime | None = None
    per_book_probs: dict[int, list[float]] = {}
    for market in data.get("markets", []):
        kind = market.get("market")
        if kind not in ("win", "place"):
            continue
        for best in market.get("best", []):
            n = best.get("number")
            if n in scratched or not best.get("price"):
                continue
            q = Quote(float(best["price"]), best.get("bookmaker") or "?")
            if kind == "win":
                slot(n).best_win = q
            else:
                slot(n).best_place = q
        books = market.get("bookmakers", [])
        field_size = max((b.get("runners_quoted") or 0 for b in books), default=0)
        for book in books:
            seen = _utc(book.get("observed_at"))
            if seen and (latest is None or seen > latest):
                latest = seen
            quoted = {
                r["number"]: float(r["price"])
                for r in book.get("runners", [])
                if r.get("price") and r.get("number") not in scratched
            }
            if book.get("key") == SPORTSBET:
                for n, p in quoted.items():
                    if kind == "win":
                        slot(n).sportsbet_win = p
                    else:
                        slot(n).sportsbet_place = p
            if kind == "win" and field_size and len(quoted) >= 0.8 * field_size:
                for n, p in _no_vig(quoted).items():
                    per_book_probs.setdefault(n, []).append(p)
                    slot(n).books += 1

    medians = {n: statistics.median(ps) for n, ps in per_book_probs.items() if ps}
    total = sum(medians.values())
    for n, p in medians.items():
        slot(n).consensus_prob = p / total if total else None
    return MarketSnapshot(prices, places_paid, latest, {n for n in scratched if n is not None})


class PuntersEdgeClient:
    def __init__(self, api_key: str, *, transport: httpx.BaseTransport | None = None):
        self.src = JsonSource("PuntersEdge", BASE_URL, api_key, transport=transport)

    def acceptances(self, race_date: date, venue: str) -> Card:
        data = self.src.get(
            "/v1/racing/acceptances",
            {"date": race_date.isoformat(), "venue": venue},
            ttl=600,
        )
        return parse_acceptances(data, venue, race_date)

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

    def markets(
        self, race_date: date, venue: str, race_number: int, *, ttl: float = 0
    ) -> MarketSnapshot:
        data = self.src.get(
            "/v1/racing/markets",
            {
                "venue": venue,
                "meeting_date": race_date.isoformat(),
                "race_number": race_number,
                "country": "AU",
                "markets": "win,place",
            },
            ttl=ttl,
        )
        return parse_markets(data)
