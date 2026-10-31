"""Azure function package (azure/function): needs no Azure SDK, azure-functions or network.

The Azure modules are replaced by in-memory stubs and urllib.request.urlopen by a fake GitHub / ARM.
"""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import hmac
import importlib.util
import io
import json
import sys
import types
import urllib.error
import urllib.request
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1] / "azure" / "function"
SECRET = "s3cret"
RESOURCE = "/subscriptions/s/resourceGroups/rg/providers/Microsoft.App/jobs/lotto-reenter"
NOW = dt.datetime(2026, 11, 3, 5, 7, tzinfo=dt.UTC)


# ---------------------------------------------------------------- Azure stubs


class ResourceNotFoundError(Exception):
    pass


class ResourceExistsError(Exception):
    pass


class FakeBlob:
    def __init__(self, store, container, name):
        self.store, self.container, self.name = store, container, name

    @property
    def data(self):
        return self.store.containers.setdefault(self.container, {})

    def upload_blob(self, content, overwrite=False, content_settings=None):
        if self.store.fail_upload:
            raise RuntimeError("upload failed")
        if self.name in self.data and not overwrite:
            raise ResourceExistsError(self.name)
        self.data[self.name] = content if isinstance(content, bytes) else content.encode()

    def download_blob(self, name=None):
        key = name or self.name
        if key not in self.data:
            raise ResourceNotFoundError(key)
        payload = self.data[key]
        return types.SimpleNamespace(readall=lambda: payload)

    def delete_blob(self, name=None):
        key = name or self.name
        if key not in self.data:
            raise ResourceNotFoundError(key)
        if self.store.delete_calls_before_failure is not None:
            if self.store.delete_calls_before_failure == 0:
                raise RuntimeError("delete failed")
            self.store.delete_calls_before_failure -= 1
        del self.data[key]

    def exists(self):
        return self.name in self.data


class FakeContainer(FakeBlob):
    def __init__(self, store, container):
        super().__init__(store, container, "")

    def get_blob_client(self, name):
        return FakeBlob(self.store, self.container, name)

    def list_blobs(self, name_starts_with=""):
        return [
            types.SimpleNamespace(name=n)
            for n in sorted(self.data)
            if n.startswith(name_starts_with)
        ]


class FakeService:
    def __init__(self):
        self.containers: dict[str, dict[str, bytes]] = {}
        self.fail_upload = False
        self.delete_calls_before_failure = None

    def get_blob_client(self, container, name):
        return FakeBlob(self, container, name)

    def get_container_client(self, container):
        return FakeContainer(self, container)

    def put(self, container, name, content):
        self.containers.setdefault(container, {})[name] = content


class Headers(dict):
    def get(self, key, default=None):
        return super().get(key.lower(), default)


class HttpRequest:
    def __init__(self, body=b"", headers=None):
        self._body = body
        self.headers = Headers({k.lower(): v for k, v in (headers or {}).items()})

    def get_body(self):
        return self._body


class HttpResponse:
    def __init__(self, body="", status_code=200):
        self.body, self.status_code = body, status_code


def azure_stubs() -> dict[str, types.ModuleType]:
    def module(name, **attrs):
        mod = types.ModuleType(name)
        mod.__dict__.update(attrs)
        return mod

    class FunctionApp:
        def timer_trigger(self, **_):
            return lambda fn: fn

        def route(self, **_):
            return lambda fn: fn

    class DefaultAzureCredential:
        def get_token(self, *_):
            return types.SimpleNamespace(token="arm-token")

    return {
        "azure": module("azure"),
        "azure.core": module("azure.core"),
        "azure.core.exceptions": module(
            "azure.core.exceptions",
            ResourceNotFoundError=ResourceNotFoundError,
            ResourceExistsError=ResourceExistsError,
        ),
        "azure.identity": module("azure.identity", DefaultAzureCredential=DefaultAzureCredential),
        "azure.storage": module("azure.storage"),
        "azure.storage.blob": module(
            "azure.storage.blob",
            BlobServiceClient=object,
            ContentSettings=lambda **kw: types.SimpleNamespace(**kw),
        ),
        "azure.functions": module(
            "azure.functions",
            FunctionApp=FunctionApp,
            HttpRequest=HttpRequest,
            HttpResponse=HttpResponse,
            TimerRequest=object,
            AuthLevel=types.SimpleNamespace(ANONYMOUS="anonymous"),
        ),
    }


# ---------------------------------------------------------------- fake GitHub and ARM


class FakeNet:
    def __init__(self):
        self.github_files: set[str] = set()
        self.commits = []  # paths committed
        self.tree_paths: dict[str, str] = {}
        self.commit_trees: dict[str, str] = {}
        self.fail_commit = False
        self.arm_calls: list[tuple[str, str, dict | None]] = []
        self.running = False
        self.start_status = 200
        self.counter = 0

    def __call__(self, request, timeout=None):
        assert timeout is not None, "every urlopen call needs a timeout"
        url, method = request.full_url, request.get_method()
        payload = json.loads(request.data) if request.data else None
        if url.startswith("https://management.azure.com"):
            return self.arm(url, method, payload)
        assert url.startswith("https://api.github.com/repos/o/r/"), url
        return self.github(url.split("/repos/o/r/")[1], method, payload)

    def respond(self, body):
        return _Response(json.dumps(body).encode())

    def arm(self, url, method, payload):
        self.arm_calls.append((method, url, payload))
        if url.endswith("/start?api-version=2024-03-01"):
            if self.start_status != 200:
                raise urllib.error.HTTPError(url, self.start_status, "boom", {}, None)
            return self.respond({})
        if "/executions" in url:
            status = "Running" if self.running else "Succeeded"
            return self.respond({"value": [{"properties": {"status": status}}]})
        template = {
            "containers": [{"name": "worker", "env": [{"name": "ISSUE_TITLE", "value": "old"}]}]
        }
        return self.respond({"properties": {"template": template}})

    def github(self, path, method, payload):
        self.counter += 1
        if path.startswith("git/trees/live:"):
            directory = path.split(":", 1)[1]
            names = [
                f.rsplit("/", 1)[1] for f in self.github_files if f.rsplit("/", 1)[0] == directory
            ]
            if not names:
                raise urllib.error.HTTPError(path, 404, "nf", {}, None)
            return self.respond({"tree": [{"path": n} for n in names], "truncated": False})
        if path == "git/ref/heads/live":
            return self.respond({"object": {"sha": "head"}})
        if path.startswith("git/commits/"):
            return self.respond({"tree": {"sha": "base"}})
        if path == "git/blobs":
            return self.respond({"sha": f"blob{self.counter}"})
        if path == "git/trees":
            sha = f"tree{self.counter}"
            self.tree_paths[sha] = payload["tree"][0]["path"]
            return self.respond({"sha": sha})
        if path == "git/commits":
            if self.fail_commit:
                raise urllib.error.HTTPError(path, 500, "boom", {}, None)
            sha = f"commit{self.counter}"
            self.commit_trees[sha] = self.tree_paths[payload["tree"]]
            return self.respond({"sha": sha})
        if path == "git/refs/heads/live":
            file = self.commit_trees[payload["sha"]]
            self.github_files.add(file)
            self.commits.append(file)
            return self.respond({})
        raise AssertionError(path)


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


# ---------------------------------------------------------------- fixtures


@pytest.fixture
def net(monkeypatch):
    fake = FakeNet()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("LOTTO_REENTER_JOB_RESOURCE_ID", RESOURCE)
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    for name in (
        "COLLECTOR_DISABLED",
        "COLLECTOR_THROTTLE",
        "COLLECTOR_START_UTC",
        "COLLECTOR_STOP_UTC",
    ):
        monkeypatch.delenv(name, raising=False)
    return fake


@pytest.fixture
def fa(monkeypatch, net):
    """function_app.py loaded fresh: stubbed Azure modules, in-memory store, fixed clock."""
    for name, mod in azure_stubs().items():
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.syspath_prepend(str(PKG))
    monkeypatch.delitem(sys.modules, "collector_runtime", raising=False)
    spec = importlib.util.spec_from_file_location(
        "function_app_under_test", PKG / "function_app.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    service = FakeService()
    module.service = service
    monkeypatch.setattr(module, "blobs", lambda: service)
    monkeypatch.setattr(module, "now_utc", lambda: NOW)
    return module


@pytest.fixture
def rt(fa):
    return sys.modules["collector_runtime"]


def gz(text: str) -> bytes:
    return gzip.compress(text.encode(), mtime=0)


def sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def issue_body(issue_id=11, number=5, title="reenter: 1 2 3", user="jesseallomes", action="opened"):
    return json.dumps(
        {
            "action": action,
            "issue": {"id": issue_id, "number": number, "title": title, "user": {"login": user}},
            "repository": {
                "full_name": "JesseAllomes/Lotto-Project",
                "owner": {"login": "jesseallomes"},
            },
        }
    ).encode()


def hook(fa, body, *, event="issues", delivery="d1", signature=None):
    headers = {"x-github-event": event, "x-github-delivery": delivery}
    headers["x-hub-signature-256"] = sign(body) if signature is None else signature
    return fa.reenter(HttpRequest(body, headers))


# ------------------------------------------------------- D1 / D2 / D3 / D12: collector runtime


def fake_gql(lc, seen):
    soon = (dt.datetime.now(dt.UTC) + dt.timedelta(minutes=10)).isoformat()
    today = dt.datetime.now(dt.UTC).date().isoformat()

    def gql(query, variables):
        seen.append(lc.REQUEST_TIMEOUT_S)
        sent = lc.now()
        if "GetRaceMeetingsByStateNew" in query:
            rows = (
                [{"id": "M1", "venue": "V", "date": today, "state": "VIC"}]
                if variables["s"] == "VIC"
                else []
            )
            data = {"GetRaceMeetingsByStateNew": rows}
        elif "getNoCacheRacesForMeet" in query:
            data = {
                "getNoCacheRacesForMeet": [
                    {"id": "R1", "raceNumber": 1, "time": soon, "raceStatus": "open"}
                ]
            }
        elif "GetBettingData" in query:
            data = {"GetBettingData": {"id": "R1", "raceStatus": "open", "bettingStatus": "open"}}
        else:
            data = {"getNoCacheRaceForm": {"id": "R1"}}
        return data, None, 200, sent, lc.now()

    return gql


def records(files):
    out = []
    for path in files:
        out += [
            json.loads(line) for line in gzip.decompress(path.read_bytes()).decode().splitlines()
        ]
    return out


def test_d1_every_file_is_self_contained(rt, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(rt.lc, "gql", fake_gql(rt.lc, seen))
    session = rt.CollectorSession()
    first_state, first_files, _, _ = session.run_once(tmp_path / "a", "aaaa")
    state, files, _, _ = session.run_once(tmp_path / "b", "bbbb")
    second = records(files)
    markets = [r for r in second if r.get("what") == "market"]
    assert markets, "the restored collector must keep watching the race"
    assert all("data" in r and "same_as" not in r for r in markets)
    assert not any("same_as" in r for r in records(first_files) + second)
    assert json.loads(rt.encode_state(first_state))["collector"]["cycle"] == 1
    assert "query" not in json.dumps(state)  # D10: no query text in the state


def test_d2_request_timeout_and_d12_start_record(rt, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(rt.lc, "gql", fake_gql(rt.lc, seen))
    _, files, _, _ = rt.CollectorSession().run_once(tmp_path, "cccc")
    assert set(seen) == {10.0}
    assert (
        rt.lc.REQUEST_TIMEOUT_S == 30 and rt.lc.DEADLINE is None
    )  # restored for the GitHub runner
    start = next(r for r in records(files) if r["kind"] == "start")
    assert (
        start["version"]
        == hashlib.sha256((PKG.parents[1] / "tools/live_collector.py").read_bytes()).hexdigest()
    )
    assert start["cadence"]["cycle_s"] == 60 and start["host"] == "azure-functions"


def test_d3_throttle_is_off_unless_opted_in(rt, tmp_path, monkeypatch):
    monkeypatch.setattr(rt.lc, "gql", fake_gql(rt.lc, []))
    slow = {"durations": [30.0] * 60, "invocations": 1}
    _, _, _, skipped = rt.CollectorSession(slow).run_once(tmp_path / "a", "dddd")
    assert skipped is False
    monkeypatch.setenv("COLLECTOR_THROTTLE", "1")
    _, files, _, skipped = rt.CollectorSession(slow).run_once(tmp_path / "b", "eeee")
    assert skipped is True and files == []


# ---------------------------------------------------------------- D4 / D10 / D13: state handling


def test_d13_corrupt_state_is_a_cold_start(fa):
    fa.service.put("collector-state", "state.json", b"{not json")
    assert fa.load_session().collector_state is None
    fa.session = None
    fa.service.put("collector-state", "state.json", b"\xff\xfe")
    assert fa.load_session().collector_state is None
    fa.session = None
    fa.service.put("collector-state", "state.json", b"[1, 2]")
    assert fa.load_session().collector_state is None


def test_d10_oversized_state_fails_and_resets(fa, rt):
    fa.service.put("collector-state", "state.json", b'{"collector":{}}')
    with pytest.raises(rt.StateTooLarge):
        fa.save_state({"collector": {"meets": {"x": "y" * (rt.STATE_LIMIT_BYTES + 1)}}})
    assert "state.json" not in fa.service.containers["collector-state"]
    fa.service.put("collector-state", "state.json", b" " * (rt.STATE_LIMIT_BYTES + 1))
    fa.session = None
    assert fa.load_session().collector_state is None


def test_d4_any_exception_resets_the_cached_session(fa, rt, monkeypatch):
    monkeypatch.setattr(rt.lc, "gql", fake_gql(rt.lc, []))
    fa.collect(None)
    assert fa.session is not None
    assert any(n.startswith("pending/") for n in fa.service.containers["live-observations"])
    fa.service.fail_upload = True
    with pytest.raises(RuntimeError):
        fa.collect(None)
    assert fa.session is None


# ---------------------------------------------------------------- window / disable


def test_collect_and_publish_do_nothing_outside_the_window(fa, monkeypatch):
    monkeypatch.setattr(fa, "blobs", lambda: pytest.fail("storage touched outside the window"))
    monkeypatch.setattr(fa, "load_session", lambda: pytest.fail("collector ran outside the window"))
    monkeypatch.setenv(
        "COLLECTOR_STOP_UTC", "2026-11-03T03:00:00Z"
    )  # now is 05:07, past stop + 1 h grace
    fa.collect(None)
    fa.publish(None)
    monkeypatch.setenv("COLLECTOR_STOP_UTC", "2026-11-07T13:00:00Z")
    monkeypatch.setenv("COLLECTOR_START_UTC", "2026-11-04T00:00:00Z")  # not started yet
    fa.collect(None)
    fa.publish(None)


def test_disabled_and_bad_window_settings_stop_both_timers(fa, monkeypatch):
    monkeypatch.setattr(fa, "blobs", lambda: pytest.fail("storage touched while disabled"))
    monkeypatch.setenv("COLLECTOR_DISABLED", "1")
    fa.collect(None)
    fa.publish(None)
    monkeypatch.delenv("COLLECTOR_DISABLED")
    monkeypatch.setenv("COLLECTOR_STOP_UTC", "not a date")
    fa.collect(None)
    fa.publish(None)


def test_publish_gets_one_grace_hour_to_flush_after_the_stop(fa, net, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("COLLECTOR_STOP_UTC", "2026-11-03T05:00:00Z")  # now is 05:07
    fa.service.put(
        "live-observations", "pending/2026-11-03/20261103T040000Z-az-a-0001.jsonl.gz", gz("x\n")
    )
    fa.publish(None)
    assert len(net.commits) == 1
    monkeypatch.setattr(fa, "now_utc", lambda: NOW + dt.timedelta(hours=1))
    fa.service.put(
        "live-observations", "pending/2026-11-03/20261103T050000Z-az-b-0001.jsonl.gz", gz("y\n")
    )
    fa.publish(None)
    assert len(net.commits) == 1


# ---------------------------------------------------------------- D5 / D16: publish


def pend(fa, hour, tag="a"):
    day = "2026-11-02"
    name = f"pending/{day}/{day.replace('-', '')}T{hour:02d}0000Z-az-{tag}-0001.jsonl.gz"
    fa.service.put("live-observations", name, gz(f"{hour}{tag}\n"))
    return name


def left(fa):
    return sorted(fa.service.containers.get("live-observations", {}))


def test_d16_no_token_needed_when_nothing_is_pending(fa, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    fa.publish(None)  # would raise KeyError if the token were read eagerly
    pend(fa, 12, "z")  # hour 12 of the previous day is closed: now it needs the token
    with pytest.raises(KeyError):
        fa.publish(None)
    assert len(left(fa)) == 1


def test_publish_commits_a_unique_path_then_deletes(fa, net, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    pend(fa, 3, "a")
    pend(fa, 3, "b")
    fa.publish(None)
    (path,) = net.commits
    assert path.startswith("observations/2026-11-02/azure-2026-11-02T0300Z-") and path.endswith(
        ".jsonl.gz"
    )
    assert [n for n in left(fa) if n.startswith("pending/")] == []


def test_d5_a_partial_delete_never_commits_the_leftovers_twice(fa, net, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    pend(fa, 3, "a")
    pend(fa, 3, "b")
    fa.service.delete_calls_before_failure = 1
    with pytest.raises(RuntimeError):
        fa.publish(None)
    assert (
        len(net.commits) == 1 and len(left(fa)) == 2
    )  # committed; one pending blob left + the ledger
    fa.service.delete_calls_before_failure = None
    fa.publish(None)
    assert len(net.commits) == 1  # the leftover is in the ledger: deleted, not published again
    assert [n for n in left(fa) if n.startswith("pending/")] == []
    # a blob that arrives late for the same hour gets its own unique path and replaces nothing
    pend(fa, 3, "c")
    fa.publish(None)
    assert len(net.commits) == 2 and len(set(net.commits)) == 2


def test_d5_same_blob_set_already_on_live_is_not_committed_again(fa, net, monkeypatch, rt):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    name = pend(fa, 3, "a")
    records_ = [types.SimpleNamespace(name=name)]
    net.github_files.add(rt.hour_path("2026-11-02/03", records_))
    fa.publish(None)
    assert net.commits == [] and [n for n in left(fa) if n.startswith("pending/")] == []


def test_d5_blobs_survive_a_failed_commit(fa, net, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    pend(fa, 3, "a")
    net.fail_commit = True
    with pytest.raises(urllib.error.HTTPError):
        fa.publish(None)
    assert len(left(fa)) == 1  # nothing deleted, no ledger written
    net.fail_commit = False
    fa.publish(None)
    assert len(net.commits) == 1 and not [n for n in left(fa) if n.startswith("pending/")]


def test_d5_at_most_three_hours_per_run_oldest_first(fa, net, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    for hour in (9, 4, 7, 1, 6):
        pend(fa, hour)
    fa.publish(None)
    assert [p.split("T")[1][:2] for p in net.commits] == ["01", "04", "06"]
    assert len([n for n in left(fa) if n.startswith("pending/")]) == 2
    fa.publish(None)
    assert len(net.commits) == 5 and not [n for n in left(fa) if n.startswith("pending/")]


def test_the_current_hour_is_never_published(fa, net, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    name = "pending/2026-11-03/20261103T050000Z-az-a-0001.jsonl.gz"
    fa.service.put("live-observations", name, gz("x\n"))
    fa.publish(None)
    assert net.commits == [] and left(fa) == [name]


# ---------------------------------------------------------------- D6 / D7 / risk 2: the webhook


def test_signature_must_be_valid_and_never_raises(fa, net):
    body = issue_body()
    assert hook(fa, body, signature="sha256=" + "0" * 64).status_code == 401
    assert hook(fa, body, signature="sha256=éé").status_code == 401
    assert hook(fa, body, signature="").status_code == 401
    assert hook(fa, body, signature=sign(body, "other")).status_code == 401
    assert net.arm_calls == [] and fa.service.containers == {}


def test_a_missing_secret_refuses_instead_of_accepting_an_empty_key(fa, net, monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "")
    body = issue_body()
    assert hook(fa, body, signature=sign(body, "")).status_code == 503
    assert net.arm_calls == []


def test_only_issues_events_and_matching_issues_start_a_job(fa, net):
    body = issue_body()
    assert hook(fa, body, event="ping").status_code == 202
    assert hook(fa, body, event="issue_comment").status_code == 202
    for other in (
        issue_body(title="remove: 1"),
        issue_body(user="stranger"),
        issue_body(action="edited"),
    ):
        assert hook(fa, other).status_code == 202
    assert net.arm_calls == []
    assert hook(fa, b"[]").status_code == 400
    assert hook(fa, issue_body(issue_id="x")).status_code == 400


def test_valid_hook_starts_the_job_once_and_replays_are_dropped_on_issue_id(fa, net):
    body = issue_body(title="Reenter: 7")
    assert hook(fa, body, delivery="d1").status_code == 202
    starts = [c for c in net.arm_calls if c[1].endswith("/start?api-version=2024-03-01")]
    assert len(starts) == 1
    env = {e["name"]: e["value"] for e in starts[0][2]["template"]["containers"][0]["env"]}
    assert env == {"ISSUE_TITLE": "Reenter: 7", "ISSUE_NUMBER": "5"}
    assert "issue-11" in fa.service.containers["webhook-replays"]
    # the same signed body replayed with fresh delivery ids must not start anything
    for delivery in ("d2", "d3"):
        reply = hook(fa, body, delivery=delivery)
        assert (reply.status_code, reply.body) == (202, "already queued")
    assert len([c for c in net.arm_calls if c[1].endswith("/start?api-version=2024-03-01")]) == 1


def test_d6_failed_start_leaves_no_marker_so_redelivery_works(fa, net):
    body = issue_body()
    net.start_status = 500
    assert hook(fa, body).status_code == 502
    assert "issue-11" not in fa.service.containers.get("webhook-replays", {})
    net.start_status = 200
    assert hook(fa, body, delivery="d2").status_code == 202
    assert "issue-11" in fa.service.containers["webhook-replays"]


def test_d7_a_running_execution_gets_409_and_no_marker(fa, net):
    net.running = True
    body = issue_body()
    assert hook(fa, body).status_code == 409
    assert not [c for c in net.arm_calls if c[1].endswith("/start?api-version=2024-03-01")]
    assert "issue-11" not in fa.service.containers["webhook-replays"]
    net.running = False
    assert hook(fa, body, delivery="d2").status_code == 202


def test_at_most_six_starts_per_hour_then_429(fa, net):
    for n in range(1, 7):
        assert hook(fa, issue_body(issue_id=n, number=n)).status_code == 202
    assert hook(fa, issue_body(issue_id=7, number=7)).status_code == 429
    starts = [c for c in net.arm_calls if c[1].endswith("/start?api-version=2024-03-01")]
    assert len(starts) == 6
    assert fa.service.containers["webhook-replays"]["rate-2026110305"] == b"6"


def test_failed_attempts_count_against_the_hourly_cap(fa, net):
    net.start_status = 500
    for n in range(1, 7):
        assert hook(fa, issue_body(issue_id=n, number=n)).status_code == 502
    assert hook(fa, issue_body(issue_id=99, number=99)).status_code == 429
