# ruff: noqa: E501
"""Send the push reminders that are due (owner, 2026-11-04: alerts on the phone with the app closed).

The web app keeps one blob per phone in the `nba` container, push/<id>.json:
    {"sub": <the browser's push subscription>, "reminders": [{"at": ISO, "title", "body", "url"}]}
On demand (owner, 2026-11-04): the web app queues each timed reminder on the storage queue
`alerts`, hidden until its time, and the Function's queue trigger calls send_one() the moment it
shows. The props timer's send_due() (every 10 minutes) is the backstop: it sends reminders that
were never queued (LEAD early) and queued ones the queue missed. Each is marked sent once, and
dropped unsent if it is more than LATE minutes old. Each reminder goes to every channel the phone
has: Chrome push (subscription "sub") and Telegram (chat "tg", linked by the web app's
/api/telegram webhook from the bot's "/start <id>" message, melbcup/push_store.py). A channel that refuses (404/410 push, 403 blocked bot) is removed,
and the blob with it once no channel is left.
"""

from __future__ import annotations

import datetime as dt
import json
import re

try:  # the deployed package: copies of melbcup/webpush.py and melbcup/tgbot.py
    import tgbot
    import webpush
except ImportError:  # the repository (tests)
    from melbcup import tgbot, webpush

ID = re.compile(r"^[0-9a-f]{20}$")
LEAD = dt.timedelta(minutes=5)
QUEUE_LEAD = dt.timedelta(minutes=1)  # the queue wakes on time; a minute early is still on time
BACKSTOP = dt.timedelta(minutes=-2)  # queued reminders: the timer sends them only if 2 min late
LATE = dt.timedelta(minutes=30)
MAX_PHONES = 50


def _when(text: str) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None


def _send_doc(
    doc: dict, now, private_key, send, tg_token, tg_send, lead_for
) -> tuple[int, bool, bool]:
    """Send one phone's due reminders. Returns (sent, changed, lost a channel)."""
    sent, changed, lost = 0, False, False
    for r in doc.get("reminders", []):
        at = _when(r.get("at"))
        if r.get("sent") or at is None:
            continue
        if at < now - LATE:
            r["sent"] = "missed"
            changed = True
            continue
        if at > now + lead_for(r):
            continue
        message = {k: r.get(k) for k in ("title", "body", "url")}
        ok = False
        if doc.get("sub") and private_key:
            status = send(doc["sub"], message, private_key)
            ok = status in (200, 201, 202)
            if status in (404, 410):  # Chrome alerts turned off on that phone
                doc.pop("sub")
                changed = lost = True
        if doc.get("tg") and tg_token:
            status = tg_send(tg_token, doc["tg"], message)
            ok = ok or status == 200
            if status == 403:  # the bot was blocked
                doc.pop("tg")
                changed = lost = True
        if ok:
            r["sent"] = now.isoformat()
            sent += 1
            changed = True
    return sent, changed, lost


def _finish(blob, doc: dict, changed: bool, lost: bool) -> int:
    if lost and not doc.get("sub") and not doc.get("tg"):
        blob.delete_blob()  # its last channel said no: no way left to reach that phone
        return 1
    if changed:
        blob.upload_blob(json.dumps(doc).encode(), overwrite=True)
    return 0


def send_one(
    container,
    pid: str,
    now: dt.datetime,
    private_key: str | None,
    send=webpush.send,
    tg_token: str | None = None,
    tg_send=tgbot.send,
) -> tuple[int, int]:
    """The queue's wake-up for one phone (the web app queues each timed reminder to wake at its
    time): send what is due now. Returns (sent, dropped)."""
    if not ID.match(str(pid)):
        return 0, 0
    blob = container.get_blob_client(f"push/{pid}.json")
    try:
        doc = json.loads(blob.download_blob().readall())
    except Exception:  # gone, or not JSON: nothing to send
        return 0, 0
    sent, changed, lost = _send_doc(
        doc, now, private_key, send, tg_token, tg_send, lambda r: QUEUE_LEAD
    )
    return sent, _finish(blob, doc, changed, lost)


def send_due(
    container,
    now: dt.datetime,
    private_key: str | None,
    send=webpush.send,
    tg_token: str | None = None,
    tg_send=tgbot.send,
) -> tuple[int, int]:
    """The timer's sweep. Returns (reminders sent, phones dropped). A reminder the queue will
    wake for is only sent here once it is BACKSTOP late (the queue missed it); others go LEAD early."""
    sent = dropped = 0
    for i, item in enumerate(container.list_blobs(name_starts_with="push/")):
        if i >= MAX_PHONES:
            break
        if item.name.startswith("push/_"):
            continue
        blob = container.get_blob_client(item.name)
        try:
            doc = json.loads(blob.download_blob().readall())
        except (ValueError, KeyError):
            continue
        n, changed, lost = _send_doc(
            doc,
            now,
            private_key,
            send,
            tg_token,
            tg_send,
            lambda r: BACKSTOP if r.get("q") else LEAD,
        )
        sent += n
        dropped += _finish(blob, doc, changed, lost)
    return sent, dropped
