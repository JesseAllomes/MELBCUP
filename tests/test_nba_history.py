"""NBA box-score history batches (azure/function/nba_history.py): resumable, skips missing games."""

import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "azure" / "function"))
import nba_history  # noqa: E402
from test_racelens_snapshot import Container  # noqa: E402


def test_batches_resume_and_skip_missing(monkeypatch):
    monkeypatch.setattr(nba_history, "BATCH", 3)
    monkeypatch.setattr(nba_history, "fetch", lambda gid: None if gid.endswith("2") else b'{"g":1}')
    box = Container()
    first = nba_history.run_batch(box)
    assert (first["next"], first["saved"], first["missing"]) == (3, 2, ["0022400002"])
    second = nba_history.run_batch(box)
    assert second["next"] == 6 and second["saved"] == 5
    assert json.loads(gzip.decompress(box.store["00224/0022400001.json.gz"])) == {"g": 1}
    assert not second["finished"]
