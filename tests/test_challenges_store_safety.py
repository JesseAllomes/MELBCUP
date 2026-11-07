"""The challenge store never overwrites the owner's challenges after a failed read."""

import json

import pytest

from melbcup import nba_challenge as C


def test_failed_read_is_not_an_empty_store(tmp_path, monkeypatch):
    f = tmp_path / "chs.json"
    monkeypatch.setenv("NBA_CHALLENGES_FILE", str(f))
    monkeypatch.delenv("NBA_ACCOUNT", raising=False)
    C._CACHE[:] = [0.0, None]
    store = C.load(None, fresh_read=True)
    store, _, _ = C.apply_store(store, {"ch": "newch", "chname": "Real", "op": "x1"}, "2026-11-07")
    C.save(store)
    saved = f.read_bytes()

    def boom():
        raise C.StoreUnavailable("blob down")

    monkeypatch.setattr(C, "_read", boom)
    C._CACHE[:] = [0.0, None]
    broken = C.load(None, fresh_read=True)
    assert broken.get("_unavailable")
    with pytest.raises(C.StoreUnavailable):
        C.save(broken)
    assert f.read_bytes() == saved and json.loads(saved)["challenges"][0]["name"] == "Real"
