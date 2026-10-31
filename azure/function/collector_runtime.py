"""Runtime-independent helpers for the timer-triggered Azure collector.

The collector itself is tools/live_collector.py, copied into the package at deploy time
(.github/workflows/azure-deploy.yml), so the GitHub runner and the function never diverge.
Nothing here imports the Azure SDK; function_app.py does, and tests stub it.
"""

from __future__ import annotations

import base64
import datetime as dt
import gzip
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tools import live_collector as lc
from tools.live_collector import Collector, Log, iso, now

STATE_LIMIT_BYTES = 256 * 1024
MAX_PUBLISH_HOURS = 3
GITHUB_TIMEOUT_S = 20


class StateTooLarge(RuntimeError):
    """state.json would exceed STATE_LIMIT_BYTES: the caller drops it and cold-starts."""


def parse_utc(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt.UTC)


def within_window(moment: dt.datetime, start: str, stop: str, grace_s: float = 0) -> bool:
    moment = moment.astimezone(dt.UTC)
    return parse_utc(start) <= moment < parse_utc(stop) + dt.timedelta(seconds=grace_s)


def throttle_enabled() -> bool:
    """The cadence throttle thins the data on exactly the busy days, so it is opt-in."""
    return os.environ.get("COLLECTOR_THROTTLE") == "1"


def cadence_divisor(durations: list[float]) -> int:
    recent = durations[-60:]
    average = sum(recent) / len(recent) if recent else 0.0
    if average > 8.0:
        return 4
    if average > 4.0:
        return 2
    return 1


def encode_state(state: dict) -> bytes:
    raw = json.dumps(state, separators=(",", ":")).encode()
    if len(raw) > STATE_LIMIT_BYTES:
        raise StateTooLarge(f"state is {len(raw)} bytes (limit {STATE_LIMIT_BYTES})")
    return raw


def decode_state(raw: bytes | str | None) -> dict | None:
    """Parse state.json; corrupt, oversized or wrongly shaped state is a cold start (None)."""
    if raw is None or len(raw) > STATE_LIMIT_BYTES:
        return None
    try:
        state = json.loads(raw)
    except ValueError:  # includes UnicodeDecodeError
        logging.warning("collector state is corrupt; cold start")
        return None
    return state if isinstance(state, dict) else None


def collector_version() -> str:
    return hashlib.sha256(Path(lc.__file__).read_bytes()).hexdigest()


def cadence() -> dict:
    return {
        "cycle_s": lc.CYCLE_S,
        "meetings_every": lc.MEETINGS_EVERY,
        "schedule_every": lc.SCHEDULE_EVERY,
        "flucs_every": lc.FLUCS_EVERY,
        "watch_before_s": lc.WATCH_BEFORE,
        "watch_after_s": lc.WATCH_AFTER,
    }


class CollectorSession:
    def __init__(self, state: dict | None = None):
        state = state if isinstance(state, dict) else {}
        self.collector_state = state.get("collector")
        self.durations = deque((float(x) for x in state.get("durations") or []), maxlen=60)
        self.invocations = int(state.get("invocations") or 0)

    def snapshot(self, collector: Collector) -> dict:
        return {
            "collector": collector.snapshot(),
            "durations": list(self.durations),
            "invocations": self.invocations,
        }

    def run_once(self, output: Path, invocation_id: str) -> tuple[dict, list[Path], float, bool]:
        """Run one poll; return state, the closed gzip files, seconds taken, and whether skipped."""
        self.invocations += 1
        divisor = cadence_divisor(list(self.durations)) if throttle_enabled() else 1
        if divisor > 1 and self.invocations % divisor:
            return (
                {
                    "collector": self.collector_state,
                    "durations": list(self.durations),
                    "invocations": self.invocations,
                },
                [],
                0.0,
                True,
            )

        run = f"{now().strftime('%Y%m%dT%H%M%SZ')}-az-{invocation_id}"
        log = Log(str(output), run, None)
        collector = Collector.restore(log, run, self.collector_state)
        collector.last = {}  # D1: files are self-contained; same_as never points elsewhere
        log.write(
            {
                "kind": "start",
                "run": run,
                "obs_utc": iso(now()),
                "version": collector_version(),
                "host": "azure-functions",
                "cadence": cadence(),
                "throttle": throttle_enabled(),
                "resume_cycle": collector.cycle,
            }
        )
        timeout = lc.REQUEST_TIMEOUT_S
        started = time.monotonic()
        lc.REQUEST_TIMEOUT_S = float(os.environ.get("COLLECTOR_REQUEST_TIMEOUT_S", "10"))
        lc.DEADLINE = time.time() + float(os.environ.get("COLLECTOR_CYCLE_BUDGET_S", "45"))
        collector.cycle_planned = now()
        try:
            with ThreadPoolExecutor(8) as pool:
                collector.poll(pool)
            reason = "one cycle complete"
        except Exception as exc:
            reason = "cycle failed"
            log.write(
                {
                    "kind": "error",
                    "what": "cycle",
                    "run": run,
                    "obs_utc": iso(now()),
                    "recv_utc": iso(now()),
                    "error": f"{type(exc).__name__}: {exc}"[:300],
                }
            )
            collector.cycle += 1
        finally:
            lc.REQUEST_TIMEOUT_S = timeout
            lc.DEADLINE = None
        elapsed = time.monotonic() - started
        self.durations.append(elapsed)
        self.collector_state = collector.snapshot()
        log.write(
            {
                "kind": "stop",
                "run": run,
                "obs_utc": iso(now()),
                "reason": reason,
                "cycles": collector.cycle,
                "elapsed_seconds": round(elapsed, 3),
            }
        )
        log.close()
        return self.snapshot(collector), sorted(output.rglob("*.gz")), elapsed, False


def merge_gzip(files: list[bytes]) -> bytes:
    """Merge gzip members into one deterministic gzip stream."""
    plain = b"".join(gzip.decompress(blob) for blob in files)
    return gzip.compress(plain, compresslevel=6, mtime=0)


def github_api(method: str, path: str, token: str, payload: object | None = None) -> object:
    raw = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/{path.lstrip('/')}",
        data=raw,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "melbcup-azure-collector",
        },
    )
    with urllib.request.urlopen(request, timeout=GITHUB_TIMEOUT_S) as response:
        body = response.read()
    return json.loads(body) if body else {}


def github_path_exists(path: str, token: str, branch: str = "live") -> bool:
    """True when `path` is already on `branch` (trees API, so file size does not matter)."""
    directory, _, name = path.rpartition("/")
    try:
        listing = github_api("GET", f"git/trees/{branch}:{directory}", token)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise
    return any(item.get("path") == name for item in listing.get("tree", []))


def commit_github_file(
    path: str, content: bytes, token: str, message: str, branch: str = "live"
) -> str:
    """Atomically add one file on a branch, retrying a moved branch head."""
    for attempt in range(4):
        ref = github_api("GET", f"git/ref/heads/{branch}", token)
        parent = ref["object"]["sha"]
        commit = github_api("GET", f"git/commits/{parent}", token)
        blob = github_api(
            "POST",
            "git/blobs",
            token,
            {"content": base64.b64encode(content).decode(), "encoding": "base64"},
        )
        tree = github_api(
            "POST",
            "git/trees",
            token,
            {
                "base_tree": commit["tree"]["sha"],
                "tree": [{"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]}],
            },
        )
        created = github_api(
            "POST",
            "git/commits",
            token,
            {"message": message, "tree": tree["sha"], "parents": [parent]},
        )
        try:
            github_api(
                "PATCH", f"git/refs/heads/{branch}", token, {"sha": created["sha"], "force": False}
            )
            return created["sha"]
        except urllib.error.HTTPError as exc:
            if exc.code not in (409, 422) or attempt == 3:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("unreachable")


def pending_hours(blobs, current_hour: str) -> dict[str, list]:
    """Group pending/<day>/<run>-<seq>.jsonl.gz blobs by closed UTC hour ('YYYY-MM-DD/HH')."""
    groups: dict[str, list] = {}
    for blob in blobs:
        parts = blob.name.split("/")
        if len(parts) < 3 or len(parts[2]) < 11 or not parts[2][9:11].isdigit():
            continue
        hour = f"{parts[1]}/{parts[2][9:11]}"
        if hour < current_hour:
            groups.setdefault(hour, []).append(blob)
    return groups


def hour_path(hour: str, records: list) -> str:
    """Unique per blob set: a late blob never replaces a published file; a retry finds its own."""
    digest = hashlib.sha256("\n".join(item.name for item in records).encode()).hexdigest()[:10]
    day, hour_number = hour.split("/")
    return f"observations/{day}/azure-{day}T{hour_number}00Z-{digest}.jsonl.gz"


def publish_pending(
    container,
    token_factory: Callable[[], str],
    current_hour: str,
    max_hours: int = MAX_PUBLISH_HOURS,
) -> list[str]:
    """Commit up to `max_hours` closed hours (oldest first) to the live branch; return the paths.

    Idempotent: a path that already exists is not committed again, published blob names go in
    a per-hour ledger, and pending blobs are deleted only once the commit (or the existing file) is
    confirmed. Any failure leaves the blobs for the next run.
    """
    groups = pending_hours(container.list_blobs(name_starts_with="pending/"), current_hour)
    if not groups:
        return []
    token = token_factory()  # read lazily: no pending work, no token needed
    done = []
    for hour, records in sorted(groups.items())[:max_hours]:
        records.sort(key=lambda item: item.name)
        ledger_blob = container.get_blob_client(f"published/{hour}.json")
        ledger = (
            set(json.loads(ledger_blob.download_blob().readall()))
            if ledger_blob.exists()
            else set()
        )
        fresh = [item for item in records if item.name not in ledger]  # not yet on the live branch
        if fresh:
            path = hour_path(hour, fresh)
            if github_path_exists(path, token):
                logging.info("%s already on live", path)
            else:
                payload = merge_gzip(
                    [container.download_blob(item.name).readall() for item in fresh]
                )
                day, hour_number = hour.split("/")
                commit_github_file(
                    path, payload, token, f"live: Azure observations {day} {hour_number}:00Z"
                )
            done.append(path)
            # Recorded before any delete, so leftovers of a failed delete are not committed twice.
            names = sorted(ledger | {item.name for item in fresh})
            ledger_blob.upload_blob(json.dumps(names).encode(), overwrite=True)
        for record in records:
            container.delete_blob(record.name)
    return done


def valid_signature(secret: str, body: bytes, supplied: str) -> bool:
    """HMAC-SHA256 over the raw body, compared as bytes so a non-ASCII header is a clean False."""
    if not secret:
        return False
    expected = ("sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()).encode()
    return hmac.compare_digest(expected, (supplied or "").encode("utf-8", "surrogateescape"))
