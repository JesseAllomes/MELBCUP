# ruff: noqa: E501, E702
"""Deploy straight to Azure, no GitHub Actions (owner, 2026-11-04: "stop using git to deploy").

    python3 tools/deploy_azure.py web|job|function|all [--skip-checks]

Needs, in the environment (never in the repository): AZURE_TENANT_ID, AZURE_CLIENT_ID,
AZURE_CLIENT_SECRET (a service principal with rights on the resource group) and GHCR_TOKEN (the
registry token kept in Key Vault as ghcr-publish-token) for web and job.

Before anything goes out, the same gates the workflow had: tools/cost_guard.py (against
origin/main) and the test suite. After each deploy the live resource is read back and checked with
cost_guard --live, like the workflow did.

web, job: the code changes ship as one new image layer on top of the image running now (its
Python packages stay as they are), pushed to ghcr.io, and the resource is PUT from its spec in
azure/ (melbcup-web.json, jobs/melbcup-nba.json) with that image. A change to dependencies
(pyproject.toml, requirements, a Dockerfile) needs a full image build: the azure-deploy workflow
can still be started by hand for that.
function: the package the workflow built (named files + wheels for the Function's Python), zipped
and published to the Flex Consumption app with the one-deploy API.
"""

from __future__ import annotations

import base64
import datetime as dt
import gzip
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUB = "78e367c0-cd4d-4334-8c02-69fa04c8bffd"
RG = "rg-personal-automation-aue"
ARM = f"https://management.azure.com/subscriptions/{SUB}/resourceGroups/{RG}/providers"
ENV_NAME = "cae-personal-v5ethud2i3cfq"
FUNC = "func-personal-v5ethud2i3cfq"
FUNC_PY = "3.12"
TIMEOUT = 120

WEB = {
    "repo": "jesseallomes/melbcup-web",
    "url": f"{ARM}/Microsoft.App/containerApps/melbcup-web?api-version=2025-01-01",
    "spec": "azure/webapp/melbcup-web.json",
    # the code is imported from /app (uvicorn puts its working directory first) and was also
    # pip-installed into site-packages: both copies are replaced
    "files": [("melbcup", "app/melbcup"), ("melbcup", "usr/local/lib/python3.13/site-packages/melbcup"),
              ("docs/data", "app/docs/data"), ("data/nba", "app/data/nba")],
    "live": "containerapp.json",
}
JOB = {
    "repo": "jesseallomes/melbcup-nba",
    "url": f"{ARM}/Microsoft.App/jobs/melbcup-nba?api-version=2025-01-01",
    "spec": "azure/jobs/melbcup-nba.json",
    "files": [(f"tools/nba/{n}", f"app/tools/nba/{n}") for n in ("board.py", "tune.py", "tune_v4.py", "settle.py", "espn_history.py", "daily.py", "legs.py", "model_v3.json", "model_v4.json", "forward_report.py")]
    + [("melbcup/__init__.py", "app/melbcup/__init__.py"), ("melbcup/nba_legs.py", "app/melbcup/nba_legs.py")],
    "live": "job-melbcup-nba.json",
}
FUNC_FILES = ["azure/function/function_app.py", "azure/function/collector_runtime.py", "azure/function/racelens.py",
              "azure/function/nba_props.py", "azure/function/push_send.py", "azure/function/host.json",
              "azure/function/requirements.txt"]


def say(msg):
    print(msg, flush=True)


# ------------------------------------------------------------------ Azure


_TOKENS: dict[str, tuple[float, str]] = {}


def token(scope="https://management.azure.com/.default") -> str:
    stamp, tok = _TOKENS.get(scope, (0.0, ""))
    if time.time() - stamp < 1800:
        return tok
    from azure.identity import ClientSecretCredential

    cred = ClientSecretCredential(os.environ["AZURE_TENANT_ID"], os.environ["AZURE_CLIENT_ID"], os.environ["AZURE_CLIENT_SECRET"])
    tok = cred.get_token(scope).token
    _TOKENS[scope] = (time.time(), tok)
    return tok


def http(method, url, body=None, headers=None, raw=False, tries=4):
    """One HTTP call, retried on network errors and 5xx (2s, 4s, 8s)."""
    for attempt in range(tries):
        req = urllib.request.Request(url, method=method, data=body, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                data = r.read()
                return (data, r.headers) if raw else (json.loads(data) if data else {})
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == tries - 1:
                raise SystemExit(f"{method} {url.split('?')[0]} -> {e.code}: {e.read()[:400]!r}") from None
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            if attempt == tries - 1:
                raise
        time.sleep(2 ** (attempt + 1))
    raise AssertionError("unreachable")


def arm(method, url, body=None):
    hdr = {"Authorization": "Bearer " + token(), "Content-Type": "application/json"}
    return http(method, url, json.dumps(body).encode() if body is not None else None, hdr)


def wait_provisioned(url, what):
    for _ in range(60):
        state = arm("GET", url)["properties"].get("provisioningState")
        if state in ("Succeeded", "Failed", "Canceled"):
            break
        time.sleep(5)
    say(f"  {what}: {state}")
    if state != "Succeeded":
        raise SystemExit(f"{what} did not provision")


# ------------------------------------------------------------------ registry


class Registry:
    def __init__(self, repo):
        self.repo = repo
        basic = base64.b64encode(f"JesseAllomes:{os.environ['GHCR_TOKEN']}".encode()).decode()
        url = f"https://ghcr.io/token?scope=repository:{repo}:pull,push&service=ghcr.io"
        self.tok = http("GET", url, headers={"Authorization": "Basic " + basic})["token"]

    def h(self, extra=None):
        return {"Authorization": "Bearer " + self.tok} | (extra or {})

    def manifest(self, ref):
        accept = "application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.v2+json"
        data, hdrs = http("GET", f"https://ghcr.io/v2/{self.repo}/manifests/{ref}", headers=self.h({"Accept": accept}), raw=True)
        return json.loads(data), hdrs.get("Content-Type")

    def blob(self, digest):
        data, _ = http("GET", f"https://ghcr.io/v2/{self.repo}/blobs/{digest}", headers=self.h(), raw=True)
        return data

    def has(self, digest):
        try:
            http("HEAD", f"https://ghcr.io/v2/{self.repo}/blobs/{digest}", headers=self.h(), raw=True, tries=1)
            return True
        except SystemExit:
            return False

    def push_blob(self, data):
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        if self.has(digest):
            return digest
        _, hdrs = http("POST", f"https://ghcr.io/v2/{self.repo}/blobs/uploads/", b"", self.h({"Content-Length": "0"}), raw=True)
        loc = hdrs["Location"]
        loc = loc if loc.startswith("http") else "https://ghcr.io" + loc
        sep = "&" if "?" in loc else "?"
        http("PUT", f"{loc}{sep}digest={digest}", data, self.h({"Content-Type": "application/octet-stream"}), raw=True)
        return digest

    def push_manifest(self, man, media, tag):
        body = json.dumps(man, separators=(",", ":")).encode()
        http("PUT", f"https://ghcr.io/v2/{self.repo}/manifests/{tag}", body, self.h({"Content-Type": media}), raw=True)
        return "sha256:" + hashlib.sha256(body).hexdigest()


def code_layer(files) -> tuple[bytes, str]:
    """A gzip tar of the given (source, path in image) pairs; returns (blob, diff_id)."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar:
        dirs = set()
        for src, dest in files:
            p = ROOT / src
            items = [p] if p.is_file() else sorted(x for x in p.rglob("*") if x.is_file() and "__pycache__" not in x.parts)
            for f in items:
                rel = dest if p.is_file() else f"{dest}/{f.relative_to(p).as_posix()}"
                parts = rel.split("/")
                for i in range(1, len(parts)):
                    d = "/".join(parts[:i])
                    if d not in dirs:
                        dirs.add(d)
                        ti = tarfile.TarInfo(d); ti.type = tarfile.DIRTYPE; ti.mode = 0o755; ti.mtime = 0
                        tar.addfile(ti)
                ti = tarfile.TarInfo(rel); data = f.read_bytes(); ti.size = len(data); ti.mode = 0o644; ti.mtime = 0
                tar.addfile(ti, io.BytesIO(data))
    raw_bytes = raw.getvalue()
    diff_id = "sha256:" + hashlib.sha256(raw_bytes).hexdigest()
    return gzip.compress(raw_bytes, mtime=0), diff_id


def ship_image(target, running_image, label):
    """Push running image + one code layer; returns the new image reference (repo@digest)."""
    reg = Registry(target["repo"])
    base_ref = running_image.split("@", 1)[1]
    man, media = reg.manifest(base_ref)
    cfg = json.loads(reg.blob(man["config"]["digest"]))
    man = dict(man)
    hist = cfg.get("history", [])
    if hist and "tools/deploy_azure.py code layer" in hist[-1].get("created_by", ""):
        # the running image is itself a direct deploy: replace its code layer, don't stack another
        man["layers"] = man["layers"][:-1]
        cfg["rootfs"]["diff_ids"] = cfg["rootfs"]["diff_ids"][:-1]
        cfg["history"] = hist[:-1]
    blob, diff_id = code_layer(target["files"])
    layer_digest = reg.push_blob(blob)
    cfg["rootfs"]["diff_ids"].append(diff_id)
    cfg.setdefault("history", []).append({"created": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), "created_by": f"tools/deploy_azure.py code layer {label}"})
    cfg_bytes = json.dumps(cfg, separators=(",", ":")).encode()
    cfg_digest = reg.push_blob(cfg_bytes)
    layer_media = man["layers"][-1]["mediaType"]
    man["config"] = dict(man["config"], digest=cfg_digest, size=len(cfg_bytes))
    man["layers"] = man["layers"] + [{"mediaType": layer_media, "digest": layer_digest, "size": len(blob)}]
    digest = reg.push_manifest(man, media, f"code-{label}")
    say(f"  image: {len(blob) // 1024} KB code layer on {base_ref[:19]}... -> {digest[:19]}...")
    return f"ghcr.io/{target['repo']}@{digest}"


# ------------------------------------------------------------------ targets


def _swap(obj, image, env_id):
    if obj == "IMAGE":
        return image
    if obj == "ENVIRONMENT_ID":
        return env_id
    if isinstance(obj, dict):
        return {k: _swap(v, image, env_id) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_swap(v, image, env_id) for v in obj]
    return obj


def env_id():
    return arm("GET", f"{ARM}/Microsoft.App/managedEnvironments/{ENV_NAME}?api-version=2025-01-01")["id"]


def live_check(target_url, name):
    live = Path(tempfile.mkdtemp()) / name
    live.write_text(json.dumps(arm("GET", target_url)))
    guard("--live", str(live))


def deploy_web(label):
    say("web: melbcup-web")
    running = arm("GET", WEB["url"])["properties"]["template"]["containers"][0]["image"]
    image = ship_image(WEB, running, label)
    spec = json.loads((ROOT / WEB["spec"]).read_text())
    identity = spec["configuration"]["secrets"][0]["identity"]
    body = {"location": "australiaeast", "identity": {"type": "UserAssigned", "userAssignedIdentities": {identity: {}}},
            "properties": _swap(spec, image, env_id())}
    arm("PUT", WEB["url"], body)
    wait_provisioned(WEB["url"], "container app")
    live_check(WEB["url"], WEB["live"])


def deploy_job(label):
    say("job: melbcup-nba")
    running = arm("GET", JOB["url"])["properties"]["template"]["containers"][0]["image"]
    image = ship_image(JOB, running, label)
    spec = json.loads((ROOT / JOB["spec"]).read_text())
    spec.pop("name", None)
    arm("PUT", JOB["url"], _swap(spec, image, env_id()))
    wait_provisioned(JOB["url"], "job")
    live_check(JOB["url"], JOB["live"])


def deploy_function(label):
    say(f"function: {FUNC}")
    pkg = Path(tempfile.mkdtemp()) / "pkg"
    (pkg / "tools").mkdir(parents=True)
    for f in FUNC_FILES:
        shutil.copy(ROOT / f, pkg)
    shutil.copy(ROOT / "tools/live_collector.py", pkg / "tools/live_collector.py")
    shutil.copy(ROOT / "melbcup/nba_legs.py", pkg / "nba_legs.py")
    shutil.copy(ROOT / "melbcup/webpush.py", pkg / "webpush.py")
    shutil.copy(ROOT / "melbcup/tgbot.py", pkg / "tgbot.py")
    shutil.copy(ROOT / "melbcup/nba_challenge.py", pkg / "nba_challenge.py")
    (pkg / "tools/__init__.py").touch()
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--no-cache-dir", "--only-binary=:all:",
                    "--platform", "manylinux2014_x86_64", "--python-version", FUNC_PY, "--implementation", "cp",
                    "-r", str(ROOT / "azure/function/requirements.txt"), "--target", str(pkg / ".python_packages/lib/site-packages")],
                   check=True, timeout=600)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(pkg.rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts:
                z.write(f, f.relative_to(pkg).as_posix())
    data = buf.getvalue()
    say(f"  package {len(data) // 1024} KB ({label})")
    url = f"https://{FUNC}.scm.azurewebsites.net/api/publish?RemoteBuild=false"
    http("POST", url, data, {"Authorization": "Bearer " + token(), "Content-Type": "application/zip"}, raw=True, tries=2)
    say("  published")
    site = arm("GET", f"{ARM}/Microsoft.Web/sites/{FUNC}?api-version=2023-12-01")
    live = Path(tempfile.mkdtemp()) / "functionapp.json"
    live.write_text(json.dumps(site))
    guard("--live", str(live))


# ------------------------------------------------------------------ gates


def guard(*extra):
    r = subprocess.run([sys.executable, "tools/cost_guard.py", "--base-ref", "origin/main", *extra], cwd=ROOT, capture_output=True, text=True, timeout=300)
    last = (r.stdout.strip().splitlines() or ["?"])[-1]
    say(f"  cost guard: {last}")
    if r.returncode != 0:
        raise SystemExit(r.stdout + r.stderr)


def checks():
    say("checks: cost guard and tests")
    guard()
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x"], cwd=ROOT, capture_output=True, text=True, timeout=900)
    say("  tests: " + ((r.stdout.strip().splitlines() or ["?"])[-1]))
    if r.returncode != 0:
        raise SystemExit(r.stdout[-3000:])


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else ""
    if what not in ("web", "job", "function", "all"):
        raise SystemExit(__doc__)
    label = subprocess.run(["git", "rev-parse", "--short=8", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip() or "local"
    if "--skip-checks" not in sys.argv:
        checks()
    for name, fn in (("function", deploy_function), ("job", deploy_job), ("web", deploy_web)):
        if what in (name, "all"):
            fn(label)
    say("done")


if __name__ == "__main__":
    main()
