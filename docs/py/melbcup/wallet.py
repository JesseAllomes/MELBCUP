# ruff: noqa: E501
"""Bonus wallet (owner, 2026-11-07): provider-scoped bonus credits that are NOT cash.

An append-only ledger; every balance is computed from it. The app never moves money: the owner
records what the provider actually gave and allowed. Entries (`t`):
  grant    amount, provider, expiry (ISO date or ""), note     -> a new credit `c<n>`
  split    credit, parts [amounts]                             -> children `<id>.<n>`; the parts are
           the provider's permitted split as the owner typed it and must add up to the credit
  allocate credit, challenge                                   -> reserved for one challenge
  release  credit                                              -> the reservation ends (explicit)
  redeem   credit                                              -> used
  expire   credit                                              -> lapsed (also implied once the
           expiry date has passed)
An entry may carry `op`: re-appending an op already in the ledger does nothing.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

MELBOURNE = ZoneInfo("Australia/Melbourne")

MAX_CHILDREN = 10  # the provider interface the owner observed (pack: PROMOTIONS)
KINDS = ("grant", "split", "allocate", "release", "redeem", "expire")


class WalletError(ValueError):
    pass


def _amount(v) -> float:
    try:
        x = round(float(str(v).replace("$", "").replace(",", "")), 2)
    except (TypeError, ValueError):
        raise WalletError("amount must be a number") from None
    if not 0 < x < 1_000_000:
        raise WalletError("amount must be above 0")
    return x


def credits(ledger: list[dict], today: str = "") -> dict[str, dict]:
    """Replay the ledger: {credit id: {id, provider, amount, expiry, note, parent, status,
    challenge}}. status: open | split | redeemed | expired; challenge is who holds it, or None."""
    out: dict[str, dict] = {}
    n = 0
    for e in ledger:
        t, cid = e["t"], e.get("credit")
        if t == "grant":
            n += 1
            out[f"c{n}"] = {
                "id": f"c{n}",
                "provider": e["provider"],
                "amount": e["amount"],
                "expiry": e.get("expiry", ""),
                "note": e.get("note", ""),
                "parent": None,
                "status": "available",
                "challenge": None,
                "plans": e.get("plans") or [],
            }
            continue
        c = out.get(cid)
        if c is None:
            continue
        if t == "split":
            c["status"] = "split"
            for i, amt in enumerate(e["parts"], 1):
                out[f"{cid}.{i}"] = c | {
                    "id": f"{cid}.{i}",
                    "amount": amt,
                    "parent": cid,
                    "status": "available",
                    "challenge": None,
                    "plans": [],
                }
        elif t == "allocate":
            c["challenge"] = e["challenge"]
        elif t == "release":
            c["challenge"] = None
        elif t == "redeem":
            c["status"] = "redeemed"
        elif t == "expire":
            c["status"] = "expired"
    if today:
        for c in out.values():
            if c["status"] == "available" and c["expiry"] and c["expiry"] < today:
                c["status"] = "expired"
    for c in out.values():  # the contract's field names (pack: bonus_token.schema.json)
        c["bookmaker"], c["face_cents"] = c["provider"], round(c["amount"] * 100)
        # a date the owner typed is a Melbourne day: it lapses at the end of it (UTC inside)
        c["expires_at_utc"] = (
            datetime.combine(date.fromisoformat(c["expiry"]), time(23, 59, 59), MELBOURNE)
            .astimezone(UTC)
            .isoformat()
            .replace("+00:00", "Z")
            if c["expiry"]
            else ""
        )
        c["parent_token_id"], c["reserved_challenge_id"] = c["parent"], c["challenge"]
        if c["status"] == "available" and c["challenge"]:
            c["status"] = "reserved"
    return out


def balances(ledger: list[dict], today: str = "") -> dict[str, dict]:
    """Per provider: {"open": total of usable credits, "held": the part allocated to challenges}.
    Bonus value, never cash."""
    out: dict[str, dict] = {}
    for c in credits(ledger, today).values():
        if c["status"] not in ("available", "reserved"):
            continue
        b = out.setdefault(c["provider"], {"open": 0.0, "held": 0.0})
        b["open"] = round(b["open"] + c["amount"], 2)
        if c["challenge"]:
            b["held"] = round(b["held"] + c["amount"], 2)
    return out


def append(ledger: list[dict], entry: dict, today: str = "") -> list[dict]:
    """A new ledger with `entry` added after checking it against the current credits. Raises
    WalletError when it is not allowed (double allocation, splitting a used credit...)."""
    if entry.get("t") not in KINDS:
        raise WalletError("unknown entry")
    op = entry.get("op")
    if op and any(e.get("op") == op for e in ledger):
        return ledger  # the same submission again: nothing
    cs = credits(ledger, today)
    t, cid = entry["t"], entry.get("credit")
    if t == "grant":
        provider = str(entry.get("provider") or "").strip()[:40]
        if not provider:
            raise WalletError("provider needed")
        expiry = str(entry.get("expiry") or "")
        if expiry:
            try:
                date.fromisoformat(expiry)
            except ValueError:
                raise WalletError("expiry must be a date") from None
        new = {
            "t": "grant",
            "amount": _amount(entry.get("amount")),
            "provider": provider,
            "expiry": expiry,
            "note": str(entry.get("note") or "")[:200],
        }
        if entry.get(
            "plans"
        ):  # the splits the provider showed for this credit, if the owner typed them
            new["plans"] = [[_amount(a) for a in p] for p in entry["plans"]]
    else:
        c = cs.get(cid)
        if c is None:
            raise WalletError("no such credit")
        if c["status"] not in ("available", "reserved"):
            raise WalletError(f"credit is {c['status']}")
        new = {"t": t, "credit": cid}
        if t == "split":
            parts = [_amount(p) for p in entry.get("parts") or []]
            if len(parts) < 2:
                raise WalletError("a split needs at least two parts")
            if c["challenge"]:
                raise WalletError("release it from its challenge first")
            if round(sum(parts), 2) != c["amount"]:
                raise WalletError("the parts must add up to the credit")
            if len(parts) > MAX_CHILDREN:
                raise WalletError(f"at most {MAX_CHILDREN} parts")
            if c["plans"] and sorted(parts) not in [sorted(p) for p in c["plans"]]:
                raise WalletError("not one of the splits the provider offered for this credit")
            new["parts"] = parts
        elif t == "allocate":
            if c["challenge"]:
                raise WalletError("already allocated")
            if not entry.get("challenge"):
                raise WalletError("challenge needed")
            new["challenge"] = str(entry["challenge"])
        elif t == "release" and not c["challenge"]:
            raise WalletError("not allocated")
        elif (
            t == "redeem"
            and entry.get("challenge")
            and c["challenge"] not in (None, entry["challenge"])
        ):
            raise WalletError("allocated to another challenge")
    if op:
        new["op"] = op
    if entry.get("at"):
        new["at"] = entry["at"]
    return [*ledger, new]
