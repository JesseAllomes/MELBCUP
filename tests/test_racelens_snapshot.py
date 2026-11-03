"""RaceLens Oaks Day snapshots (azure/function/racelens.py): only changes are written."""

import datetime as dt
import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "azure" / "function"))
import racelens  # noqa: E402


class Blob:
    def __init__(self, store, key):
        self.store, self.key = store, key

    def download_blob(self):
        if self.key not in self.store:
            raise KeyError(self.key)
        data = self.store[self.key]
        return type("R", (), {"readall": lambda _self: data})()

    def upload_blob(self, data, overwrite=False):
        self.store[self.key] = data


class Container:
    def __init__(self):
        self.store = {}

    def get_blob_client(self, key):
        return Blob(self.store, key)


def fake_server(prob):
    pack = {
        "races": [
            {
                "number": 1,
                "startTime": "2026-11-05T00:00:00Z",
                "runners": [{"number": 1, "odds": []}],
            }
        ],
        "predictions": {"1": {"generatedAt": "x", "ranked": [{"number": 1, "winProb": prob}]}},
        "results": {},
    }
    calls = []

    def req(path, body=None):
        calls.append(path)
        if path == "/api/packs":
            return [{"id": "2026-11-05:flemington"}, {"id": "2026-11-04:other"}]
        return pack

    return req, calls


def test_writes_only_when_the_prediction_changes():
    box, now = Container(), dt.datetime(2026, 11, 5, 1, 0, tzinfo=dt.UTC)
    req, calls = fake_server(0.3)
    assert racelens.snapshot_day(box, req, "2026-11-05", now) == (1, 1)
    assert racelens.snapshot_day(box, req, "2026-11-05", now) == (1, 0)
    req2, _ = fake_server(0.4)
    assert racelens.snapshot_day(box, req2, "2026-11-05", now + dt.timedelta(minutes=5)) == (1, 1)
    saved = sorted(k for k in box.store if k.endswith(".gz"))
    assert saved == [
        "2026-11-05/flemington/R1/010000.json.gz",
        "2026-11-05/flemington/R1/010500.json.gz",
    ]
    body = json.loads(gzip.decompress(box.store[saved[-1]]))
    assert body["prediction"]["ranked"][0]["winProb"] == 0.4
    assert "/api/packs/2026-11-04%3Aother" not in calls  # other days are never fetched
