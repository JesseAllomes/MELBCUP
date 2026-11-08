from __future__ import annotations

import datetime as dt
import json
import logging
import os
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
from pathlib import Path

import azure.functions as func
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import nba_props  # noqa: E402
import push_send  # noqa: E402
import racelens  # noqa: E402
from collector_runtime import (  # noqa: E402
    CollectorSession,
    StateTooLarge,
    decode_state,
    encode_state,
    publish_pending,
    valid_signature,
    within_window,
)

try:
    import catalogue  # the deployed package: copied from melbcup/catalogue.py
except ImportError:  # the repository (tests)
    from melbcup import catalogue

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
    publish_pending(container, moment.strftime("%Y-%m-%d/%H"))


RACELENS_DAY = "2026-11-05"  # Oaks Day; RACELENS_DATE overrides
MELBOURNE = dt.timezone(dt.timedelta(hours=11))  # AEDT, all of the Spring Carnival


@app.timer_trigger(
    schedule="0 */5 20-23,0-10 * * *", arg_name="timer", run_on_startup=False, use_monitor=True
)
def racelens_snapshot(timer: func.TimerRequest) -> None:
    """Read-only RaceLens snapshots on the chosen race day only (owner and Damian agreed)."""
    moment = now_utc()
    day = os.environ.get("RACELENS_DATE", RACELENS_DAY)
    base = os.environ.get("RACELENS_URL", "").rstrip("/")
    password = os.environ.get("RACELENS_PASSWORD", "")
    if moment.astimezone(MELBOURNE).strftime("%Y-%m-%d") != day or not base or not password:
        return
    container = blobs().get_container_client("racelens")
    try:
        container.create_container()
    except ResourceExistsError:
        pass
    req = racelens.client(base, password)
    meetings, written = racelens.snapshot_day(container, req, day, moment)
    logging.info("racelens: %d meetings, %d race snapshots", meetings, written)


@app.timer_trigger(
    schedule="0 */10 * * * *", arg_name="timer", run_on_startup=False, use_monitor=True
)
def nba_props_run(timer: func.TimerRequest) -> None:
    """Every 10 minutes, around the clock (owner, 2026-11-07; was 7am-6:50pm AEDT): push the phone alerts that are due (owner,
    2026-11-04), then NBA player-prop prices from PointsBet and the day's legs (2026-11-03)."""
    moment, started = now_utc(), time.monotonic()
    try:
        _nba_work(moment)
    finally:  # after the NBA work, whatever happened to it; a catalogue error never escapes
        _catalogue_tick(moment, started)


def _nba_work(moment: dt.datetime) -> None:
    key, tg = os.environ.get("VAPID_PRIVATE_KEY"), os.environ.get("TELEGRAM_BOT_TOKEN")
    if key or tg:
        try:
            nba = blobs().get_container_client("nba")
            sent, dropped = push_send.send_due(nba, moment, key, tg_token=tg)
            logging.info("alerts: %d sent, %d phones dropped", sent, dropped)
        except Exception:  # alerts must never stop the prices
            logging.exception("alerts: failed")
    if os.environ.get("NBA_PROPS") == "0":
        return
    container = blobs().get_container_client("nba-props")
    try:
        container.create_container()
    except ResourceExistsError:
        pass
    snaps: list[dict] = []
    games, written = nba_props.collect(container, moment, keep=snaps)
    nba = blobs().get_container_client("nba")
    try:
        nba.create_container()
    except ResourceExistsError:
        pass
    legs = nba_props.price_legs(nba, snaps, moment)
    try:
        legs += "; " + nba_props.build_view(nba, snaps, moment)
    except Exception:  # the page falls back to working it out itself
        logging.exception("nba view: failed")
    logging.info("nba props: %d games, %d snapshots; legs %s", games, written, legs)
    logging.info("us books %s", nba_props.pretip_ping(nba, moment))


CATALOGUE_EVERY_S = 540  # every run (the 10-minute timer jitters): the best-multis page needs fresh prices
CATALOGUE_END_S = 42.0  # seconds after the run starts: the Function times out at 55 s (host.json)
CATALOGUE_STATE = "catalogue/state.json"


def _catalogue_tick(moment: dt.datetime, started: float) -> None:
    """Build the all-sport catalogue (PointsBet) into the `nba` container, at most every 30 minutes
    and within a time budget: sports are built in rotation (the cursor is kept in blob state) so
    a run builds as many as fit. Any error is logged and swallowed."""
    if os.environ.get("CATALOGUE") == "0":
        return
    try:
        c = blobs().get_container_client("nba")
        try:
            state = json.loads(c.download_blob(CATALOGUE_STATE).readall())
        except ResourceNotFoundError:
            state = {}
        last = state.get("last_build")
        if last and (moment - dt.datetime.fromisoformat(last)).total_seconds() < CATALOGUE_EVERY_S:
            return
        deadline = started + CATALOGUE_END_S
        if time.monotonic() > deadline - 8:
            logging.info("catalogue: skipped, the NBA work used the time")
            return
        out = catalogue.run_rotation(
            state.get("cursor", 0),
            deadline,
            moment,
            lambda n, b: c.get_blob_client(n).upload_blob(b, overwrite=True),
            lambda n: _read_blob(c, n),
            lambda: [b.name for b in c.list_blobs(name_starts_with="catalogue/raw/")],
        )
        for n in out["expired"]:
            try:
                c.get_blob_client(n).delete_blob()
            except ResourceNotFoundError:
                pass
        c.get_blob_client(CATALOGUE_STATE).upload_blob(
            json.dumps({"last_build": moment.isoformat(), "cursor": out["cursor"]}),
            overwrite=True,
        )
        logging.info("catalogue: built %s, cursor %s", out["built"], out["cursor"])
    except Exception:
        logging.exception("catalogue: failed")


def _read_blob(container, name: str):
    try:
        return container.download_blob(name).readall()
    except ResourceNotFoundError:
        return None


@app.queue_trigger(arg_name="msg", queue_name="alerts", connection="AzureWebJobsStorage")
def alerts_due(msg: func.QueueMessage) -> None:
    """On demand (owner, 2026-11-04): the web app queues each timed alert hidden until its time;
    this wakes then and sends that phone's due alerts. Runs only when there is an alert."""
    try:
        pid = json.loads(msg.get_body())["id"]
    except (ValueError, KeyError, TypeError):
        return
    key, tg = os.environ.get("VAPID_PRIVATE_KEY"), os.environ.get("TELEGRAM_BOT_TOKEN")
    nba = blobs().get_container_client("nba")
    sent, dropped = push_send.send_one(nba, pid, now_utc(), key, tg_token=tg)
    logging.info("alerts (queue): %d sent, %d phones dropped", sent, dropped)


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
