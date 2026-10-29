"""racing.com's public form service: each runner's recent runs (finish, margin, starting price,
weight, jockey, class, where it settled, and the stewards' comment). National coverage, free,
and no key from the user: the key is the public one racing.com's own form pages send. It
replaces PuntersEdge's recent-form call (3 credits a race), which stays as the fallback.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from melbcup.domain import (
    Card,
    Race,
    RaceResult,
    Runner,
    RunNote,
    StatLine,
    going_band,
    parse_margin,
)
from melbcup.sources.http import JsonSource, SourceError
from melbcup.sources.puntersedge import MarketSnapshot, parse_race_prices

if TYPE_CHECKING:
    import httpx

BASE_URL = "https://graphql.rmdprod.racing.com"
PUBLIC_KEY = "da2-6nsi4ztsynar3l3frgxf77q5fe"  # racing.com's own form pages send this one
RUNS_KEPT = 6
RUNS_TTL = 6 * 3600

MEETING = (
    "query($venueName: String, $date: String) { GetMeetingByVenueDateTrial("
    "venueName: $venueName, date: $date, isTrial: 0, isJumpOut: 0) { id } }"
)
FIELD = (
    "query($meetCode: ID!, $raceNumber: Int!) { getRaceForm(meetCode: $meetCode, "
    "raceNumber: $raceNumber) { formRaceEntries { raceEntryNumber horseCode } } }"
)
RUNS = (
    "query($horseCode: ID!) { GetRaceEntryItemByHorsePaged(horseCode: $horseCode, limit: 12) {"
    " finish margin startingPrice weightCarried jockeyName positionAtSettledAbv commentStewards"
    " race { date isTrial isJumpOut venueAbbr distance trackCondition class runnersCount } } }"
)

RESULTS = (
    "query($meetCode: ID!, $raceNumber: Int!) {"
    " getRaceForm(meetCode: $meetCode, raceNumber: $raceNumber) { status formRaceEntries {"
    " raceEntryNumber horseName finish scratched startingPrice odds { providerCode oddsPlace } } }"
    " GetBettingData(meetCode: $meetCode, raceNumber: $raceNumber) {"
    " exotics { poolStatusCode selections amount } } }"
)
RACES = (
    "query($meetCode: ID!) { getRacesForMeet(meetCode: $meetCode) {"
    " raceNumber raceStatus time trackCondition } }"
)
PRICES = (
    "query($meetCode: ID!, $raceNumber: Int!) {"
    " GetBettingData(meetCode: $meetCode, raceNumber: $raceNumber) { formRaceEntries {"
    " raceEntryNumber scratched odds { providerCode oddsWin oddsPlace updated } } } }"
)
# racing.com's fixed-price bookmakers, under the keys the PuntersEdge feed uses for them.
BOOKS = {"SB2": "sportsbet", "LB2": "ladbrokes_au", "PB3": "pointsbetau", "BT": "bet365_au"}
PRICE_TTL = 30
MEETINGS = (
    "query($states: String!, $daysBack: Int!, $daysForward: Int!, $userDate: String!) {"
    " GetRaceMeetingsByStateNew(states: $states, daysBack: $daysBack, daysForward: $daysForward,"
    " userDate: $userDate) { id venue date state isTrial isJumpOut } }"
)
STATES = ("VIC", "NSW", "QLD", "SA", "WA", "TAS", "NT", "ACT")
CARD_RACES = (
    "query($meetCode: ID!) { getRacesForMeet(meetCode: $meetCode) { raceNumber raceStatus"
    " distance time class name meet { trackCondition railPosition weather } } }"
)
CARD_FIELD = (
    "query($meetCode: ID!, $raceNumber: Int!) { getRaceForm(meetCode: $meetCode,"
    " raceNumber: $raceNumber) { formRaceEntries { raceEntryNumber horseName horseCode"
    " barrierNumber weight jockeyName trainerName scratched emergency gearChanges handicapRating"
    " lastRaceDate trackStats distanceStats trackDistanceStats horse { age sex owners"
    " sireHorseName damHorseName lastFive firstUpStats secondUpStats goodStats softStats"
    " heavyStats firmStats syntheticStats } } } }"
)
GOING_STATS = {
    "good": "goodStats",
    "soft": "softStats",
    "heavy": "heavyStats",
    "firm": "firmStats",
    "synthetic": "syntheticStats",
}
EXOTIC_CODES = {
    "trifecta": "TF",
    "first 4": "FF",
    "first four": "FF",
    "quinella": "QN",
    "exacta": "EX",
}
PLACE_FROM = ("SB2", "V", "N", "Q")  # Sportsbet's fixed place price, else a tote's place dividend


def _int(text: Any) -> int | None:
    digits = "".join(ch for ch in str(text or "") if ch.isdigit())
    return int(digits) if digits else None


def _number(text: Any) -> float | None:
    cleaned = str(text or "").replace("$", "").replace("kg", "").replace(",", "").strip()
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def statline(text: Any) -> StatLine | None:
    """``"7:2-2-1"`` or ``"29-7-5-2"`` (starts, wins, seconds, thirds) -> StatLine."""
    parts = [int(x) for x in str(text or "").replace(":", "-").split("-") if x.strip().isdigit()]
    if len(parts) != 4 or not parts[0]:
        return None
    starts, wins, seconds, thirds = parts
    return StatLine(starts, wins, wins + seconds + thirds)


def _last_figures(text: Any) -> str | None:
    """``'["7","-","6","0","5"]'`` (oldest first) -> ``"7x605"``, newest last like PuntersEdge's."""
    try:
        figures = json.loads(text) if text else []
    except ValueError:
        return None
    out = "".join(str(f) if str(f).isdigit() and len(str(f)) == 1 else "x" for f in figures)
    return out or None


def parse_runner(e: dict[str, Any], condition: str | None) -> Runner:
    horse = e.get("horse") or {}
    by_going = {
        band: line for band, key in GOING_STATS.items() if (line := statline(horse.get(key)))
    }
    career = None
    if by_going:  # the going records together cover every start
        lines = by_going.values()
        career = StatLine(
            sum(x.starts for x in lines), sum(x.wins for x in lines), sum(x.top3 for x in lines)
        )
    band = going_band(condition)
    last = e.get("lastRaceDate")
    return Runner(
        number=int(e["raceEntryNumber"]),
        name=e.get("horseName") or f"No. {e['raceEntryNumber']}",
        barrier=_int(e.get("barrierNumber")),
        jockey=e.get("jockeyName"),
        trainer=e.get("trainerName"),
        owner=horse.get("owners"),
        weight_kg=_number(e.get("weight")),
        scratched=bool(e.get("scratched")),
        emergency=bool(e.get("emergency")),
        age=_int(horse.get("age")),
        sex=horse.get("sex"),
        sire=horse.get("sireHorseName"),
        dam=horse.get("damHorseName"),
        gear_changes=e.get("gearChanges"),
        last10=_last_figures(horse.get("lastFive")),
        hcp_rating=_int(e.get("handicapRating")),
        last_start_date=date.fromisoformat(last[:10]) if last else None,
        career=career,
        track=statline(e.get("trackStats")),
        distance=statline(e.get("distanceStats")),
        track_distance=statline(e.get("trackDistanceStats")),
        going=by_going.get(band) if band else None,
        going_records=by_going or None,
        first_up=statline(horse.get("firstUpStats")),
        second_up=statline(horse.get("secondUpStats")),
    )


def parse_runs(data: dict[str, Any]) -> list[RunNote]:
    """Newest first; trials and jump-outs left out."""
    out = []
    for item in data.get("GetRaceEntryItemByHorsePaged") or []:
        race = item.get("race") or {}
        if race.get("isTrial") or race.get("isJumpOut") or not race.get("date"):
            continue
        note = (item.get("commentStewards") or "").strip()
        finish = _int(item.get("finish"))
        out.append(
            RunNote(
                run_date=date.fromisoformat(race["date"][:10]),
                venue=race.get("venueAbbr") or "",
                distance_m=_int(race.get("distance")),
                condition=race.get("trackCondition"),
                finish=finish,
                settled=_int(item.get("positionAtSettledAbv")),
                stewards=" ".join(note.split()) or None,
                field_size=_int(race.get("runnersCount")),
                margin_l=0.0 if finish == 1 else parse_margin(item.get("margin")),
                sp=_number(item.get("startingPrice")),
                weight_kg=_number(item.get("weightCarried")),
                jockey=item.get("jockeyName"),
                race_class=race.get("class"),
            )
        )
    return sorted(out, key=lambda n: n.run_date, reverse=True)


def parse_result(data: dict[str, Any]) -> RaceResult | None:
    """A run race's official result, or None before it is run."""
    form = data.get("getRaceForm") or {}
    status = (form.get("status") or "").lower()
    if "result" not in status:
        return None
    finish, sp, names, place = {}, {}, {}, {}
    for e in form.get("formRaceEntries") or []:
        n, pos = _int(e.get("raceEntryNumber")), _int(e.get("finish"))
        if n is None or e.get("scratched") or not pos:
            continue
        finish[n], names[n] = pos, e.get("horseName") or str(n)
        if (price := _number(e.get("startingPrice"))) and price > 1.0:
            sp[n] = price
        quotes = {o.get("providerCode"): _number(o.get("oddsPlace")) for o in e.get("odds") or []}
        if (div := next((quotes[k] for k in PLACE_FROM if quotes.get(k)), None)) is not None:
            place[n] = div
    exotics: dict[str, tuple[tuple[int, ...], float]] = {}
    for x in (data.get("GetBettingData") or {}).get("exotics") or []:
        code = EXOTIC_CODES.get((x.get("poolStatusCode") or "").strip().lower())
        amount = _number(x.get("amount"))
        if code and amount and code not in exotics:
            try:
                exotics[code] = (tuple(int(v) for v in x["selections"].split("/")), amount)
            except (KeyError, ValueError):
                continue
    if not finish:
        return None
    final = "interim" not in status
    return RaceResult("final" if final else "interim", finish, sp, names, place, exotics)


def as_next_to_go(race: dict[str, Any], prices: dict[str, Any]) -> dict[str, Any]:
    """One race in the PuntersEdge next-to-go shape, so the same parser (best price per runner,
    Sportsbet's, and the margin-free consensus) reads both feeds."""
    runners, scratched = [], []
    for e in (prices.get("GetBettingData") or {}).get("formRaceEntries") or []:
        n = _int(e.get("raceEntryNumber"))
        if n is None:
            continue
        if e.get("scratched"):
            scratched.append({"number": n})
            continue
        books = []
        for o in e.get("odds") or []:
            key = BOOKS.get(o.get("providerCode"))
            win = _number(o.get("oddsWin"))
            if key and win:
                seen = o.get("updated")
                books.append(
                    {
                        "key": key,
                        "win_price": win,
                        "place_price": _number(o.get("oddsPlace")),
                        "last_update": datetime.fromtimestamp(int(seen), UTC).isoformat()
                        if seen
                        else None,
                    }
                )
        runners.append({"number": n, "bookmakers": books})
    starters = len(runners)
    return {
        "runners": runners,
        "scratchings": scratched,
        "places_paid": 3 if starters >= 8 else 2 if starters >= 5 else 1,
        "start_time": race.get("time"),
        "track_condition": race.get("trackCondition"),
    }


class RacingComClient:
    def __init__(self, api_key: str = PUBLIC_KEY, *, transport: httpx.BaseTransport | None = None):
        self.src = JsonSource("racing.com", BASE_URL, api_key, transport=transport)
        self._codes: dict[tuple[date, str], str] = {}  # (day, venue) -> meeting code

    @staticmethod
    def _request(query: str, variables: dict[str, Any], ttl: float) -> tuple[str, dict, float]:
        return "/", {"query": query, "variables": json.dumps(variables, sort_keys=True)}, ttl

    def _query(self, query: str, variables: dict[str, Any], ttl: float) -> dict[str, Any]:
        path, params, ttl = self._request(query, variables, ttl)
        body = self.src.get(path, params, ttl=ttl)
        if not isinstance(body, dict) or body.get("data") is None:
            errors = body.get("errors") if isinstance(body, dict) else None
            message = (errors or [{}])[0].get("message") or "no data"
            raise SourceError("racing.com", "bad_response", message)
        return body["data"]

    def meeting_code(self, race_date: date, venue: str) -> str | None:
        if (known := self._codes.get((race_date, venue.lower()))) is not None:
            return known
        found = self._query(MEETING, {"venueName": venue, "date": race_date.isoformat()}, 6 * 3600)
        meetings = found.get("GetMeetingByVenueDateTrial") or []
        return str(meetings[0]["id"]) if meetings else None

    def field(self, meet_code: str, race_number: int) -> dict[int, str]:
        """Saddlecloth -> racing.com's horse code."""
        data = self._query(FIELD, {"meetCode": meet_code, "raceNumber": race_number}, 3600)
        entries = (data.get("getRaceForm") or {}).get("formRaceEntries") or []
        return {
            int(e["raceEntryNumber"]): str(e["horseCode"])
            for e in entries
            if e.get("raceEntryNumber") and e.get("horseCode")
        }

    def _runs_request(self, horse_code: str) -> tuple[str, dict, float]:
        return self._request(RUNS, {"horseCode": horse_code}, RUNS_TTL)

    def runs(self, horse_code: str) -> list[RunNote]:
        return parse_runs(self._query(RUNS, {"horseCode": horse_code}, RUNS_TTL))

    def results(self, race_date: date, venue: str, races: list[int]) -> dict[int, RaceResult]:
        """Race number -> result, for the races already run (free; PuntersEdge charges 2)."""
        code = self.meeting_code(race_date, venue)
        if code is None:
            raise SourceError("racing.com", "not_found", f"no meeting for {venue} on {race_date}")
        out = {}
        for n in races:
            result = parse_result(self._query(RESULTS, {"meetCode": code, "raceNumber": n}, 60))
            if result is not None:
                out[n] = result
        return out

    def card_prices(
        self, race_date: date, venue: str, races: list[int]
    ) -> dict[int, MarketSnapshot]:
        """Race number -> Sportsbet, Ladbrokes, PointsBet and bet365 prices for the races not
        yet run (free; PuntersEdge charges 2 a check). Races with no prices are left out."""
        code = self.meeting_code(race_date, venue)
        if code is None:
            raise SourceError("racing.com", "not_found", f"no meeting for {venue} on {race_date}")
        meta = {
            r["raceNumber"]: r
            for r in self._query(RACES, {"meetCode": code}, PRICE_TTL).get("getRacesForMeet") or []
        }
        out = {}
        for n in races:
            race = meta.get(n, {})
            if "result" in (race.get("raceStatus") or "").lower():
                continue
            data = self._query(PRICES, {"meetCode": code, "raceNumber": n}, PRICE_TTL)
            snap = parse_race_prices(as_next_to_go(race, data))
            if any(p.best_win for p in snap.prices.values()):
                out[n] = snap
        return out

    def meetings(self, race_date: date, today: date) -> list[str]:
        """Australian meetings on a day (no trials or jump-outs), as racing.com names them.
        Its list runs relative to today; the meeting codes are kept for the card load."""
        back, forward = max(0, (today - race_date).days), max(0, (race_date - today).days)
        found: dict[str, str] = {}
        for state in STATES:
            rows = (
                self._query(
                    MEETINGS,
                    {
                        "states": state,
                        "daysBack": back,
                        "daysForward": forward,
                        "userDate": today.isoformat(),
                    },
                    1800,
                ).get("GetRaceMeetingsByStateNew")
                or []
            )
            for m in rows:
                if (
                    m.get("isTrial")
                    or m.get("isJumpOut")
                    or str(m.get("date", ""))[:10] != race_date.isoformat()
                ):
                    continue
                found.setdefault(m["venue"], str(m["id"]))
        self._codes.update({(race_date, v.lower()): c for v, c in found.items()})
        return sorted(found)

    def card(self, race_date: date, venue: str) -> Card:
        """The meeting's field from racing.com: runners, scratchings, barriers, weights, riders,
        owners, breeding, ratings and their records (career, track, distance, going, spells)."""
        code = self.meeting_code(race_date, venue)
        if code is None:
            raise SourceError("racing.com", "not_found", f"no meeting for {venue} on {race_date}")
        races = self._query(CARD_RACES, {"meetCode": code}, 600).get("getRacesForMeet") or []
        card = Card(venue, race_date)
        for r in sorted(races, key=lambda x: x.get("raceNumber") or 0):
            meet = r.get("meet") or {}
            condition = meet.get("trackCondition")
            card.condition, card.rail = (
                card.condition or condition,
                card.rail or meet.get("railPosition"),
            )
            race = Race(
                venue=venue,
                race_date=race_date,
                number=int(r["raceNumber"]),
                name=r.get("name"),
                distance_m=_int(r.get("distance")),
                condition=condition,
                weather=meet.get("weather"),
                race_class=r.get("class"),
                start_time=datetime.fromisoformat(r["time"].replace("Z", "+00:00"))
                if r.get("time")
                else None,
            )
            field = self._query(CARD_FIELD, {"meetCode": code, "raceNumber": race.number}, 600)
            entries = (field.get("getRaceForm") or {}).get("formRaceEntries") or []
            race.runners = [parse_runner(e, condition) for e in entries if e.get("raceEntryNumber")]
            starters = len(race.starters)
            race.places_paid = 3 if starters >= 8 else 2 if starters >= 5 else 1
            card.races.append(race)
        if not card.races:
            raise SourceError("racing.com", "not_found", f"no field yet for {venue} on {race_date}")
        return card

    def horse_codes(self, card: Card) -> dict[tuple[int, int], str]:
        """(race, saddlecloth) -> horse code for the whole card: one call per race."""
        code = self.meeting_code(card.race_date, card.venue)
        if code is None:
            return {}
        out = {}
        for race in card.races:
            for number, horse in self.field(code, race.number).items():
                out[(race.number, number)] = horse
        return out

    def load_requests(self, card: Card) -> list[tuple[str, dict[str, Any], float]]:
        """The runs requests a card load makes (after the meeting and field look-ups, which this
        makes itself and caches), so the browser can fetch them side by side."""
        try:
            codes = self.horse_codes(card)
        except SourceError:
            return []
        return [self._runs_request(h) for h in sorted(set(codes.values()))]
