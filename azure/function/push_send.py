# ruff: noqa: E501
"""Send the push reminders that are due (owner, 2026-11-04: alerts on the phone with the app closed).

The web app keeps one blob per phone in the `nba` container, push/<id>.json:
    {"sub": <the browser's push subscription>, "reminders": [{"at": ISO, "title", "body", "url"}]}
The props timer calls send_due() every 10 minutes: a reminder goes out once it is due (or due
within the next LEAD minutes, so a "tips off in 15 min" alert is not late), is marked sent, and is
dropped unsent if it is more than LATE minutes old. Each reminder goes to every channel the phone
has: Chrome push (subscription "sub") and Telegram (chat "tg", linked by the web app's
/api/telegram webhook from the bot's "/start <id>" message, melbcup/push_store.py). A channel that refuses (404/410 push, 403 blocked bot) is removed,
and the blob with it once no channel is left.
"""

from __future__ import annotations

import datetime as dt
import json

try:  # the deployed package: copies of melbcup/webpush.py and melbcup/tgbot.py
    import tgbot
    import webpush
except ImportError:  # the repository (tests)
    from melbcup import tgbot, webpush

LEAD = dt.timedelta(minutes=5)
LATE = dt.timedelta(minutes=30)
MAX_PHONES = 50


def _when(text: str) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None


def send_due(
    container,
    now: dt.datetime,
    private_key: str | None,
    send=webpush.send,
    tg_token: str | None = None,
    tg_send=tgbot.send,
) -> tuple[int, int]:
    """Returns (reminders sent, phones dropped). Each reminder goes to every channel the phone has
    (Chrome push, Telegram); it counts as sent when one of them took it."""
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
        changed = lost = False
        for r in doc.get("reminders", []):
            at = _when(r.get("at"))
            if r.get("sent") or at is None:
                continue
            if at < now - LATE:
                r["sent"] = "missed"
                changed = True
                continue
            if at > now + LEAD:
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
        if lost and not doc.get("sub") and not doc.get("tg"):
            blob.delete_blob()  # its last channel said no: no way left to reach that phone
            dropped += 1
        elif changed:
            blob.upload_blob(json.dumps(doc).encode(), overwrite=True)
    return sent, dropped
