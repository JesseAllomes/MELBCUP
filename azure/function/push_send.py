"""Send the push reminders that are due (owner, 2026-11-04: alerts on the phone with the app closed).

The web app keeps one blob per phone in the `nba` container, push/<id>.json:
    {"sub": <the browser's push subscription>, "reminders": [{"at": ISO, "title", "body", "url"}]}
The props timer calls send_due() every 10 minutes: a reminder goes out once it is due (or due
within the next LEAD minutes, so a "tips off in 15 min" alert is not late), is marked sent, and is
dropped unsent if it is more than LATE minutes old. A phone that turned alerts off (404/410 from
the push service) has its blob removed.
"""

from __future__ import annotations

import datetime as dt
import json

try:
    import webpush  # the deployed package: copied from melbcup/webpush.py
except ImportError:  # the repository (tests)
    from melbcup import webpush

LEAD = dt.timedelta(minutes=5)
LATE = dt.timedelta(minutes=30)
MAX_PHONES = 50


def _when(text: str) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None


def send_due(container, now: dt.datetime, private_key: str, send=webpush.send) -> tuple[int, int]:
    """Returns (reminders sent, phones dropped)."""
    sent = dropped = 0
    for i, item in enumerate(container.list_blobs(name_starts_with="push/")):
        if i >= MAX_PHONES:
            break
        blob = container.get_blob_client(item.name)
        try:
            doc = json.loads(blob.download_blob().readall())
        except (ValueError, KeyError):
            continue
        changed = gone = False
        for r in doc.get("reminders", []):
            at = _when(r.get("at"))
            if r.get("sent") or at is None:
                continue
            if at < now - LATE:
                r["sent"] = "missed"
                changed = True
            elif at <= now + LEAD:
                status = send(doc["sub"], {k: r.get(k) for k in ("title", "body", "url")}, private_key)
                if status in (200, 201, 202):
                    r["sent"] = now.isoformat()
                    sent += 1
                    changed = True
                elif status in (404, 410):
                    gone = True
                    break
        if gone:
            blob.delete_blob()
            dropped += 1
        elif changed:
            blob.upload_blob(json.dumps(doc).encode(), overwrite=True)
    return sent, dropped
