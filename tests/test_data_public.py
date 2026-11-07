"""/data: datasets stream, .gz files read as plain text, private blobs stay hidden."""

import gzip

from fastapi.testclient import TestClient

from melbcup import nba_feed
from melbcup.data_public import DATA_ABOUT, DATA_OK

CSV = "".join(f"{i},row\n" for i in range(5000)).encode()
BLOBS = {"sports/nba/dataset_games.csv.gz": gzip.compress(CSV), "push/subs.json": b"secret"}


def _app(monkeypatch):
    from melbcup.web import app as web

    monkeypatch.setenv("NBA_ACCOUNT", "acct")

    def stream(account, client, name):
        raw = BLOBS.get(name)
        if raw is None:
            return None
        return len(raw), iter([raw[i : i + 999] for i in range(0, len(raw), 999)])

    monkeypatch.setattr(nba_feed, "blob_stream", stream)
    monkeypatch.setattr(nba_feed, "blob_sizes", lambda a, c: {n: len(b) for n, b in BLOBS.items()})
    return TestClient(web.create_app() if hasattr(web, "create_app") else web.app)


def test_rules():
    assert DATA_OK.match("sports/racing/dataset.csv.gz") and DATA_OK.match("export/asynym-data.zip")
    assert not DATA_OK.match("push/subs.json") and not DATA_OK.match("us-on.json")
    assert DATA_ABOUT[-1][0] == ""  # every listed name has a description


def test_plain_and_rows(monkeypatch):
    c = _app(monkeypatch)
    full = c.get("/data/plain/sports/nba/dataset_games.csv.gz")
    assert full.status_code == 200 and full.content == CSV
    head = c.get("/data/plain/sports/nba/dataset_games.csv.gz?rows=10")
    assert head.text.splitlines() == [f"{i},row" for i in range(10)]
    raw = c.get("/data/sports/nba/dataset_games.csv.gz")
    assert gzip.decompress(raw.content) == CSV
    assert c.get("/data/push/subs.json").status_code == 404
    listed = [x["name"] for x in c.get("/data/index.json").json()]
    assert listed == ["sports/nba/dataset_games.csv.gz"]
