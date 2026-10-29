"""Meetings already downloaded, kept so opening them again costs no credits.

The site is public, so each meeting is sealed with a key derived from the owner's PuntersEdge key
(PBKDF2-HMAC-SHA256): only a phone holding that key can read it, and the providers' data is not
republished in the clear. Sealing uses only hashlib/hmac, which the browser build has: a
SHA-256 counter-mode keystream with a random nonce, then HMAC-SHA256 over nonce and ciphertext.

Layout under the archive root:
    index.json                         {"salt", "check", "meetings": {"YYYY-MM-DD": [venue, ...]}}
    YYYY-MM-DD/<venue-slug>.bin         base64 of nonce | ciphertext | tag
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import pickle
import zlib
from collections.abc import Callable
from datetime import date

from melbcup.domain import Card

# The secret is a random API key, not a password, so stretching buys little; the browser's
# hashlib has no pbkdf2_hmac, and the pure-Python fallback below must stay quick there.
ITERATIONS = 5_000
NONCE = 16
TAG = 32


class ArchiveError(ValueError):
    pass


def _pbkdf2(secret: bytes, salt: bytes, iterations: int, length: int) -> bytes:
    """PBKDF2-HMAC-SHA256 from hmac alone (RFC 8018), for builds without pbkdf2_hmac."""
    out = b""
    block = 1
    while len(out) < length:
        u = hmac.new(secret, salt + block.to_bytes(4, "big"), hashlib.sha256).digest()
        acc = int.from_bytes(u, "big")
        for _ in range(iterations - 1):
            u = hmac.new(secret, u, hashlib.sha256).digest()
            acc ^= int.from_bytes(u, "big")
        out += acc.to_bytes(32, "big")
        block += 1
    return out[:length]


def derive(secret: str, salt: bytes) -> tuple[bytes, bytes]:
    """(encryption key, MAC key) from the PuntersEdge key."""
    fast = getattr(hashlib, "pbkdf2_hmac", None)
    if fast is not None:
        key = fast("sha256", secret.encode(), salt, ITERATIONS, dklen=64)
    else:
        key = _pbkdf2(secret.encode(), salt, ITERATIONS, 64)
    return key[:32], key[32:]


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    blocks = (length + 31) // 32
    return b"".join(
        hashlib.sha256(key + nonce + i.to_bytes(8, "big")).digest() for i in range(blocks)
    )[:length]


def _xor(data: bytes, stream: bytes) -> bytes:
    return (int.from_bytes(data, "big") ^ int.from_bytes(stream, "big")).to_bytes(len(data), "big")


def seal(plain: bytes, keys: tuple[bytes, bytes], nonce: bytes | None = None) -> bytes:
    enc, mac = keys
    nonce = nonce or os.urandom(NONCE)
    body = _xor(plain, _keystream(enc, nonce, len(plain)))
    return nonce + body + hmac.new(mac, nonce + body, hashlib.sha256).digest()


def unseal(blob: bytes, keys: tuple[bytes, bytes]) -> bytes:
    enc, mac = keys
    if len(blob) < NONCE + TAG:
        raise ArchiveError("damaged file")
    nonce, body, tag = blob[:NONCE], blob[NONCE:-TAG], blob[-TAG:]
    if not hmac.compare_digest(tag, hmac.new(mac, nonce + body, hashlib.sha256).digest()):
        raise ArchiveError("wrong key or damaged file")
    return _xor(body, _keystream(enc, nonce, len(body)))


def slug(venue: str) -> str:
    return "-".join(venue.lower().split())


def check_value(keys: tuple[bytes, bytes]) -> str:
    return hmac.new(keys[1], b"melbcup-archive", hashlib.sha256).hexdigest()[:16]


class Archive:
    """Read side. ``read`` maps a path under the archive root to its text, or None if absent
    (a file read on a server, a same-origin request in the browser)."""

    def __init__(self, read: Callable[[str], str | None], secret: str):
        self._read = read
        self._index: dict[date, list[str]] = {}
        self._keys: tuple[bytes, bytes] | None = None
        raw = read("index.json")
        if raw is None:
            return
        index = json.loads(raw)
        keys = derive(secret, bytes.fromhex(index["salt"]))
        if not hmac.compare_digest(check_value(keys), index["check"]):
            return  # a different PuntersEdge key: the archive stays closed
        self._keys = keys
        self._index = {date.fromisoformat(d): v for d, v in index["meetings"].items()}

    @property
    def open(self) -> bool:
        return self._keys is not None

    def venues(self, day: date) -> list[str]:
        return list(self._index.get(day, []))

    def has(self, day: date, venue: str) -> bool:
        return venue.lower() in (v.lower() for v in self._index.get(day, []))

    def load(self, day: date, venue: str) -> Card:
        if not self.has(day, venue) or self._keys is None:
            raise ArchiveError(f"{venue} on {day} is not saved")
        raw = self._read(f"{day.isoformat()}/{slug(venue)}.bin")
        if raw is None:
            raise ArchiveError(f"{venue} on {day}: file missing")
        return pickle.loads(zlib.decompress(unseal(base64.b64decode(raw), self._keys)))


def write(root: str, cards: list[Card], secret: str) -> None:
    """Build side (tools/build_archive.py): seal every card and write the index."""
    salt = os.urandom(16)
    keys = derive(secret, salt)
    meetings: dict[str, list[str]] = {}
    for card in sorted(cards, key=lambda c: (c.race_date, c.venue)):
        folder = os.path.join(root, card.race_date.isoformat())
        os.makedirs(folder, exist_ok=True)
        blob = seal(zlib.compress(pickle.dumps(card), 9), keys)
        with open(os.path.join(folder, f"{slug(card.venue)}.bin"), "w") as fh:
            fh.write(base64.b64encode(blob).decode())
        meetings.setdefault(card.race_date.isoformat(), []).append(card.venue)
    with open(os.path.join(root, "index.json"), "w") as fh:
        json.dump(
            {"salt": salt.hex(), "check": check_value(keys), "meetings": meetings}, fh, indent=1
        )
