# ruff: noqa: E501
"""Phone alerts, web side (melbcup/push_store.py) and the app's /sw.js and /api/push routes."""

import json
from datetime import UTC, datetime

import pytest

from melbcup.push_store import PushError, PushStore

SUB = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc", "keys": {"p256dh": "P", "auth": "A"}}
NOW = datetime(2026, 11, 4, 23, 0, tzinfo=UTC)


def store():
    blobs = {}
    return PushStore(read=blobs.get, write=blobs.__setitem__), blobs


def test_subscribe_remind_and_never_resend_a_sent_reminder():
    s, blobs = store()
    pid = s.subscribe(SUB)
    assert len(pid) == 20 and s.subscribe(SUB) == pid  # the same phone, the same id
    r = [{"at": "2026-11-04T23:45:00+00:00", "title": "Stage 1 tips off in 15 min", "body": "x"},
         {"at": "2026-11-05T02:30:00Z", "title": "Stage 1 result due"},
         {"at": "2026-12-25T00:00:00Z", "title": "too far"}, {"at": "nonsense"}]
    assert s.remind(pid, r, NOW) == 2
    doc = json.loads(blobs[f"push/{pid}.json"])
    doc["reminders"][0]["sent"] = "2026-11-04T23:40:00+00:00"  # the Function sent it
    blobs[f"push/{pid}.json"] = json.dumps(doc).encode()
    s.remind(pid, r, NOW)  # the page posts the same times again
    again = json.loads(blobs[f"push/{pid}.json"])["reminders"]
    assert again[0]["sent"] and "sent" not in again[1]
    assert s.subscribe(SUB) == pid and json.loads(blobs[f"push/{pid}.json"])["reminders"]  # re-subscribe keeps them


def test_bad_input_is_refused():
    s, _ = store()
    with pytest.raises(PushError):
        s.subscribe({"endpoint": "http://not-https", "keys": {"p256dh": "P", "auth": "A"}})
    with pytest.raises(PushError):
        s.remind("../../etc", [])
    with pytest.raises(PushError):
        s.remind("0" * 20, [])  # no such phone
    pid = s.subscribe(SUB)
    s.test(pid, NOW)
    s.test(pid, NOW)  # one test at a time


def test_routes(monkeypatch):
    from test_asynym import ON, make

    from melbcup import push_store

    blobs = {}
    monkeypatch.setattr(push_store.PushStore.__init__, "__defaults__", (blobs.get, blobs.__setitem__))
    with make(ON) as c:
        sw = c.get("/sw.js")
        assert sw.status_code == 200 and "showNotification" in sw.text
        assert sw.headers["service-worker-allowed"] == "/"
        pid = c.post("/api/push/subscribe", json={"subscription": SUB}).json()["id"]
        assert c.post("/api/push/remind", json={"id": pid, "reminders": []}).json() == {"saved": 0}
        assert c.post("/api/push/test", json={"id": pid}).json() == {"queued": True}
        assert c.post("/api/push/remind", json={"id": "bad", "reminders": []}).status_code == 400
        assert c.post("/api/push/status", json={"id": pid}).json() == {"known": True, "web": True, "telegram": False}
        tid = c.post("/api/push/link").json()["id"]  # Telegram first, Chrome later: one id
        assert c.post("/api/push/status", json={"id": tid}).json() == {"known": True, "web": False, "telegram": False}
        other = {"endpoint": "https://fcm.googleapis.com/fcm/send/xyz", "keys": {"p256dh": "P", "auth": "A"}}
        assert c.post("/api/push/subscribe", json={"subscription": other, "id": tid}).json()["id"] == tid
