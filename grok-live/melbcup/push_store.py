"""Phone alerts, the web side (owner, 2026-11-04): keep each phone's push subscription and its
reminders in the Blob container `nba` (push/<id>.json); the Azure Function's timer sends them
(azure/function/push_send.py). The id is a hash of the phone's push endpoint, kept on the phone.

Reminders come from the page (the Challenge tab's next tip-off and result-due times). Writing
them again never re-sends one: a reminder already sent keeps its mark.

Instant (owner, 2026-11-04: "just make it instant"): with VAPID_PRIVATE_KEY and TELEGRAM_BOT_TOKEN
set, a test goes out from here at once, and Telegram's webhook (/api/telegram) links a chat the
moment Start is pressed. The Function's timer sends only the timed reminders.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx

from melbcup import tgbot
from melbcup.nba_feed import TIMEOUT_S, _token, blob_reader

ID = re.compile(r"^[0-9a-f]{20}$")
MAX_REMINDERS = 10
QUEUE = "alerts"  # storage queue: each timed reminder wakes the Function's alerts_due at its time
QUEUE_MAX_PER_DAY = 40  # azure/limits.json alerts_due.queue_max_per_day (the cost guard's count)
MAX_DELAY_S = 7 * 86400 - 60  # a queue message can stay hidden at most 7 days
CHATS = "push/_chats.json"  # Telegram chat -> phone id, for /stop
TEST = {
    "title": "AsynymBet test",
    "body": "Alerts work: stage reminders will show up like this.",
    "url": "/nba?tab=challenge",
}


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


def queue_sender(account: str, client_id: str | None) -> Callable[[dict, int], None]:
    """Put a message on the storage queue `alerts`, hidden for `delay_s` seconds."""

    def put(message: dict, delay_s: int) -> None:
        text = base64.b64encode(json.dumps(message).encode()).decode()
        resp = httpx.post(
            f"https://{account}.queue.core.windows.net/{QUEUE}/messages",
            params={"visibilitytimeout": delay_s, "messagettl": delay_s + 86400},
            content=f"<QueueMessage><MessageText>{text}</MessageText></QueueMessage>",
            headers={
                "Authorization": f"Bearer {_token(client_id)}",
                "x-ms-version": "2021-08-06",
                "Content-Type": "application/xml",
            },
            timeout=TIMEOUT_S,
        )
        resp.raise_for_status()

    return put


class PushStore:
    def __init__(
        self,
        read=None,
        write=None,
        private_key: str | None = None,
        tg_token: str | None = None,
        send_web=None,
        tg_api=tgbot.call,
        enqueue=None,
    ):
        if read is None and os.environ.get("NBA_ACCOUNT"):
            account, client = os.environ["NBA_ACCOUNT"], os.environ.get("AZURE_CLIENT_ID")
            read, write = blob_reader(account, client), blob_writer(account, client)
            enqueue = enqueue or queue_sender(account, client)
        self.read, self.write, self.enqueue = read, write, enqueue
        self.private_key = private_key or os.environ.get("VAPID_PRIVATE_KEY")
        self.tg_token = tg_token or os.environ.get("TELEGRAM_BOT_TOKEN")
        self.send_web, self.tg_api = send_web, tg_api

    @property
    def ready(self) -> bool:
        return self.read is not None and self.write is not None

    def _load(self, pid: str) -> dict | None:
        raw = self.read(f"push/{pid}.json")
        return json.loads(raw) if raw else None

    def _save(self, pid: str, doc: dict) -> None:
        self.write(f"push/{pid}.json", json.dumps(doc).encode())

    def link(self) -> str:
        """A new id for a phone that wants Telegram alerts before (or without) Chrome alerts."""
        pid = secrets.token_hex(10)
        self._save(pid, {"reminders": []})
        return pid

    def subscribe(self, sub: dict, pid: str | None = None) -> str:
        """Keep the phone's Chrome push subscription: on its existing id (Telegram linked first)
        or on one made from the push endpoint."""
        endpoint = str((sub or {}).get("endpoint") or "")
        keys = (sub or {}).get("keys") or {}
        if not endpoint.startswith("https://") or not keys.get("p256dh") or not keys.get("auth"):
            raise PushError("not a push subscription")
        old = self._load(pid) if pid and ID.match(str(pid)) else None
        if old is None:
            pid = hashlib.sha256(endpoint.encode()).hexdigest()[:20]
            old = self._load(pid) or {}
        clean = {
            "endpoint": endpoint,
            "keys": {"p256dh": str(keys["p256dh"]), "auth": str(keys["auth"])},
        }
        self._save(pid, old | {"sub": clean, "reminders": old.get("reminders", [])})
        return pid

    def status(self, pid: str) -> dict:
        doc = self._load(pid) if ID.match(str(pid or "")) else None
        return {
            "known": doc is not None,
            "web": bool((doc or {}).get("sub")),
            "telegram": bool((doc or {}).get("tg")),
        }

    def remind(self, pid: str, reminders: list, now: datetime | None = None) -> int:
        if not ID.match(str(pid)):
            raise PushError("bad id")
        doc = self._load(pid)
        if doc is None:
            raise PushError("this phone has no alerts on")
        now = now or datetime.now(UTC)
        sent = {(r.get("at"), r.get("title")): r.get("sent") for r in doc.get("reminders", [])}
        queued = {(r.get("at"), r.get("title")) for r in doc.get("reminders", []) if r.get("q")}
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
            if (item["at"], item["title"]) in queued:
                item["q"] = True
            out.append(item)
        doc["reminders"] = out
        self._queue(pid, out, now)
        self._save(pid, doc)
        return len(out)

    def _queue(self, pid: str, reminders: list[dict], now: datetime) -> None:
        """Wake the Function at each new reminder's time (marked "q"). Anything not queued (no
        queue here, over 7 days out, the day's cap used, the queue down) is sent by its timer."""
        if self.enqueue is None:
            return
        for r in reminders:
            if r.get("sent") or r.get("q"):
                continue
            delay = int((datetime.fromisoformat(r["at"]) - now).total_seconds())
            if delay > MAX_DELAY_S or not self._take_slot(now):
                continue
            try:
                self.enqueue({"id": pid}, max(0, delay))
            except httpx.HTTPError:
                return
            r["q"] = True

    def _take_slot(self, now: datetime) -> bool:
        """At most QUEUE_MAX_PER_DAY queued alerts a day across every phone (the cost cap)."""
        name = f"push/_q-{now:%Y%m%d}.json"
        raw = self.read(name)
        used = json.loads(raw).get("n", 0) if raw else 0
        if used >= QUEUE_MAX_PER_DAY:
            return False
        self.write(name, json.dumps({"n": used + 1}).encode())
        return True

    def _web_sender(self):
        """Chrome push needs `cryptography`, which the web image may not have: then the Function
        (which has it) sends Chrome alerts, woken through the queue."""
        if self.send_web is None:
            try:
                from melbcup import webpush
            except ImportError:
                return None
            self.send_web = webpush.send
        return self.send_web

    def send_now(self, pid: str, message: dict) -> list[str]:
        """Send one alert at once to every channel the phone has; returns the channels that took
        it. A channel that refuses for good (push 404/410, bot blocked) is removed."""
        if not ID.match(str(pid)):
            raise PushError("bad id")
        doc = self._load(pid)
        if doc is None:
            raise PushError("this phone has no alerts on")
        took, changed = [], False
        if doc.get("sub") and self.private_key and self._web_sender():
            status = self.send_web(doc["sub"], message, self.private_key)
            if status in (200, 201, 202):
                took.append("chrome")
            elif status in (404, 410):
                doc.pop("sub")
                changed = True
        if doc.get("tg") and self.tg_token:
            status = tgbot.send(self.tg_token, doc["tg"], message, self.tg_api)
            if status == 200:
                took.append("telegram")
            elif status == 403:
                doc.pop("tg")
                changed = True
        if changed:
            self._save(pid, doc)
        return took

    def test(self, pid: str, now: datetime | None = None) -> dict:
        """Send the test now when this app can reach every channel the phone has; otherwise the
        queue wakes the Function to send it (seconds)."""
        if not ID.match(str(pid)):
            raise PushError("bad id")
        doc = self._load(pid)
        if doc is None:
            raise PushError("this phone has no alerts on")
        web_ok = not doc.get("sub") or (self.private_key and self._web_sender())
        tg_ok = not doc.get("tg") or self.tg_token
        if web_ok and tg_ok and (doc.get("sub") or doc.get("tg")):
            took = self.send_now(pid, TEST)
            if not took:
                raise PushError("no channel took the test: turn alerts on again")
            return {"sent": took}
        now = now or datetime.now(UTC)
        doc["reminders"] = [r for r in doc.get("reminders", []) if r.get("title") != TEST["title"]]
        doc["reminders"].append({"at": now.isoformat()} | TEST)
        self._queue(pid, doc["reminders"], now)
        self._save(pid, doc)
        return {"queued": True}

    def telegram(self, update: dict) -> str:
        """One message to @AsynymBetBot (Telegram's webhook): "/start <id>" links that chat to the
        phone's alerts, "/stop" unlinks it. Returns what was done, for the log."""
        msg = (update or {}).get("message") or {}
        text, chat = (msg.get("text") or "").strip(), (msg.get("chat") or {}).get("id")
        if not chat or not self.tg_token:
            return "ignored"
        parts = text.split()
        say = lambda t: tgbot.say(self.tg_token, chat, t, self.tg_api)  # noqa: E731
        raw = self.read(CHATS)
        chats = json.loads(raw) if raw else {}
        if parts[:1] == ["/start"] and len(parts) == 2 and ID.match(parts[1]):
            doc = self._load(parts[1])
            if doc is None:
                say("That link has expired: tap Telegram alerts in Settings again.")
                return "expired"
            self._save(parts[1], doc | {"tg": chat})
            self.write(CHATS, json.dumps(chats | {str(chat): parts[1]}).encode())
            say("Linked ✓ AsynymBet alerts will arrive here. Send /stop to turn them off.")
            return "linked"
        if parts[:1] == ["/stop"]:
            pid = chats.pop(str(chat), None)
            doc = self._load(pid) if pid else None
            if doc is not None and doc.get("tg") == chat:
                doc.pop("tg")
                self._save(pid, doc)
            self.write(CHATS, json.dumps(chats).encode())
            say("Alerts off. Tap Telegram alerts in Settings to turn them back on.")
            return "stopped"
        say("Open bet.asynym.dev, tap Settings, then Telegram alerts to link this chat.")
        return "help"
