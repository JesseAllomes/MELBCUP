from __future__ import annotations

import datetime as dt
import json
import logging
import os
import sys
import tempfile
import threading
import urllib.request
import uuid
from pathlib import Path

import azure.functions as func
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from collector_runtime import (  # noqa: E402
    CollectorSession,
    StateTooLarge,
    decode_state,
    encode_state,
    publish_pending,
    valid_signature,
    within_window,
)

app = func.FunctionApp()
lock = threading.Lock()
session: CollectorSession | None = None

REPO = "jesseallomes/lotto-project"
MAX_STARTS_PER_HOUR = 6
PUBLISH_GRACE_S = 3600  # publish may run once more after the stop time to flush the last hour
ARM_TIMEOUT_S = 15
ARM_API = "2024-03-01"
RUNNING = {"running", "processing"}


class JobBusy(Exception):
    """A lotto-reenter execution is already running."""


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def blobs() -> BlobServiceClient:
    connection = os.environ.get("AzureWebJobsStorage", "")
    if "DefaultEndpointsProtocol=" in connection:
        return BlobServiceClient.from_connection_string(connection)
    return BlobServiceClient(
        account_url=os.environ["AZURE_STORAGE_ACCOUNT_URL"], credential=DefaultAzureCredential()
    )


def window_open(moment: dt.datetime, grace_s: float = 0) -> bool:
    """True only inside the collection window and while COLLECTOR_DISABLED is not 1."""
    if os.environ.get("COLLECTOR_DISABLED") == "1":
        return False
    try:
        return within_window(
            moment,
            os.environ.get("COLLECTOR_START_UTC", "2026-10-30T13:00:00Z"),
            os.environ.get("COLLECTOR_STOP_UTC", "2026-11-07T13:00:00Z"),
            grace_s,
        )
    except ValueError:
        logging.error(
            "COLLECTOR_START_UTC / COLLECTOR_STOP_UTC are not ISO timestamps; staying off"
        )
        return False


def load_session() -> CollectorSession:
    global session
    if session is not None:
        return session
    try:
        raw = blobs().get_blob_client("collector-state", "state.json").download_blob().readall()
    except ResourceNotFoundError:
        raw = None
    session = CollectorSession(decode_state(raw))  # corrupt or oversized state: cold start
    return session


def save_state(state: dict) -> None:
    client = blobs().get_blob_client("collector-state", "state.json")
    try:
        raw = encode_state(state)
    except StateTooLarge:
        logging.error("collector state over the size limit; dropping it for a cold start")
        try:
            client.delete_blob()
        except ResourceNotFoundError:
            pass
        raise
    client.upload_blob(raw, overwrite=True)


@app.timer_trigger(schedule="0 * * * * *", arg_name="timer", run_on_startup=False, use_monitor=True)
def collect(timer: func.TimerRequest) -> None:
    global session
    if not window_open(now_utc()):
        return
    if not lock.acquire(blocking=False):
        logging.warning("previous collection cycle is still running")
        return
    try:
        runtime = load_session()
        with tempfile.TemporaryDirectory(prefix="melbcup-cycle-") as directory:
            state, files, elapsed, skipped = runtime.run_once(
                Path(directory), uuid.uuid4().hex[:12]
            )
            if not skipped:
                client = blobs()
                for path in files:
                    rel = path.relative_to(directory).as_posix()
                    client.get_blob_client("live-observations", f"pending/{rel}").upload_blob(
                        path.read_bytes(),
                        overwrite=False,
                        content_settings=ContentSettings(content_type="application/gzip"),
                    )
                logging.info("collector cycle completed in %.3f seconds", elapsed)
            save_state(state)
    except BaseException:
        session = None  # in-memory state may be ahead of the blobs: reload from the blob next time
        raise
    finally:
        lock.release()


@app.timer_trigger(schedule="0 7 * * * *", arg_name="timer", run_on_startup=False, use_monitor=True)
def publish(timer: func.TimerRequest) -> None:
    moment = now_utc()
    if not window_open(moment, PUBLISH_GRACE_S):
        return
    container = blobs().get_container_client("live-observations")
    publish_pending(container, lambda: os.environ["GITHUB_TOKEN"], moment.strftime("%Y-%m-%d/%H"))


def take_start_slot(moment: dt.datetime) -> bool:
    """Count a start attempt in a per-hour counter blob; False once MAX_STARTS_PER_HOUR is used."""
    client = blobs().get_blob_client("webhook-replays", f"rate-{moment:%Y%m%d%H}")
    try:
        count = int(client.download_blob().readall() or 0)
    except ResourceNotFoundError:
        count = 0
    except ValueError:
        count = MAX_STARTS_PER_HOUR  # unreadable counter: fail closed
    if count >= MAX_STARTS_PER_HOUR:
        return False
    client.upload_blob(str(count + 1).encode(), overwrite=True)
    return True


def arm(url: str, token: str, method: str = "GET", payload: dict | None = None) -> dict:
    request = urllib.request.Request(
        url,
        data=None if payload is None else json.dumps(payload).encode(),
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=ARM_TIMEOUT_S) as response:
        body = response.read()
    return json.loads(body) if body else {}


def start_reenter_job(issue: dict) -> None:
    """Start one lotto-reenter execution for the issue; raise JobBusy if one is already running."""
    token = DefaultAzureCredential().get_token("https://management.azure.com/.default").token
    resource = f"https://management.azure.com{os.environ['LOTTO_REENTER_JOB_RESOURCE_ID']}"
    executions = arm(f"{resource}/executions?api-version={ARM_API}", token)
    for item in executions.get("value", []):
        if str((item.get("properties") or {}).get("status", "")).lower() in RUNNING:
            raise JobBusy
    template = arm(f"{resource}?api-version={ARM_API}", token)["properties"]["template"]
    worker = next(item for item in template["containers"] if item["name"] == "worker")
    worker["env"] = [
        item
        for item in worker.get("env", [])
        if item["name"] not in {"ISSUE_TITLE", "ISSUE_NUMBER"}
    ]
    worker["env"].extend(
        [
            {"name": "ISSUE_TITLE", "value": issue["title"]},
            {"name": "ISSUE_NUMBER", "value": str(issue["number"])},
        ]
    )
    arm(f"{resource}/start?api-version={ARM_API}", token, "POST", {"template": template})


@app.route(route="github/reenter", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def reenter(req: func.HttpRequest) -> func.HttpResponse:
    body = req.get_body()
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    if not secret:
        return func.HttpResponse("webhook not configured", status_code=503)
    if not valid_signature(secret, body, req.headers.get("x-hub-signature-256", "")):
        return func.HttpResponse("invalid signature", status_code=401)
    if req.headers.get("x-github-event", "") != "issues":
        return func.HttpResponse("ignored", status_code=202)
    try:
        payload = json.loads(body)
    except ValueError:
        return func.HttpResponse("invalid json", status_code=400)
    if not isinstance(payload, dict):
        return func.HttpResponse("invalid json", status_code=400)
    issue = payload.get("issue") or {}
    repository = payload.get("repository") or {}
    if str(repository.get("full_name", "")).lower() != REPO:
        return func.HttpResponse("ignored", status_code=202)
    owner = (repository.get("owner") or {}).get("login")
    if payload.get("action") != "opened" or (issue.get("user") or {}).get("login") != owner:
        return func.HttpResponse("ignored", status_code=202)
    if not str(issue.get("title") or "").lower().startswith("reenter"):
        return func.HttpResponse("ignored", status_code=202)

    # Dedupe on the signed issue id: the delivery-id header is unsigned and changes in a replay.
    issue_id = issue.get("id")
    if not isinstance(issue_id, int) or isinstance(issue_id, bool) or "number" not in issue:
        return func.HttpResponse("missing issue id", status_code=400)
    replays = blobs().get_container_client("webhook-replays")
    marker = f"issue-{issue_id}"
    if replays.get_blob_client(marker).exists():
        return func.HttpResponse("already queued", status_code=202)
    if not take_start_slot(now_utc()):
        return func.HttpResponse("too many job starts this hour", status_code=429)
    try:
        start_reenter_job(issue)
    except JobBusy:
        return func.HttpResponse("a reenter job is already running", status_code=409)
    except Exception:
        logging.exception("could not start the reenter job")
        return func.HttpResponse("job start failed", status_code=502)
    # Written only after the job started, so a failed start leaves no marker and can be redelivered.
    try:
        replays.get_blob_client(marker).upload_blob(b"1", overwrite=False)
    except ResourceExistsError:
        pass
    except Exception:
        logging.exception("job started but the replay marker was not written")
    return func.HttpResponse("queued", status_code=202)
