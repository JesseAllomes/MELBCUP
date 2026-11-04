# ruff: noqa: E501
"""Push reminders sent by the props timer (azure/function/push_send.py)."""

import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "azure" / "function"))
import push_send  # noqa: E402


class Item:
    def __init__(self, name):
        self.name = name


class Blob:
    def __init__(self, store, key):
        self.store, self.key = store, key

    def download_blob(self):
        data = self.store[self.key]
        return type("R", (), {"readall": lambda _s: data})()

    def upload_blob(self, data, overwrite=False):
        self.store[self.key] = data

    def delete_blob(self):
        del self.store[self.key]


class Container:
    def __init__(self, store):
        self.store = store

    def list_blobs(self, name_starts_with=""):
        return [Item(k) for k in sorted(self.store) if k.startswith(name_starts_with)]

    def get_blob_client(self, key):
        return Blob(self.store, key)


NOW = dt.datetime(2026, 11, 5, 0, 0, tzinfo=dt.UTC)


def phone(endpoint, *reminders):
    return json.dumps({"sub": {"endpoint": endpoint, "keys": {}}, "reminders": list(reminders)}).encode()


def test_due_reminders_go_once_stale_ones_drop_and_gone_phones_are_removed():
    store = {
        "push/a": phone("https://push/a",
                        {"at": "2026-11-05T00:03:00+00:00", "title": "Stage 2 tips off", "body": "15 min", "url": "/nba"},
                        {"at": "2026-11-05T02:30:00+00:00", "title": "Stage 2 result due"},
                        {"at": "2026-11-04T23:00:00+00:00", "title": "old"}),
        "push/b": phone("https://push/b", {"at": "2026-11-04T23:55:00+00:00", "title": "x"}),
        "other/c": b"{}",
    }
    calls = []

    def send(sub, msg, key):
        calls.append((sub["endpoint"], msg["title"], key))
        return 410 if sub["endpoint"].endswith("/b") else 201

    sent, dropped = push_send.send_due(Container(store), NOW, "KEY", send)
    assert (sent, dropped) == (1, 1)
    assert calls == [("https://push/a", "Stage 2 tips off", "KEY"), ("https://push/b", "x", "KEY")]
    a = json.loads(store["push/a"])["reminders"]
    assert a[0]["sent"] and not a[1].get("sent") and a[2]["sent"] == "missed"
    assert "push/b" not in store  # the phone turned alerts off
    calls.clear()
    assert push_send.send_due(Container(store), NOW, "KEY", send) == (0, 0) and calls == []  # nothing twice
