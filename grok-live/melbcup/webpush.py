"""Web Push without extra packages: VAPID (RFC 8292) and aes128gcm payloads (RFC 8291).

Only `cryptography` is needed, which the Azure Function already carries (azure-identity uses it).
The web app stores each phone's subscription; the Function's timer sends the reminders that fall
due with send(). A subscription is what the browser's pushManager.subscribe() returns:
{"endpoint": ..., "keys": {"p256dh": ..., "auth": ...}}.
"""

from __future__ import annotations

import base64
import json
import os
import struct
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

SUBJECT = "https://bet.asynym.dev"  # who sends: the site (no email address needed)
TIMEOUT_S = 10


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def new_keys() -> tuple[str, str]:
    """(private key, public key), base64url: the private 32-byte scalar and the 65-byte point."""
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_numbers().private_value.to_bytes(32, "big")
    return b64u(private), public_of(b64u(private))


def _private(private_b64: str) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(int.from_bytes(unb64u(private_b64), "big"), ec.SECP256R1())


def public_of(private_b64: str) -> str:
    point = (
        _private(private_b64)
        .public_key()
        .public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    )
    return b64u(point)


def vapid_header(endpoint: str, private_b64: str, now: float | None = None) -> str:
    """The Authorization header: a 12-hour ES256 token for the push service's origin."""
    parts = urlsplit(endpoint)
    claims = {
        "aud": f"{parts.scheme}://{parts.netloc}",
        "exp": int((now or time.time()) + 12 * 3600),
        "sub": SUBJECT,
    }
    head = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    body = b64u(json.dumps(claims, separators=(",", ":")).encode())
    der = _private(private_b64).sign(f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    sig = b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={head}.{body}.{sig}, k={public_of(private_b64)}"


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def encrypt(
    payload: bytes,
    p256dh_b64: str,
    auth_b64: str,
    salt: bytes | None = None,
    server_key: ec.EllipticCurvePrivateKey | None = None,
) -> bytes:
    """aes128gcm body for one subscription (RFC 8291), a single record."""
    ua_public = unb64u(p256dh_b64)
    auth = unb64u(auth_b64)
    salt = salt or os.urandom(16)
    server_key = server_key or ec.generate_private_key(ec.SECP256R1())
    as_public = server_key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    shared = server_key.exchange(
        ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    )
    ikm = _hkdf(auth, shared, b"WebPush: info\x00" + ua_public + as_public, 32)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    record = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)  # \x02: the last (only) record
    header = salt + struct.pack("!IB", 4096, len(as_public)) + as_public
    return header + record


def send(subscription: dict, message: dict, private_b64: str, ttl: int = 3600) -> int:
    """Push one message ({"title", "body", "url"}). Returns the HTTP status: 201 sent, 404/410 the
    subscription is gone (the phone turned alerts off), anything else a temporary failure."""
    endpoint = subscription["endpoint"]
    keys = subscription["keys"]
    body = encrypt(json.dumps(message).encode(), keys["p256dh"], keys["auth"])
    req = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": vapid_header(endpoint, private_b64),
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "TTL": str(ttl),
            "Urgency": "high",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0
