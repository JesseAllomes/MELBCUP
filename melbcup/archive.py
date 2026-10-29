"""Meetings already downloaded, kept so opening them again costs no credits.

The site is public, so the meetings are sealed under one random content key, and the index
holds that key locked once per secret (the owner's PuntersEdge key, and a History password the
owner can give friends), each through PBKDF2-HMAC-SHA256. Only a phone holding one of the
secrets can read them, and the providers' data is not republished in the clear. Sealing uses
only hashlib/hmac, which the browser build has: a SHA-256 counter-mode keystream with a random
nonce, then HMAC-SHA256 over nonce and ciphertext.

Layout under the archive root:
    index.json      {"locks": [{"salt", "key"}, ...], "meetings": {"YYYY-MM-DD": [venue, ...]}}
    YYYY-MM-DD/<venue-slug>.bin         base64 of nonce | ciphertext | tag
    history.bin                         the model's record on every saved race, sealed the same way
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


def _open(index: dict, secrets: list[str]) -> tuple[bytes, bytes] | None:
    """The content key, unlocked by the first secret that fits one of the index's locks."""
    for secret in secrets:
        for lock in index.get("locks", []):
            try:
                content = unseal(
                    base64.b64decode(lock["key"]), derive(secret, bytes.fromhex(lock["salt"]))
                )
            except ArchiveError:
                continue
            return content[:32], content[32:]
    return None


class Archive:
    """Read side. ``read`` maps a path under the archive root to its text, or None if absent
    (a file read on a server, a same-origin request in the browser)."""

    def __init__(self, read: Callable[[str], str | None], *secrets: str | None):
        self._read = read
        self._index: dict[date, list[str]] = {}
        self._keys: tuple[bytes, bytes] | None = None
        raw = read("index.json")
        if raw is None:
            return
        index = json.loads(raw)
        self._keys = _open(index, [s for s in secrets if s])
        if self._keys is not None:  # otherwise none of the secrets fits: it stays closed
            self._index = {date.fromisoformat(d): v for d, v in index["meetings"].items()}

    @property
    def open(self) -> bool:
        return self._keys is not None

    def venues(self, day: date) -> list[str]:
        return list(self._index.get(day, []))

    def has(self, day: date, venue: str) -> bool:
        return venue.lower() in (v.lower() for v in self._index.get(day, []))

    def history(self) -> list[dict]:
        """The model's record on every saved race (built when the archive was written)."""
        if self._keys is None:
            return []
        raw = self._read("history.bin")
        if raw is None:
            return []
        try:
            return json.loads(zlib.decompress(unseal(base64.b64decode(raw), self._keys)))
        except (ArchiveError, ValueError, zlib.error):
            return []  # from another build: show the races graded on this phone instead

    def load(self, day: date, venue: str) -> Card:
        if not self.has(day, venue) or self._keys is None:
            raise ArchiveError(f"{venue} on {day} is not saved")
        raw = self._read(f"{day.isoformat()}/{slug(venue)}.bin")
        if raw is None:
            raise ArchiveError(f"{venue} on {day}: file missing")
        return pickle.loads(zlib.decompress(unseal(base64.b64decode(raw), self._keys)))


def write(
    root: str, cards: list[Card], secrets: list[str], history: list[dict] | None = None
) -> None:
    """Build side (tools/build_archive.py): seal every card and the history under a fresh content
    key, and lock that key once per secret in the index."""
    content = os.urandom(64)
    keys = (content[:32], content[32:])
    locks = []
    for secret in secrets:
        salt = os.urandom(16)
        blob = seal(content, derive(secret, salt))
        locks.append({"salt": salt.hex(), "key": base64.b64encode(blob).decode()})
    meetings: dict[str, list[str]] = {}
    for card in sorted(cards, key=lambda c: (c.race_date, c.venue)):
        folder = os.path.join(root, card.race_date.isoformat())
        os.makedirs(folder, exist_ok=True)
        blob = seal(zlib.compress(pickle.dumps(card), 9), keys)
        with open(os.path.join(folder, f"{slug(card.venue)}.bin"), "w") as fh:
            fh.write(base64.b64encode(blob).decode())
        meetings.setdefault(card.race_date.isoformat(), []).append(card.venue)
    if history is not None:
        blob = seal(zlib.compress(json.dumps(history).encode(), 9), keys)
        with open(os.path.join(root, "history.bin"), "w") as fh:
            fh.write(base64.b64encode(blob).decode())
    with open(os.path.join(root, "index.json"), "w") as fh:
        json.dump({"locks": locks, "meetings": meetings}, fh, indent=1)
