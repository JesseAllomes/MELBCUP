#!/usr/bin/env python3
"""Cost guard for the MELBCUP Azure function. Stdlib only; no network, no Azure calls.

    python3 tools/cost_guard.py [--root DIR] [--limits azure/limits.json] [--live FILE ...] [--json]

Exit 0 = pass, 1 = violations (one line each: RULE path:line message), 2 = configuration error.
Deterministic: the only clock is --now (default: today, UTC), used for the collector stop-date rule.

Rules (function checks only; the limits file is owner-approved, see C10):
  C3   worst-case cost: the 10-day collector window at the host timeout, and a month at full scale
  C4   scale and host.json: instances, memory, always-ready, timeout, http throttles, sampling
  C5   function_app.py (ast): the allowed functions, timer rates, webhook auth order, window checks
  C6   resource types in azure/inventory.json against the allow-list
  C7   static code: unbounded calls (ratchet), loops, sleeps, retries, secrets
  C8   workflows: timeouts, concurrency, dispatch loops, triggers, cron volume, issue-title loops
  C10  ratchet: no limit may be loosened against the base ref (unless LIMITS_APPROVED=1)

--live takes the exports written by the deploy workflow, told apart by file name:
  *functionapp* (az functionapp show), *appsettings* (names, maybe values), *inventory*
  (az resource list).
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECONDS_30D = 30 * 24 * 3600
SUBPROCESS_CALLS = {"run", "Popen", "check_call", "check_output", "call"}
NETWORK_CALLS = {"urlopen", "github_api", "arm"}


class ConfigError(Exception):
    pass


class Report:
    def __init__(self):
        self.violations: list[tuple[str, str, str]] = []
        self.info: list[str] = []
        self.costs: dict[str, float] = {}

    def fail(self, rule: str, where: str, message: str) -> None:
        self.violations.append((rule, where, message))


def load_json(path: Path) -> dict | list:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc


def find_key(obj, key):
    """First value stored under `key` anywhere in a nested JSON structure (None if absent)."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for value in obj.values():
            found = find_key(value, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = find_key(value, key)
            if found is not None:
                return found
    return None


def parse_timeout(value) -> int | None:
    """host.json functionTimeout '[d.]hh:mm:ss' to seconds; None if missing, '-1' or malformed."""
    match = re.fullmatch(r"(?:(\d+)\.)?(\d{1,2}):(\d{2}):(\d{2})", str(value or ""))
    if not match:
        return None
    days, hours, minutes, seconds = (int(x or 0) for x in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def parse_utc(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt.UTC)


# ---------------------------------------------------------------- cron


def field_count(spec: str, low: int, high: int) -> int:
    """Count of values a numeric cron field (*, */n, a, a-b, a-b/n, lists) matches in range."""
    values: set[int] = set()
    for part in spec.split(","):
        match = re.fullmatch(r"(\*|\d+(?:-\d+)?)(?:/(\d+))?", part)
        if not match:
            raise ConfigError(f"unsupported cron field {spec!r}")
        base, step = match.group(1), int(match.group(2) or 1)
        if step < 1:
            raise ConfigError(f"unsupported cron step in {spec!r}")
        if base == "*":
            first, last = low, high
        elif "-" in base:
            first, last = (int(x) for x in base.split("-"))
        else:
            first = last = int(base)
            if match.group(2):
                last = high
        if not low <= first <= last <= high:
            raise ConfigError(f"cron field {spec!r} out of range")
        values.update(range(first, last + 1, step))
    return len(values)


def fires_per_day(cron: str) -> int:
    """Upper bound of firings per day for a 5-field cron or a 6-field NCRONTAB (seconds first)."""
    fields = cron.split()
    if len(fields) == 6:
        seconds, fields = field_count(fields[0], 0, 59), fields[1:]
    elif len(fields) == 5:
        seconds = 1
    else:
        raise ConfigError(f"cron {cron!r} needs 5 or 6 fields")
    return seconds * field_count(fields[0], 0, 59) * field_count(fields[1], 0, 23)


# ---------------------------------------------------------------- C3, C4


def window_days(limits: dict) -> float:
    return float(limits["function"]["max_collect_window_days"])


def function_cost(limits: dict, host_timeout_s: int, memory_mb: int) -> dict[str, float]:
    """Worst-case USD: every invocation of the collector window runs to the host timeout."""
    prices, fn = limits["prices"], limits["function"]
    gb = memory_mb / 1024
    days = window_days(limits)
    runs = {
        "collect": 1440 * days,
        "publish": 24 * days,
        "reenter": float(fn["assumed_http_requests_month"]),
    }
    gb_s = sum(count * host_timeout_s * gb for count in runs.values())
    executions = sum(runs.values())
    window = max(0.0, gb_s - prices["flex_free_gb_s"]) * prices["flex_gb_s"]
    window += (
        max(0.0, executions - prices["flex_free_exec"]) / 1e6 * prices["flex_per_million_exec"]
    )
    full_scale = fn["max_instances"] * gb * SECONDS_30D * prices["flex_gb_s"]
    return {
        "function_window_worst_case": round(window, 2),
        "function_full_scale_month": round(full_scale, 2),
    }


def check_scale(rep: Report, limits: dict, scale: dict, where: str) -> None:
    fn = limits["function"]
    maximum, memory, ready = scale.get("max"), scale.get("memory"), scale.get("ready")
    if not isinstance(maximum, int) or maximum > fn["max_instances"]:
        rep.fail("C4", where, f"maximumInstanceCount {maximum!r} must be <= {fn['max_instances']}")
    if not isinstance(memory, int) or memory > fn["max_instance_memory_mb"]:
        rep.fail(
            "C4", where, f"instanceMemoryMB {memory!r} must be <= {fn['max_instance_memory_mb']}"
        )
    if ready:
        rep.fail("C4", where, f"alwaysReady must be empty (found {ready!r})")


def read_scale(doc) -> dict:
    ready = find_key(doc, "alwaysReady")
    return {
        "max": find_key(doc, "maximumInstanceCount"),
        "memory": find_key(doc, "instanceMemoryMB"),
        "ready": ready if ready else None,
    }


def check_host(rep: Report, limits: dict, host: dict, where: str) -> int:
    fn = limits["function"]
    seconds = parse_timeout(host.get("functionTimeout"))
    if seconds is None or seconds <= 0 or seconds > fn["max_function_timeout_s"]:
        rep.fail(
            "C4",
            where,
            f"functionTimeout {host.get('functionTimeout')!r} must be hh:mm:ss, "
            f"> 0 and <= {fn['max_function_timeout_s']} s",
        )
        seconds = fn["max_function_timeout_s"]
    http = (host.get("extensions") or {}).get("http") or {}
    for key, cap in (
        ("maxConcurrentRequests", fn["max_http_concurrent"]),
        ("maxOutstandingRequests", fn["max_http_outstanding"]),
    ):
        value = http.get(key)
        if not isinstance(value, int) or not 0 < value <= cap:
            rep.fail("C4", where, f"extensions.http.{key} {value!r} must be set and <= {cap}")
    sampling = ((host.get("logging") or {}).get("applicationInsights") or {}).get(
        "samplingSettings"
    ) or {}
    if sampling.get("isEnabled") is not True:
        rep.fail("C4", where, "logging.applicationInsights.samplingSettings.isEnabled must be true")
    return seconds


def check_stop_value(rep: Report, limits: dict, value, where: str, now: dt.datetime) -> None:
    try:
        stop = parse_utc(str(value))
    except ValueError:
        rep.fail("C5", where, f"COLLECTOR_STOP_UTC {value!r} is not an ISO timestamp")
        return
    ceiling = now + dt.timedelta(days=window_days(limits))
    if stop > ceiling:
        rep.fail(
            "C5",
            where,
            f"COLLECTOR_STOP_UTC {value} is later than now + {window_days(limits):g} days",
        )


# ---------------------------------------------------------------- C5


def call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def names_and_strings(node: ast.AST) -> set[str]:
    found = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            found.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            found.add(sub.attr)
        elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            found.add(sub.value)
    return found


def check_function_app(rep: Report, limits: dict, path: Path, shown: str, now: dt.datetime) -> None:
    fn = limits["function"]
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        raise ConfigError(f"cannot parse {shown}: {exc}") from exc
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    allowed = fn["allowed_functions"]

    for node in ast.walk(tree):  # an app-wide anonymous default would expose every route
        if isinstance(node, ast.Call) and call_name(node) == "FunctionApp":
            for kw in node.keywords:
                if kw.arg == "http_auth_level" and "ANONYMOUS" in ast.unparse(kw.value):
                    rep.fail(
                        "C5", f"{shown}:{node.lineno}", "FunctionApp must not default to ANONYMOUS"
                    )

    found: dict[str, ast.FunctionDef] = {}
    for name, node in funcs.items():
        for deco in node.decorator_list:
            if not (isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute)):
                continue
            kind = deco.func.attr
            if kind != "route" and not kind.endswith("_trigger") and kind != "function_name":
                continue
            found[name] = node
            where = f"{shown}:{node.lineno}"
            kws = {kw.arg: kw.value for kw in deco.keywords}
            spec = allowed.get(name)
            if spec is None:
                rep.fail("C5", where, f"function {name!r} is not in limits.allowed_functions")
                continue
            if kind == "timer_trigger":
                schedule = kws.get("schedule")
                if not (isinstance(schedule, ast.Constant) and isinstance(schedule.value, str)):
                    rep.fail("C5", where, f"{name}: timer schedule must be a string literal")
                    continue
                per_day = fires_per_day(schedule.value)
                if per_day > spec.get("timer_max_per_day", 0):
                    rep.fail(
                        "C5",
                        where,
                        f"{name}: timer fires {per_day}/day, "
                        f"limit {spec.get('timer_max_per_day', 0)}",
                    )
            elif kind == "route":
                auth = ast.unparse(kws["auth_level"]) if "auth_level" in kws else ""
                route = kws.get("route")
                route_text = route.value if isinstance(route, ast.Constant) else None
                if "ANONYMOUS" in auth and not (
                    spec.get("anonymous") and route_text == spec.get("route")
                ):
                    rep.fail(
                        "C5", where, f"{name}: only route {spec.get('route')!r} may be ANONYMOUS"
                    )
                if route_text != spec.get("route"):
                    rep.fail(
                        "C5", where, f"{name}: route {route_text!r} is not {spec.get('route')!r}"
                    )
            else:
                rep.fail("C5", where, f"{name}: trigger {kind} is not allowed")
    for name in allowed:
        if name not in found:
            rep.fail("C5", shown, f"allowed function {name!r} not found")

    # banned-before-auth: direct calls, plus module functions that make such a call
    banned = {"blobs", "DefaultAzureCredential", "urlopen", "loads"}
    for _ in range(3):
        for name, node in funcs.items():
            if any(isinstance(c, ast.Call) and call_name(c) in banned for c in ast.walk(node)):
                banned.add(name)
    reenter = funcs.get("reenter")
    if reenter is not None:
        calls = sorted(
            (c.lineno, c.col_offset, call_name(c))
            for c in ast.walk(reenter)
            if isinstance(c, ast.Call)
        )
        signature = [c for c in calls if c[2] == "valid_signature"]
        early = [c for c in calls if c[2] in banned and (not signature or c[:2] < signature[0][:2])]
        if not signature:
            rep.fail("C5", f"{shown}:{reenter.lineno}", "reenter never calls valid_signature")
        for line, _, name in early:
            rep.fail("C5", f"{shown}:{line}", f"reenter calls {name}() before valid_signature()")

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and call_name(node) == "sleep":
            arg = node.args[0] if node.args else None
            if not (
                isinstance(arg, ast.Constant)
                and isinstance(arg.value, (int, float))
                and arg.value <= 5
            ):
                rep.fail(
                    "C5",
                    f"{shown}:{node.lineno}",
                    "time.sleep in function_app.py must be a constant <= 5",
                )

    stop_defaults = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and first.value == "COLLECTOR_STOP_UTC":
                default = node.args[1] if len(node.args) > 1 else None
                if isinstance(default, ast.Constant) and isinstance(default.value, str):
                    stop_defaults += 1
                    check_stop_value(rep, limits, default.value, f"{shown}:{node.lineno}", now)
                else:
                    rep.fail(
                        "C5", f"{shown}:{node.lineno}", "COLLECTOR_STOP_UTC needs a literal default"
                    )
    if not stop_defaults:
        rep.fail("C5", shown, "no COLLECTOR_STOP_UTC default found")

    for name in ("collect", "publish"):
        node = funcs.get(name)
        if node is None:
            continue
        seen = names_and_strings(node)
        for helper in [n for n in seen if n in funcs and n != name]:  # one level of helpers
            seen |= names_and_strings(funcs[helper])
        for needed in ("within_window", "COLLECTOR_DISABLED"):
            if needed not in seen:
                rep.fail("C5", f"{shown}:{node.lineno}", f"{name} does not check {needed}")


# ---------------------------------------------------------------- C6


def check_inventory(rep: Report, limits: dict, doc, where: str) -> None:
    items = doc.get("resources", doc.get("value", [])) if isinstance(doc, dict) else doc
    allowed = {t.lower() for t in limits["allowed_resource_types"]}
    for item in items:
        kind = str(item.get("type", ""))
        if kind.lower() not in allowed:
            rep.fail(
                "C6", where, f"resource type {kind!r} ({item.get('name', '?')}) is not allowed"
            )
        if kind.lower() == "microsoft.operationalinsights/workspaces":
            cap = find_key(item, "dailyQuotaGb")
            if not isinstance(cap, (int, float)) or cap > 0.5:
                rep.fail(
                    "C6",
                    where,
                    "Log Analytics workspace needs workspaceCapping.dailyQuotaGb <= 0.5",
                )


# ---------------------------------------------------------------- C7


def has_timeout(call: ast.Call) -> bool:
    for kw in call.keywords:
        if kw.arg == "timeout":
            return not (isinstance(kw.value, ast.Constant) and kw.value.value is None)
    return call_name(call) == "urlopen" and len(call.args) >= 3


def body_calls(node: ast.AST) -> list[ast.Call]:
    return [c for c in ast.walk(node) if isinstance(c, ast.Call)]


def check_code(rep: Report, limits: dict, root: Path) -> None:
    unbounded = 0
    unbounded_while = 0
    for rel in sorted(expand(root, limits["scan"]["code"])):
        shown = rel.relative_to(root).as_posix()
        try:
            tree = ast.parse(rel.read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as exc:
            raise ConfigError(f"cannot parse {shown}: {exc}") from exc
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                is_proc = (
                    isinstance(func, ast.Attribute)
                    and func.attr in SUBPROCESS_CALLS
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "subprocess"
                )
                if (is_proc or call_name(node) == "urlopen") and not has_timeout(node):
                    unbounded += 1
                if call_name(node) == "sleep" and node.args:
                    arg = node.args[0]
                    if (
                        isinstance(arg, ast.Constant)
                        and isinstance(arg.value, (int, float))
                        and arg.value > 60
                    ):
                        rep.fail(
                            "C7",
                            f"{shown}:{node.lineno}",
                            f"time.sleep({arg.value}) is longer than 60 s",
                        )
            elif (
                isinstance(node, ast.While)
                and isinstance(node.test, ast.Constant)
                and node.test.value
            ):
                inner = list(ast.walk(node))
                exits = any(isinstance(n, (ast.Break, ast.Return)) for n in inner)
                bounded = any(isinstance(n, ast.AugAssign) for n in inner) or any(
                    isinstance(n, ast.Name) and "deadline" in n.id.lower() for n in inner
                )
                if not exits or not bounded:
                    unbounded_while += 1
                    rep.fail(
                        "C7",
                        f"{shown}:{node.lineno}",
                        "while True needs an exit and a counter or deadline",
                    )
                if any(call_name(c) == "sleep" for c in body_calls(node)) and not exits:
                    rep.fail("C7", f"{shown}:{node.lineno}", "sleep inside an unbounded loop")
            elif (
                isinstance(node, ast.For)
                and isinstance(node.iter, ast.Call)
                and call_name(node.iter) == "range"
            ):
                arg = node.iter.args[-1] if node.iter.args else None
                if isinstance(arg, ast.Constant) and isinstance(arg.value, int) and arg.value > 5:
                    names = {call_name(c) for c in body_calls(node)}
                    if names & (NETWORK_CALLS | SUBPROCESS_CALLS):
                        rep.fail(
                            "C7",
                            f"{shown}:{node.lineno}",
                            f"retry loop of {arg.value} (> 5) around a network or process call",
                        )
    ratchet = limits["ratchet"]
    rep.info.append(
        f"unbounded subprocess/urlopen calls: {unbounded} "
        f"(ratchet {ratchet['unbounded_subprocess']})"
    )
    if unbounded > ratchet["unbounded_subprocess"]:
        rep.fail(
            "C7",
            "scan.code",
            f"{unbounded} calls without timeout= exceed the ratchet "
            f"{ratchet['unbounded_subprocess']}",
        )
    if unbounded_while > ratchet["unbounded_while"]:
        rep.fail(
            "C7",
            "scan.code",
            f"{unbounded_while} unbounded while loops exceed the ratchet "
            f"{ratchet['unbounded_while']}",
        )

    patterns = {
        "ghp_": r"ghp_[A-Za-z0-9]{20,}",
        "github_pat_": r"github_pat_[A-Za-z0-9_]{20,}",
        "da2-": r"da2-[a-z0-9]{20,}",
        "AccountKey=": r"AccountKey=[^\s\"']{8,}",
        "sig=": r"[?&]sig=[A-Za-z0-9%]{16,}",
    }
    allow = limits["scan"].get("secret_allowlist", {})
    for rel in sorted(expand(root, limits["scan"]["text"])):
        shown = rel.relative_to(root).as_posix()
        if shown == "tools/cost_guard.py" or not rel.is_file():
            continue
        try:
            text = rel.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for label, pattern in patterns.items():
            if shown in allow.get(label, []):
                continue
            for match in re.finditer(pattern, text):
                line = text.count("\n", 0, match.start()) + 1
                rep.fail("C7", f"{shown}:{line}", f"looks like a secret ({label})")


def expand(root: Path, globs: list[str]) -> set[Path]:
    out: set[Path] = set()
    for pattern in globs:
        out.update(p for p in root.glob(pattern) if p.is_file() and "__pycache__" not in p.parts)
    return out


# ---------------------------------------------------------------- C8


def top_block(lines: list[str], key: str) -> list[str]:
    """Lines of the top-level `key:` block (until the next column-0 key)."""
    out, inside = [], False
    for line in lines:
        if re.match(rf"^{re.escape(key)}:", line):
            inside = True
            out.append(line)
        elif inside and line and not line[0].isspace() and not line.startswith("#"):
            break
        elif inside:
            out.append(line)
    return out


def check_workflows(rep: Report, limits: dict, root: Path) -> None:
    cfg = limits["workflows"]
    total_cron = 0
    directory = root / ".github" / "workflows"
    for path in sorted([*directory.glob("*.yml"), *directory.glob("*.yaml")]):
        shown = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        live = [(i + 1, ln) for i, ln in enumerate(lines) if not ln.lstrip().startswith("#")]
        trigger = top_block(lines, "on") or top_block(lines, "'on'") or top_block(lines, '"on"')
        trigger_text = "\n".join(trigger)

        # jobs and their timeouts
        jobs_block = top_block(lines, "jobs")
        names = [
            (i, m.group(1))
            for i, ln in enumerate(jobs_block)
            if (m := re.match(r"^  ([\w-]+):\s*$", ln))
        ]
        for n, (start, name) in enumerate(names):
            end = names[n + 1][0] if n + 1 < len(names) else len(jobs_block)
            block = "\n".join(jobs_block[start:end])
            match = re.search(r"^\s{4}timeout-minutes:\s*(\S+)", block, re.M)
            if not match or not match.group(1).isdigit():
                rep.fail("C8", shown, f"job {name!r} needs a numeric timeout-minutes")
            elif int(match.group(1)) > cfg["max_job_timeout_min"]:
                rep.fail(
                    "C8",
                    shown,
                    f"job {name!r} timeout-minutes {match.group(1)} > {cfg['max_job_timeout_min']}",
                )

        pushes = any(
            re.search(r"git push|git commit|--git\b|commit_entries\.sh", ln) for _, ln in live
        )
        if pushes:
            concurrency = "\n".join(top_block(lines, "concurrency")) or text
            if "concurrency:" not in text or not re.search(
                r"cancel-in-progress:\s*false", concurrency
            ):
                rep.fail(
                    "C8",
                    shown,
                    "a workflow that pushes needs concurrency with cancel-in-progress: false",
                )
            if re.search(r"^\s+push:", trigger_text, re.M) and "paths:" not in trigger_text:
                rep.fail("C8", shown, "on: push without paths: and a pushing step can loop")

        stem = path.name
        for number, ln in live:
            match = re.search(r"gh workflow run\s+([\w./-]+)", ln)
            if (
                match
                and Path(match.group(1)).name == stem
                and stem not in cfg["self_dispatch_workflows"]
            ):
                rep.fail("C8", f"{shown}:{number}", "workflow dispatches itself")
        if (
            re.search(r"^\s+workflow_run:", trigger_text, re.M)
            and stem not in cfg["workflow_run_allowed"]
        ):
            rep.fail("C8", shown, "workflow_run trigger is not allowed here")
        if re.search(r"^\s+issues:", trigger_text, re.M):
            owner_guard = "github.event.issue.user.login == github.repository_owner" in text
            title_guard = re.search(r"startsWith\([^)]*title", text) is not None
            if not (owner_guard and title_guard):
                rep.fail(
                    "C8",
                    shown,
                    "an issues workflow needs the owner check and a startsWith(title) guard",
                )

        for number, ln in live:
            match = re.search(r"cron:\s*[\"']([^\"']+)[\"']", ln)
            if match:
                total_cron += fires_per_day(match.group(1))
            if re.search(
                r"""title["']?\s*[:=]\s*["'](reenter|remove)|--title\s+["'](reenter|remove)""",
                ln,
                re.I,
            ):
                rep.fail(
                    "C8",
                    f"{shown}:{number}",
                    "an issue title starting reenter/remove would trigger the webhook",
                )
    rep.info.append(
        f"workflow cron firings/day: {total_cron} (limit {cfg['max_cron_fires_per_day']})"
    )
    if total_cron > cfg["max_cron_fires_per_day"]:
        rep.fail(
            "C8",
            ".github/workflows",
            f"cron fires {total_cron}/day, limit {cfg['max_cron_fires_per_day']}",
        )


# ---------------------------------------------------------------- C10


GRANT_PATHS = ("function.allowed_functions", "workflows.workflow_run_allowed")


def loosened(old, new, path: str = "") -> list[str]:
    out: list[str] = []
    if isinstance(old, bool) or isinstance(new, bool):
        return out
    if isinstance(old, dict) and isinstance(new, dict):
        for key, value in new.items():
            sub = f"{path}.{key}" if path else key
            if key not in old:
                if path in GRANT_PATHS:
                    out.append(f"{sub} was added")
                continue
            out.extend(loosened(old[key], value, sub))
    elif isinstance(old, list) and isinstance(new, list):
        added = [x for x in new if x not in old]
        if added:
            out.append(f"{path} gained {added!r}")
    elif isinstance(old, (int, float)) and isinstance(new, (int, float)) and new > old:
        out.append(f"{path} raised from {old} to {new}")
    return out


def base_limits(root: Path, args) -> dict | None:
    if args.base_file:
        return load_json(Path(args.base_file))
    try:
        shown = subprocess.run(
            ["git", "-C", str(root), "show", f"{args.base_ref}:azure/limits.json"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return json.loads(shown.stdout) if shown.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


# ---------------------------------------------------------------- live exports


def check_live(rep: Report, limits: dict, files: list[str], now: dt.datetime) -> None:
    for name in files:
        path = Path(name)
        doc = load_json(path)
        lowered = path.name.lower()
        if "appsettings" in lowered or "settings" in lowered:
            entries = doc if isinstance(doc, list) else doc.get("value", [])
            names = [e["name"] if isinstance(e, dict) else str(e) for e in entries]
            for forbidden in limits["function"]["forbidden_app_settings"]:
                if forbidden in names:
                    rep.fail("C4", name, f"live app setting {forbidden} adds uncapped logging cost")
            for entry in entries:
                if (
                    isinstance(entry, dict)
                    and entry.get("name") == "COLLECTOR_STOP_UTC"
                    and "value" in entry
                ):
                    check_stop_value(rep, limits, entry["value"], name, now)
        elif "inventory" in lowered or "resource" in lowered:
            check_inventory(rep, limits, doc, name)
        else:
            check_scale(rep, limits, read_scale(doc), name)


# ---------------------------------------------------------------- main


def run(args) -> Report:
    root = Path(args.root).resolve()
    limits_path = Path(args.limits) if args.limits else root / "azure" / "limits.json"
    if not limits_path.is_absolute():
        limits_path = root / limits_path
    limits = load_json(limits_path)
    now = parse_utc(args.now) if args.now else dt.datetime.now(dt.UTC)
    rep = Report()
    package = root / "azure" / "function"

    host = load_json(package / "host.json")
    timeout_s = check_host(rep, limits, host, "azure/function/host.json")
    app = load_json(package / "app.json")
    scale = read_scale(app)
    check_scale(rep, limits, scale, "azure/function/app.json")
    stop = ((app.get("appSettings") or {}).get("values") or {}).get("COLLECTOR_STOP_UTC")
    if stop is not None:
        check_stop_value(rep, limits, stop, "azure/function/app.json", now)

    memory = (
        scale["memory"]
        if isinstance(scale["memory"], int)
        else limits["function"]["max_instance_memory_mb"]
    )
    rep.costs = function_cost(limits, timeout_s, memory)
    budget = limits["budget_usd_month"]
    if rep.costs["function_window_worst_case"] > budget["total"]:
        rep.fail(
            "C3",
            "azure/limits.json",
            f"worst-case window cost ${rep.costs['function_window_worst_case']} "
            f"> budget ${budget['total']}",
        )
    if rep.costs["function_full_scale_month"] > budget["hard_cap_function"]:
        rep.fail(
            "C3",
            "azure/limits.json",
            f"full-scale month ${rep.costs['function_full_scale_month']} "
            f"> hard cap ${budget['hard_cap_function']}",
        )

    check_function_app(
        rep, limits, package / "function_app.py", "azure/function/function_app.py", now
    )
    check_inventory(
        rep, limits, load_json(root / "azure" / "inventory.json"), "azure/inventory.json"
    )
    check_code(rep, limits, root)
    check_workflows(rep, limits, root)

    base = base_limits(root, args)
    if base is not None and os.environ.get("LIMITS_APPROVED") != "1":
        for message in loosened(base, limits):
            rep.fail("C10", "azure/limits.json", f"loosened: {message}")
    check_live(rep, limits, args.live or [], now)
    return rep


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--limits")
    parser.add_argument(
        "--live", action="append", help="live export (functionapp, appsettings or inventory JSON)"
    )
    parser.add_argument("--now", help="ISO timestamp used instead of the clock")
    parser.add_argument(
        "--base-ref", default="origin/main", help="git ref holding the previous azure/limits.json"
    )
    parser.add_argument("--base-file", help="previous limits file (instead of --base-ref)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        rep = run(args)
    except (ConfigError, KeyError, TypeError) as exc:
        print(f"cost_guard: configuration error: {exc!r}", file=sys.stderr)
        return 2
    if args.json:
        print(
            json.dumps(
                {"violations": rep.violations, "info": rep.info, "costs_usd": rep.costs}, indent=2
            )
        )
    else:
        for rule, where, message in rep.violations:
            print(f"{rule} {where} {message}")
        for line in rep.info:
            print(f"info: {line}")
        for name, value in rep.costs.items():
            print(f"cost: {name} ${value:.2f}")
        print(f"cost_guard: {len(rep.violations)} violation(s)")
    return 1 if rep.violations else 0


if __name__ == "__main__":
    sys.exit(main())
