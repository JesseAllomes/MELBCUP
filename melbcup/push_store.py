"""Phone alerts, the web side (owner, 2026-11-04): keep each phone's push subscription and its
reminders in the Blob container `nba` (push/<id>.json); the Azure Function's timer sends them
(azure/function/push_send.py). The id is a hash of the phone's push endpoint, kept on the phone.

Reminders come from the page (the Challenge tab's next tip-off and result-due times). Writing
them again never re-sends one: a reminder already sent keeps its mark.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx

from melbcup.nba_feed import TIMEOUT_S, _token, blob_reader

ID = re.compile(r"^[0-9a-f]{20}$")
MAX_REMINDERS = 10


class PushError(ValueError):
    pass


def blob_writer(account: str, client_id: str | None) -> Callable[[str, bytes], None]:
    def write(name: str, data: bytes) -> None:
        resp = httpx.put(
            f"https://{account}.blob.core.windows.net/nba/{name}",
            content=data,
            headers={
                "Authorization": f"Bearer {_token(client_id)}",
                "x-ms-version": "2021-08-06",
                "x-ms-blob-type": "BlockBlob",
                "Content-Type": "application/json",
            },
            timeout=TIMEOUT_S,
        )
        resp.raise_for_status()

    return write


class PushStore:
    def __init__(self, read=None, write=None):
        if read is None and os.environ.get("NBA_ACCOUNT"):
            account, client = os.environ["NBA_ACCOUNT"], os.environ.get("AZURE_CLIENT_ID")
            read, write = blob_reader(account, client), blob_writer(account, client)
        self.read, self.write = read, write

    @property
    def ready(self) -> bool:
        return self.read is not None and self.write is not None

    def _load(self, pid: str) -> dict | None:
        raw = self.read(f"push/{pid}.json")
        return json.loads(raw) if raw else None

    def _save(self, pid: str, doc: dict) -> None:
        self.write(f"push/{pid}.json", json.dumps(doc).encode())

    def subscribe(self, sub: dict) -> str:
        endpoint = str((sub or {}).get("endpoint") or "")
        keys = (sub or {}).get("keys") or {}
        if not endpoint.startswith("https://") or not keys.get("p256dh") or not keys.get("auth"):
            raise PushError("not a push subscription")
        pid = hashlib.sha256(endpoint.encode()).hexdigest()[:20]
        old = self._load(pid) or {}
        clean = {
            "endpoint": endpoint,
            "keys": {"p256dh": str(keys["p256dh"]), "auth": str(keys["auth"])},
        }
        self._save(pid, {"sub": clean, "reminders": old.get("reminders", [])})
        return pid

    def remind(self, pid: str, reminders: list, now: datetime | None = None) -> int:
        if not ID.match(str(pid)):
            raise PushError("bad id")
        doc = self._load(pid)
        if doc is None:
            raise PushError("this phone has no alerts on")
        now = now or datetime.now(UTC)
        sent = {(r.get("at"), r.get("title")): r.get("sent") for r in doc.get("reminders", [])}
        out = []
        for r in (reminders or [])[:MAX_REMINDERS]:
            try:
                at = datetime.fromisoformat(str(r["at"]).replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue
            if at.tzinfo is None or not (now - timedelta(hours=1) <= at <= now + timedelta(days=8)):
                continue
            url = str(r.get("url") or "/nba?tab=challenge")
            item = {
                "at": at.isoformat(),
                "title": str(r.get("title") or "AsynymBet")[:80],
                "body": str(r.get("body") or "")[:140],
                "url": url if url.startswith("/") else "/",
            }
            if sent.get((item["at"], item["title"])):
                item["sent"] = sent[(item["at"], item["title"])]
            out.append(item)
        doc["reminders"] = out
        self._save(pid, doc)
        return len(out)

    def test(self, pid: str, now: datetime | None = None) -> None:
        if not ID.match(str(pid)):
            raise PushError("bad id")
        doc = self._load(pid)
        if doc is None:
            raise PushError("this phone has no alerts on")
        now = now or datetime.now(UTC)
        doc["reminders"] = [
            r for r in doc.get("reminders", []) if r.get("title") != "AsynymBet test"
        ]
        doc["reminders"].append(
            {
                "at": now.isoformat(),
                "title": "AsynymBet test",
                "body": "Alerts work: stage reminders will show up like this.",
                "url": "/nba?tab=challenge",
            }
        )
        self._save(pid, doc)
