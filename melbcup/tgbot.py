"""Telegram Bot API calls for the phone alerts (@AsynymBetBot). Standard library only, so the web
app and the Azure Function (which gets a copy of this file) share it."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

SITE = "https://bet.asynym.dev"
API = "https://api.telegram.org/bot{token}/{method}"
TIMEOUT_S = 10


def call(token: str, method: str, params: dict) -> dict:
    """One Bot API call; {} when Telegram does not answer; 403 (bot blocked) is ok False."""
    url = API.format(token=token, method=method)
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


def say(token: str, chat: int, text: str, api=call) -> dict:
    return api(
        token, "sendMessage", {"chat_id": chat, "text": text, "disable_web_page_preview": "true"}
    )


def send(token: str, chat: int, message: dict, api=call) -> int:
    """Send one alert; 200 when Telegram took it, 403 when the bot was blocked."""
    title = message.get("title") or "AsynymBet"
    url = SITE + (message.get("url") or "/nba?tab=challenge")
    text = f"{title}\n{message.get('body') or ''}\n{url}".replace("\n\n", "\n")
    r = say(token, chat, text.strip(), api)
    return 200 if r.get("ok") else int(r.get("status") or 0)
