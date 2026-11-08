"""The collector publishes to Azure Blob only: no GitHub HTTP call, blob upload happens."""

import gzip
import types
import urllib.request

from tests.test_azure_function import FakeService, gz  # noqa: F401  (fakes only)


def test_publish_pending_uses_blob_and_never_github(monkeypatch):
    import importlib.util
    import sys
    from pathlib import Path

    pkg = Path(__file__).resolve().parents[1] / "azure" / "function"
    sys.path.insert(0, str(pkg))
    try:
        rt = importlib.import_module("collector_runtime")
    finally:
        sys.path.remove(str(pkg))

    def no_http(*a, **k):
        raise AssertionError("network call made")

    monkeypatch.setattr(urllib.request, "urlopen", no_http)
    assert not hasattr(rt, "commit_github_file") and not hasattr(rt, "github_api")
    svc = FakeService()
    name = "pending/2026-11-02/20261102T030000Z-az-a-0001.jsonl.gz"
    svc.put("c", name, gzip.compress(b"x\n"))
    uploads = []
    container = svc.get_container_client("c")
    real = type(container.get_blob_client("z")).upload_blob

    def spy(self, content, overwrite=False, content_settings=None):
        uploads.append(self.name)
        return real(self, content, overwrite, content_settings)

    monkeypatch.setattr(type(container.get_blob_client("z")), "upload_blob", spy)
    done = rt.publish_pending(container, "2026-11-02/12")
    assert len(done) == 1 and done[0] in uploads
    assert gzip.decompress(svc.containers["c"][done[0]]) == b"x\n"
    assert name not in svc.containers["c"]
