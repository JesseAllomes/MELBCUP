"""Meetings already downloaded, kept so opening them again needs no fetching.

Saved meetings are open: no key, no password. Each card is a pickle compressed with zlib and
base64-encoded, so it travels as text; the pickles are our own domain objects, written by
tools/build_archive.py and shipped with the app like its code.

Layout under the archive root:
    index.json      {"meetings": {"YYYY-MM-DD": [venue, ...]}}
    YYYY-MM-DD/<venue-slug>.bin         base64 of the zlib-compressed pickled Card
    history.bin                         base64 of the zlib-compressed JSON of the model's record on
                                        every saved race (our picks and the official results)
"""

from __future__ import annotations

import base64
import json
import os
import pickle
import zlib
from collections.abc import Callable
from datetime import date

from melbcup.domain import Card


class ArchiveError(ValueError):
    pass


def slug(venue: str) -> str:
    return "-".join(venue.lower().split())


def _pack(obj: bytes) -> str:
    return base64.b64encode(zlib.compress(obj, 9)).decode()


def _unpack(raw: str) -> bytes:
    try:
        return zlib.decompress(base64.b64decode(raw))
    except (ValueError, zlib.error) as exc:
        raise ArchiveError("damaged file") from exc


class Archive:
    """Read side. ``read`` maps a path under the archive root to its text, or None if absent
    (a file read on a server, a same-origin request in the browser)."""

    def __init__(self, read: Callable[[str], str | None]):
        self._read = read
        self._index: dict[date, list[str]] = {}
        self.open = False  # an index was found
        raw = read("index.json")
        if raw is None:
            return
        try:
            meetings = json.loads(raw)["meetings"]
            self._index = {date.fromisoformat(d): list(v) for d, v in meetings.items()}
        except (ValueError, KeyError, TypeError, AttributeError):
            return  # from another build: treated as no archive
        self.open = True

    def venues(self, day: date) -> list[str]:
        return list(self._index.get(day, []))

    def has(self, day: date, venue: str) -> bool:
        return venue.lower() in (v.lower() for v in self._index.get(day, []))

    def history(self) -> list[dict]:
        """The model's record on every saved race (built when the archive was written)."""
        try:
            if (raw := self._read("history.bin")) is not None:
                return json.loads(_unpack(raw))
        except (ArchiveError, ValueError):
            pass  # from another build: show the races graded on this phone instead
        return []

    def load(self, day: date, venue: str) -> Card:
        if not self.has(day, venue):
            raise ArchiveError(f"{venue} on {day} is not saved")
        raw = self._read(f"{day.isoformat()}/{slug(venue)}.bin")
        if raw is None:
            raise ArchiveError(f"{venue} on {day}: file missing")
        return pickle.loads(_unpack(raw))


def write(root: str, cards: list[Card], history: list[dict] | None = None) -> None:
    """Build side (tools/build_archive.py): write every card and the history, unencrypted."""
    meetings: dict[str, list[str]] = {}
    for card in sorted(cards, key=lambda c: (c.race_date, c.venue)):
        folder = os.path.join(root, card.race_date.isoformat())
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, f"{slug(card.venue)}.bin"), "w") as fh:
            fh.write(_pack(pickle.dumps(card)))
        meetings.setdefault(card.race_date.isoformat(), []).append(card.venue)
    if history is not None:
        with open(os.path.join(root, "history.bin"), "w") as fh:
            fh.write(_pack(json.dumps(history).encode()))
    with open(os.path.join(root, "index.json"), "w") as fh:
        json.dump({"meetings": meetings}, fh, indent=1)
