"""racing.com's public form service: each runner's recent runs with the stewards' comment on
each, where it settled, and its finish. National coverage, free, and no key from the user: the
key is the public one racing.com's own form pages send with every request.
"""

from __future__ import annotations

import json
from datetime import date
from typing import TYPE_CHECKING, Any

from melbcup.domain import Card, RunNote
from melbcup.sources.http import JsonSource, SourceError

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
    "query($horseCode: ID!) { GetRaceEntryItemByHorsePaged(horseCode: $horseCode, limit: 8) {"
    " finish positionAtSettledAbv commentStewards"
    " race { date isTrial isJumpOut venueAbbr distance trackCondition } } }"
)


def _int(text: Any) -> int | None:
    digits = "".join(ch for ch in str(text or "") if ch.isdigit())
    return int(digits) if digits else None


def parse_runs(data: dict[str, Any]) -> list[RunNote]:
    """Newest first; trials and jump-outs left out."""
    out = []
    for item in data.get("GetRaceEntryItemByHorsePaged") or []:
        race = item.get("race") or {}
        if race.get("isTrial") or race.get("isJumpOut") or not race.get("date"):
            continue
        note = (item.get("commentStewards") or "").strip()
        out.append(
            RunNote(
                run_date=date.fromisoformat(race["date"][:10]),
                venue=race.get("venueAbbr") or "",
                distance_m=_int(race.get("distance")),
                condition=race.get("trackCondition"),
                finish=_int(item.get("finish")),
                settled=_int(item.get("positionAtSettledAbv")),
                stewards=" ".join(note.split()) or None,
            )
        )
    return sorted(out, key=lambda n: n.run_date, reverse=True)


class RacingComClient:
    def __init__(self, api_key: str = PUBLIC_KEY, *, transport: httpx.BaseTransport | None = None):
        self.src = JsonSource("racing.com", BASE_URL, api_key, transport=transport)

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
