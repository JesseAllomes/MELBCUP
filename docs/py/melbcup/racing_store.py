"""Durable record of the last-minute checks, in blob container `nba` (owner, 2026-11-07).

  racing/<date>/<venue>/checks.json   the early and late picks of every race (and, once graded,
                                      what they returned), restored when the meeting is loaded
  racing/log/<date>.jsonl             one line per graded race: market and model chances per
                                      runner, the winner, what the picks returned
  racing/tuning.json                  written by tools/racing/learn.py; read by the model

All three go through the same `blob_reader` / `blob_writer` the push store uses, so they work
only where NBA_ACCOUNT names the storage account (managed identity). Elsewhere `from_env()` is
None and nothing is saved. A blob that cannot be read or written never stops the board.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable
from dataclasses import fields
from datetime import date, datetime

log = logging.getLogger(__name__)

TUNING_NAME = "racing/tuning.json"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "unknown"


def _when(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def line_to_json(x) -> dict:
    return {f.name: getattr(x, f.name) for f in fields(x) if f.name != "exotic"}


def line_from_json(d: dict, cls):
    names = {f.name for f in fields(cls)} - {"exotic"}
    return cls(**{k: v for k, v in d.items() if k in names})


def check_to_json(c) -> dict:
    out = {}
    for f in fields(c):
        v = getattr(c, f.name)
        if f.name in ("early", "late"):
            v = None if v is None else [line_to_json(x) for x in v]
        elif isinstance(v, datetime):
            v = v.isoformat()
        out[f.name] = v
    return out


def check_from_json(d: dict, check_cls, line_cls):
    kw = dict(d)
    for k in ("jump", "early_at", "late_at"):
        kw[k] = _when(kw.get(k))
    for k in ("early", "late"):
        kw[k] = None if kw.get(k) is None else tuple(line_from_json(x, line_cls) for x in kw[k])
    names = {f.name for f in fields(check_cls)}
    return check_cls(**{k: v for k, v in kw.items() if k in names})


class RacingStore:
    def __init__(self, read: Callable[[str], bytes | None], write: Callable[[str, bytes], None]):
        self.read, self.write = read, write
        self._last: dict[str, bytes] = {}  # what was last written per name: skip unchanged saves

    @staticmethod
    def checks_name(race_date: date, venue: str) -> str:
        return f"racing/{race_date.isoformat()}/{slug(venue)}/checks.json"

    @staticmethod
    def log_name(race_date: date) -> str:
        return f"racing/log/{race_date.isoformat()}.jsonl"

    def save_checks(self, race_date: date, venue: str, checks: dict, check_cls=None) -> None:
        doc = {str(n): check_to_json(c) for n, c in sorted(checks.items())}
        name, body = self.checks_name(race_date, venue), json.dumps(doc).encode()
        if self._last.get(name) == body:
            return
        try:
            self.write(name, body)
            self._last[name] = body
        except Exception:  # a storage hiccup must not stop the board
            log.warning("could not save checks", exc_info=True)

    def load_checks(self, race_date: date, venue: str, check_cls, line_cls) -> dict:
        try:
            raw = self.read(self.checks_name(race_date, venue))
            doc = json.loads(raw) if raw else {}
            return {int(n): check_from_json(d, check_cls, line_cls) for n, d in doc.items()}
        except Exception:
            log.warning("could not restore checks", exc_info=True)
            return {}

    def log_race(self, race_date: date, venue: str, row: dict) -> None:
        """Add (or replace) this race's line in the day's log: read, merge, write back."""
        name = self.log_name(race_date)
        row = {"date": race_date.isoformat(), "venue": venue, **row}
        try:
            raw = self.read(name) or b""
            keep = []
            for line in raw.decode().splitlines():
                if not line.strip():
                    continue
                old = json.loads(line)
                if (old.get("venue"), old.get("race")) != (venue, row["race"]):
                    keep.append(old)
            keep.append(row)
            self.write(name, ("\n".join(json.dumps(x) for x in keep) + "\n").encode())
        except Exception:
            log.warning("could not log race", exc_info=True)

    def load_tuning(self) -> dict:
        try:
            raw = self.read(TUNING_NAME)
            return json.loads(raw) if raw else {}
        except Exception:
            log.warning("could not read tuning", exc_info=True)
            return {}


def from_env() -> RacingStore | None:
    account = os.environ.get("NBA_ACCOUNT")
    if not account:
        return None
    from melbcup.nba_feed import blob_reader
    from melbcup.push_store import blob_writer

    client = os.environ.get("AZURE_CLIENT_ID")
    return RacingStore(blob_reader(account, client), blob_writer(account, client))


def graded_row(race_no: int, model, check) -> dict:
    """The log line for one graded race. `model` is a RaceModel, `check` a graded RaceCheck
    (or None when no picks were saved)."""
    race = model.race
    finish = race.result.finish if race.result else {}
    winners = sorted(n for n, pos in finish.items() if pos == 1)
    runners = [
        {
            "no": n,
            "market": a.market_win,
            "model": round(a.win, 5),
            "won": n in winners,
        }
        for n, a in sorted(model.runners.items())
    ]
    row = {"race": race_no, "winners": winners, "sources": model.sources, "runners": runners}
    if check is not None:
        row.update(
            early_staked=sum(x.stake for x in check.early or ()),
            late_staked=sum(x.stake for x in check.late or ()),
            early_back=check.early_back,
            late_back=check.late_back,
            unknown=check.unknown,
        )
    return row
