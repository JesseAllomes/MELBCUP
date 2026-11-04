# ruff: noqa: E501
"""Web Push (melbcup/webpush.py): the RFC 8291 worked example, and a VAPID token that verifies."""

import base64
import json

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from melbcup import webpush as W


def test_encrypt_matches_rfc_8291_appendix_a():
    server = ec.derive_private_key(int.from_bytes(W.unb64u("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"), "big"), ec.SECP256R1())
    body = W.encrypt(
        b"When I grow up, I want to be a watermelon",
        "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
        "BTBZMqHH6r4Tts7J_aSIgg",
        salt=W.unb64u("DGv6ra1nlYgDCS1FRnbzlw"),
        server_key=server,
    )
    assert W.b64u(body) == (
        "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_"
        "yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN"
    )


def test_vapid_token_verifies_with_the_public_key():
    private, public = W.new_keys()
    header = W.vapid_header("https://fcm.googleapis.com/fcm/send/abc", private, now=1_000_000)
    token = header.split("t=")[1].split(",")[0]
    assert header.endswith(f"k={public}")
    head, body, sig = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(body + "=="))
    assert claims == {"aud": "https://fcm.googleapis.com", "exp": 1_000_000 + 12 * 3600, "sub": W.SUBJECT}
    raw = W.unb64u(sig)
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), W.unb64u(public))
    key.verify(der, f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256()))  # raises if wrong
