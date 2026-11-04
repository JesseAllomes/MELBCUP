# ruff: noqa: E501
"""Send the push reminders that are due (owner, 2026-11-04: alerts on the phone with the app closed).

The web app keeps one blob per phone in the `nba` container, push/<id>.json:
    {"sub": <the browser's push subscription>, "reminders": [{"at": ISO, "title", "body", "url"}]}
The props timer calls send_due() every 10 minutes: a reminder goes out once it is due (or due
within the next LEAD minutes, so a "tips off in 15 min" alert is not late), is marked sent, and is
dropped unsent if it is more than LATE minutes old. Each reminder goes to every channel the phone
has: Chrome push (subscription "sub") and Telegram (chat "tg", linked by link_telegram from the
bot's "/start <id>" message). A channel that refuses (404/410 push, 403 blocked bot) is removed,
and the blob with it once no channel is left.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import urllib.error
import urllib.parse
import urllib.request

try:
    import webpush  # the deployed package: copied from melbcup/webpush.py
except ImportError:  # the repository (tests)
    from melbcup import webpush

SITE = "https://bet.asynym.dev"
ID = re.compile(r"^[0-9a-f]{20}$")
TG = "https://api.telegram.org/bot{token}/{method}"
TIMEOUT_S = 10
LEAD = dt.timedelta(minutes=5)
LATE = dt.timedelta(minutes=30)
MAX_PHONES = 50


def _when(text: str) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None


def telegram(token: str, method: str, params: dict) -> dict:
    """One Bot API call; {} when Telegram does not answer. 403 (bot blocked) comes back as ok False."""
    url = TG.format(token=token, method=method)
    data = urllib.parse.urlencode(params).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=TIMEOUT_S) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read()) | {"status": exc.code}
        except ValueError:
            return {"ok": False, "status": exc.code}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return {}


def telegram_send(token: str, chat: int, message: dict) -> int:
    """Send one reminder; returns 200 when Telegram took it, 403 when the owner blocked the bot."""
    text = f"{message.get('title') or 'AsynymBet'}\n{message.get('body') or ''}\n{SITE}{message.get('url') or '/nba?tab=challenge'}"
    r = telegram(
        token,
        "sendMessage",
        {"chat_id": chat, "text": text.strip(), "disable_web_page_preview": "true"},
    )
    return 200 if r.get("ok") else int(r.get("status") or 0)


def link_telegram(container, token: str, call=telegram) -> int:
    """Read the bot's new messages: "/start <id>" (from the page's Telegram button) links that chat
    to the phone's alerts; "/stop" unlinks it. Returns the chats linked or unlinked."""
    state = container.get_blob_client("push/_telegram.json")
    try:
        offset = json.loads(state.download_blob().readall()).get("offset", 0)
    except Exception:  # first run
        offset = 0
    updates = (call(token, "getUpdates", {"offset": offset, "timeout": 0}) or {}).get(
        "result"
    ) or []
    changed = 0
    for u in updates:
        offset = max(offset, u["update_id"] + 1)
        msg = u.get("message") or {}
        text, chat = (msg.get("text") or "").strip(), (msg.get("chat") or {}).get("id")
        if not chat:
            continue
        parts = text.split()
        if parts[:1] == ["/start"] and len(parts) == 2 and ID.match(parts[1]):
            blob = container.get_blob_client(f"push/{parts[1]}.json")
            try:
                doc = json.loads(blob.download_blob().readall())
            except Exception:
                call(
                    token,
                    "sendMessage",
                    {
                        "chat_id": chat,
                        "text": "That link has expired: tap Get alerts on Telegram again on the Challenge tab.",
                    },
                )
                continue
            blob.upload_blob(json.dumps(doc | {"tg": chat}).encode(), overwrite=True)
            call(
                token,
                "sendMessage",
                {
                    "chat_id": chat,
                    "text": "Linked ✓ Challenge stage alerts will arrive here. Send /stop to turn them off.",
                },
            )
            changed += 1
        elif parts[:1] == ["/stop"]:
            for item in container.list_blobs(name_starts_with="push/"):
                if item.name.startswith("push/_"):
                    continue
                blob = container.get_blob_client(item.name)
                doc = json.loads(blob.download_blob().readall())
                if doc.get("tg") == chat:
                    doc.pop("tg")
                    blob.upload_blob(json.dumps(doc).encode(), overwrite=True)
                    changed += 1
            call(
                token,
                "sendMessage",
                {
                    "chat_id": chat,
                    "text": "Alerts off. Tap Get alerts on Telegram on the Challenge tab to turn them back on.",
                },
            )
        elif parts[:1] == ["/start"]:
            call(
                token,
                "sendMessage",
                {
                    "chat_id": chat,
                    "text": "Open bet.asynym.dev, NBA, Challenge, and tap Get alerts on Telegram to link this chat.",
                },
            )
    if updates:
        state.upload_blob(json.dumps({"offset": offset}).encode(), overwrite=True)
    return changed


def send_due(
    container,
    now: dt.datetime,
    private_key: str | None,
    send=webpush.send,
    tg_token: str | None = None,
    tg_send=telegram_send,
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
