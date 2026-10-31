"""tools/cost_guard.py: passes on the repo as delivered, and each rule has a failing fixture."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tools import cost_guard

REPO = Path(__file__).resolve().parents[1]
NOW = "2026-10-31T00:00:00Z"
WORKFLOW = """name: x
on:
  workflow_dispatch: {}
jobs:
  one:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - run: echo hi
"""


def guard(root: Path, capsys, *extra: str) -> tuple[int, str]:
    code = cost_guard.main(["--root", str(root), "--now", NOW, "--base-ref", "no-such-ref", *extra])
    return code, capsys.readouterr().out


@pytest.fixture
def tree(tmp_path):
    """A copy of the files the guard reads, ready to be broken one rule at a time."""
    shutil.copytree(
        REPO / "azure", tmp_path / "azure", ignore=shutil.ignore_patterns("__pycache__")
    )
    (tmp_path / "tools").mkdir()
    shutil.copy(REPO / "tools" / "live_collector.py", tmp_path / "tools")
    shutil.copytree(REPO / ".github" / "workflows", tmp_path / ".github" / "workflows")
    return tmp_path


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text, old
    path.write_text(text.replace(old, new, 1))


def edit_json(path: Path, change) -> None:
    doc = json.loads(path.read_text())
    change(doc)
    path.write_text(json.dumps(doc))


def expect(root, capsys, rule, *extra):
    code, out = guard(root, capsys, *extra)
    assert code == 1, out
    assert any(line.startswith(f"{rule} ") for line in out.splitlines()), out
    return out


# ------------------------------------------------------------------ as delivered


def test_the_repo_passes_as_delivered(capsys):
    code, out = guard(REPO, capsys)
    assert code == 0, out
    assert "cost: function_window_worst_case" in out


def test_copy_of_the_repo_passes(tree, capsys):
    assert guard(tree, capsys)[0] == 0


def test_json_output_and_config_error(tree, capsys):
    code, out = guard(tree, capsys, "--json")
    assert code == 0 and json.loads(out)["violations"] == []
    (tree / "azure" / "limits.json").write_text("{")
    assert guard(tree, capsys)[0] == 2


def test_cron_arithmetic():
    assert cost_guard.fires_per_day("0 * * * * *") == 1440
    assert cost_guard.fires_per_day("0 7 * * * *") == 24
    assert cost_guard.fires_per_day("*/20 * * * *") == 72
    assert cost_guard.fires_per_day("0 0 29 2 *") == 1
    with pytest.raises(cost_guard.ConfigError):
        cost_guard.fires_per_day("@daily")


# ------------------------------------------------------------------ C3


def test_c3_budget(tree, capsys):
    edit_json(tree / "azure/limits.json", lambda d: d["budget_usd_month"].update(total=1))
    expect(tree, capsys, "C3")


def test_c3_full_scale_cap(tree, capsys):
    edit_json(
        tree / "azure/limits.json", lambda d: d["budget_usd_month"].update(hard_cap_function=5)
    )
    expect(tree, capsys, "C3")


# ------------------------------------------------------------------ C4


@pytest.mark.parametrize("timeout", ["-1", "00:05:00", "", "55"])
def test_c4_function_timeout(tree, capsys, timeout):
    host = tree / "azure/function/host.json"
    edit_json(host, lambda d: d.update(functionTimeout=timeout))
    expect(tree, capsys, "C4")


def test_c4_missing_function_timeout(tree, capsys):
    edit_json(tree / "azure/function/host.json", lambda d: d.pop("functionTimeout"))
    expect(tree, capsys, "C4")


@pytest.mark.parametrize("key", ["maxConcurrentRequests", "maxOutstandingRequests"])
def test_c4_http_throttles(tree, capsys, key):
    host = tree / "azure/function/host.json"
    edit_json(host, lambda d: d["extensions"]["http"].pop(key))
    expect(tree, capsys, "C4")
    edit_json(host, lambda d: d["extensions"]["http"].update({key: 500}))
    expect(tree, capsys, "C4")


def test_c4_sampling_off(tree, capsys):
    host = tree / "azure/function/host.json"
    edit_json(
        host,
        lambda d: d["logging"]["applicationInsights"]["samplingSettings"].update(isEnabled=False),
    )
    expect(tree, capsys, "C4")


@pytest.mark.parametrize(
    "key,value",
    [("maximumInstanceCount", 2), ("instanceMemoryMB", 2048), ("alwaysReady", [{"name": "http"}])],
)
def test_c4_scale(tree, capsys, key, value):
    def change(doc):
        doc["properties"]["functionAppConfig"]["scaleAndConcurrency"][key] = value

    edit_json(tree / "azure/function/app.json", change)
    expect(tree, capsys, "C4")


def test_c4_live_drift(tree, capsys):
    live = tree / "functionapp.json"
    ok = {
        "properties": {
            "functionAppConfig": {
                "scaleAndConcurrency": {"maximumInstanceCount": 1, "instanceMemoryMB": 512}
            }
        }
    }
    live.write_text(json.dumps(ok))
    assert guard(tree, capsys, "--live", str(live))[0] == 0
    ok["properties"]["functionAppConfig"]["scaleAndConcurrency"]["instanceMemoryMB"] = 2048
    live.write_text(json.dumps(ok))
    expect(tree, capsys, "C4", "--live", str(live))
    live.write_text("{}")  # scale not visible in the export: cannot be proven, so it fails
    expect(tree, capsys, "C4", "--live", str(live))


def test_c4_live_app_insights_setting(tree, capsys):
    live = tree / "appsettings.json"
    live.write_text(json.dumps([{"name": "GITHUB_TOKEN"}]))
    assert guard(tree, capsys, "--live", str(live))[0] == 0
    live.write_text(json.dumps([{"name": "APPLICATIONINSIGHTS_CONNECTION_STRING"}]))
    expect(tree, capsys, "C4", "--live", str(live))


# ------------------------------------------------------------------ C5


def app(tree) -> Path:
    return tree / "azure/function/function_app.py"


def test_c5_unknown_function(tree, capsys):
    app(tree).write_text(
        app(tree).read_text() + '\n\n@app.route(route="x")\ndef extra(req):\n    return None\n'
    )
    expect(tree, capsys, "C5")


def test_c5_timer_rate(tree, capsys):
    edit(app(tree), 'schedule="0 7 * * * *"', 'schedule="* * * * * *"')
    expect(tree, capsys, "C5")


def test_c5_anonymous_on_the_wrong_route(tree, capsys):
    edit(app(tree), 'route="github/reenter"', 'route="github/other"')
    expect(tree, capsys, "C5")


def test_c5_app_wide_anonymous_default(tree, capsys):
    edit(
        app(tree),
        "app = func.FunctionApp()",
        "app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)",
    )
    expect(tree, capsys, "C5")


def test_c5_work_before_the_signature_check(tree, capsys):
    edit(app(tree), "    body = req.get_body()\n", "    body = req.get_body()\n    blobs()\n")
    out = expect(tree, capsys, "C5")
    assert "before valid_signature" in out


def test_c5_work_before_the_signature_check_through_a_helper(tree, capsys):
    edit(
        app(tree),
        "    body = req.get_body()\n",
        "    body = req.get_body()\n    take_start_slot(None)\n",
    )
    expect(tree, capsys, "C5")


def test_c5_sleep(tree, capsys):
    edit(
        app(tree),
        "def now_utc()",
        "def nap():\n    import time\n\n    time.sleep(30)\n\n\ndef now_utc()",
    )
    expect(tree, capsys, "C5")


def test_c5_stop_date_too_far(tree, capsys):
    edit(app(tree), '"2026-11-07T13:00:00Z"', '"2027-06-01T00:00:00Z"')
    expect(tree, capsys, "C5")


def test_c5_stop_value_in_app_json(tree, capsys):
    def change(doc):
        doc["appSettings"]["values"]["COLLECTOR_STOP_UTC"] = "2027-06-01T00:00:00Z"

    edit_json(tree / "azure/function/app.json", change)
    expect(tree, capsys, "C5")


@pytest.mark.parametrize("name", ["collect", "publish"])
def test_c5_timers_must_check_the_window(tree, capsys, name):
    text = app(tree).read_text()
    head, _, tail = text.partition(f"def {name}(")
    first = (
        "window_open(now_utc())" if name == "collect" else "window_open(moment, PUBLISH_GRACE_S)"
    )
    assert first in tail
    app(tree).write_text(head + f"def {name}(" + tail.replace(first, "True", 1))
    expect(tree, capsys, "C5")


# ------------------------------------------------------------------ C6


def test_c6_new_resource_type(tree, capsys):
    def change(doc):
        doc["resources"].append({"name": "law", "type": "Microsoft.OperationalInsights/workspaces"})

    edit_json(tree / "azure/inventory.json", change)
    expect(tree, capsys, "C6")


def test_c6_live_inventory(tree, capsys):
    live = tree / "inventory.json"
    live.write_text(json.dumps([{"name": "a", "type": "microsoft.web/sites"}]))
    assert guard(tree, capsys, "--live", str(live))[0] == 0
    live.write_text(json.dumps([{"name": "fd", "type": "Microsoft.Cdn/profiles"}]))
    expect(tree, capsys, "C6", "--live", str(live))


def test_c6_log_analytics_needs_a_daily_cap(tree, capsys):
    edit_json(
        tree / "azure/limits.json",
        lambda d: d["allowed_resource_types"].append("Microsoft.OperationalInsights/workspaces"),
    )

    def change(doc):
        doc["resources"].append({"name": "law", "type": "Microsoft.OperationalInsights/workspaces"})

    edit_json(tree / "azure/inventory.json", change)
    expect(tree, capsys, "C6")


# ------------------------------------------------------------------ C7


def extra(tree, text, name="extra.py") -> None:
    (tree / "azure/function" / name).write_text(text)


def test_c7_unbounded_call_ratchet(tree, capsys):
    extra(tree, "import subprocess\n\nsubprocess.run(['x'])\n")
    expect(tree, capsys, "C7")


def test_c7_urlopen_without_timeout(tree, capsys):
    extra(tree, "import urllib.request\n\nurllib.request.urlopen('https://x')\n")
    expect(tree, capsys, "C7")


def test_c7_while_true(tree, capsys):
    extra(tree, "while True:\n    pass\n")
    expect(tree, capsys, "C7")
    extra(tree, "while True:\n    break\n")  # an exit but no counter or deadline
    expect(tree, capsys, "C7")


def test_c7_sleep_over_a_minute(tree, capsys):
    extra(tree, "import time\n\ntime.sleep(120)\n")
    expect(tree, capsys, "C7")


def test_c7_retry_loop_too_long(tree, capsys):
    extra(
        tree,
        "import urllib.request\n\nfor _ in range(9):\n    urllib.request.urlopen('x', timeout=5)\n",
    )
    expect(tree, capsys, "C7")


@pytest.mark.parametrize(
    "secret",
    ["ghp_" + "a" * 30, "github_pat_" + "B" * 30, "AccountKey=" + "k" * 20, "?sig=" + "z" * 24],
)
def test_c7_secrets(tree, capsys, secret):
    extra(tree, f"x = '{secret}'\n", "notes.txt")
    expect(tree, capsys, "C7")


def test_c7_racing_public_key_is_allowed_only_in_the_collector(tree, capsys):
    assert "da2-" in (tree / "tools/live_collector.py").read_text()
    assert guard(tree, capsys)[0] == 0
    extra(tree, "KEY = 'da2-" + "x" * 24 + "'\n", "notes.txt")
    expect(tree, capsys, "C7")


# ------------------------------------------------------------------ C8


def workflow(tree, name, text) -> None:
    (tree / ".github/workflows" / name).write_text(text)


def test_c8_valid_workflow_passes(tree, capsys):
    workflow(tree, "ok.yml", WORKFLOW)
    assert guard(tree, capsys)[0] == 0


def test_c8_job_without_timeout(tree, capsys):
    workflow(tree, "bad.yml", WORKFLOW.replace("    timeout-minutes: 5\n", ""))
    expect(tree, capsys, "C8")


def test_c8_timeout_too_long(tree, capsys):
    workflow(tree, "bad.yml", WORKFLOW.replace("timeout-minutes: 5", "timeout-minutes: 999"))
    expect(tree, capsys, "C8")


def test_c8_pushing_without_concurrency(tree, capsys):
    workflow(tree, "bad.yml", WORKFLOW.replace("echo hi", "git push origin HEAD"))
    expect(tree, capsys, "C8")
    cancelling = "concurrency:\n  group: g\n  cancel-in-progress: true\njobs:"
    workflow(
        tree,
        "bad.yml",
        WORKFLOW.replace("jobs:", cancelling).replace("echo hi", "git push origin HEAD"),
    )
    expect(tree, capsys, "C8")


def test_c8_push_trigger_without_paths_and_a_pushing_step(tree, capsys):
    text = WORKFLOW.replace("  workflow_dispatch: {}", "  push:\n    branches: [main]")
    text = text.replace("jobs:", "concurrency:\n  group: g\n  cancel-in-progress: false\njobs:")
    workflow(tree, "bad.yml", text.replace("echo hi", "git push origin HEAD"))
    expect(tree, capsys, "C8")


def test_c8_self_dispatch(tree, capsys):
    workflow(tree, "loop.yml", WORKFLOW.replace("echo hi", "gh workflow run loop.yml"))
    expect(tree, capsys, "C8")


def test_c8_workflow_run_trigger(tree, capsys):
    workflow(
        tree,
        "chain.yml",
        WORKFLOW.replace("  workflow_dispatch: {}", "  workflow_run:\n    workflows: [a]"),
    )
    expect(tree, capsys, "C8")


def test_c8_issues_workflow_needs_guards(tree, capsys):
    text = WORKFLOW.replace("  workflow_dispatch: {}", "  issues:\n    types: [opened]")
    workflow(tree, "issue.yml", text)
    expect(tree, capsys, "C8")
    guarded = text.replace(
        "    runs-on",
        "    if: github.event.issue.user.login == github.repository_owner"
        " && startsWith(github.event.issue.title, 'x')\n    runs-on",
    )
    workflow(tree, "issue.yml", guarded)
    assert guard(tree, capsys)[0] == 0


def test_c8_cron_volume(tree, capsys):
    workflow(
        tree,
        "busy.yml",
        WORKFLOW.replace("  workflow_dispatch: {}", '  schedule:\n    - cron: "* * * * *"'),
    )
    expect(tree, capsys, "C8")


def test_c8_issue_title_that_would_trigger_the_webhook(tree, capsys):
    workflow(
        tree, "loop.yml", WORKFLOW.replace("echo hi", 'gh issue create --title "Reenter: all"')
    )
    expect(tree, capsys, "C8")


# ------------------------------------------------------------------ C11


def webapp(tree) -> Path:
    return tree / "azure/webapp/melbcup-web.json"


def spec_edit(tree, change) -> None:
    edit_json(webapp(tree), lambda d: change(d))


def test_c11_spec_passes_and_is_priced(tree, capsys):
    code, out = guard(tree, capsys, "--json")
    assert code == 0, out
    costs = json.loads(out)["costs_usd"]
    # (0.25 * 2592000 - 180000) * 0.000024 + (0.5 * 2592000 - 360000) * 0.000003 = 11.232 + 2.808
    assert costs["container_app_worst_case_month"] == 14.04
    assert costs["total_worst_case"] == round(costs["function_window_worst_case"] + 14.04, 2)


def test_c11_total_must_fit_the_budget(tree, capsys):
    edit_json(tree / "azure/limits.json", lambda d: d["budget_usd_month"].update(total=20))
    out = expect(tree, capsys, "C3")
    assert "container app" in out


def test_c11_missing_spec(tree, capsys):
    webapp(tree).unlink()
    expect(tree, capsys, "C11")


@pytest.mark.parametrize("minimum", [1, None, "0"])
def test_c11_min_replicas(tree, capsys, minimum):
    def change(doc):
        if minimum is None:
            doc["template"]["scale"].pop("minReplicas")
        else:
            doc["template"]["scale"]["minReplicas"] = minimum

    spec_edit(tree, change)
    expect(tree, capsys, "C11")


@pytest.mark.parametrize("maximum", [2, 10, None])
def test_c11_max_replicas(tree, capsys, maximum):
    def change(doc):
        if maximum is None:
            doc["template"]["scale"].pop("maxReplicas")  # the platform default is 10
        else:
            doc["template"]["scale"]["maxReplicas"] = maximum

    spec_edit(tree, change)
    expect(tree, capsys, "C11")


@pytest.mark.parametrize(
    "cpu,memory",
    [(0.5, "0.5Gi"), (0.25, "1Gi"), (0.25, "1024Mi"), (0.25, "lots"), ("fast", "0.5Gi")],
)
def test_c11_container_size(tree, capsys, cpu, memory):
    def change(doc):
        doc["template"]["containers"][0]["resources"] = {"cpu": cpu, "memory": memory}

    spec_edit(tree, change)
    expect(tree, capsys, "C11")


def test_c11_second_container_counts(tree, capsys):
    def change(doc):
        extra = json.loads(json.dumps(doc["template"]["containers"][0]))
        extra["name"] = "sidecar"
        doc["template"]["containers"].append(extra)

    spec_edit(tree, change)
    expect(tree, capsys, "C11")


def test_c11_smaller_sizes_pass(tree, capsys):
    def change(doc):
        doc["template"]["containers"][0]["resources"] = {"cpu": 0.25, "memory": "512Mi"}

    spec_edit(tree, change)
    assert guard(tree, capsys)[0] == 0


def test_c11_dedicated_workload_profile(tree, capsys):
    spec_edit(tree, lambda d: d.update(workloadProfileName="D4"))
    expect(tree, capsys, "C11")


def test_c11_multiple_revisions(tree, capsys):
    spec_edit(tree, lambda d: d["configuration"].update(activeRevisionsMode="Multiple"))
    expect(tree, capsys, "C11")


def test_c11_insecure_external_ingress(tree, capsys):
    spec_edit(tree, lambda d: d["configuration"]["ingress"].update(allowInsecure=True))
    expect(tree, capsys, "C11")


def test_c11_insecure_internal_ingress_is_allowed(tree, capsys):
    spec_edit(
        tree,
        lambda d: d["configuration"]["ingress"].update(external=False, allowInsecure=True),
    )
    assert guard(tree, capsys)[0] == 0


def test_c11_live_export(tree, capsys):
    live = tree / "containerapp.json"
    ok = json.loads(webapp(tree).read_text())
    ok["workloadProfileName"] = None  # a Consumption-only environment reports no profile
    live.write_text(json.dumps({"name": "melbcup-web", "properties": ok}))
    assert guard(tree, capsys, "--live", str(live))[0] == 0
    ok["template"]["scale"]["minReplicas"] = 1
    live.write_text(json.dumps({"properties": ok}))
    expect(tree, capsys, "C11", "--live", str(live))
    live.write_text("{}")  # nothing visible in the export: cannot be proven, so it fails
    expect(tree, capsys, "C11", "--live", str(live))


def test_c11_allows_the_container_apps_resource_type(tree, capsys):
    live = tree / "inventory.json"
    live.write_text(json.dumps([{"name": "melbcup-web", "type": "Microsoft.App/containerApps"}]))
    assert guard(tree, capsys, "--live", str(live))[0] == 0


def test_c11_memory_units():
    assert cost_guard.parse_gib("0.5Gi") == 0.5
    assert cost_guard.parse_gib("512Mi") == 0.5
    assert cost_guard.parse_gib(1) == 1.0
    assert cost_guard.parse_gib("x") is None
    assert cost_guard.parse_gib(True) is None


# ------------------------------------------------------------------ C10


def test_c10_loosened_limits(tree, capsys):
    base = json.loads((tree / "azure/limits.json").read_text())
    base["function"]["max_function_timeout_s"] = 30
    base["budget_usd_month"]["total"] = 10
    base["allowed_resource_types"] = base["allowed_resource_types"][:-1]
    del base["function"]["allowed_functions"]["publish"]
    (tree / "base.json").write_text(json.dumps(base))
    out = expect(tree, capsys, "C10", "--base-file", str(tree / "base.json"))
    assert out.count("C10 ") >= 4


def test_c10_tightening_passes_and_approval_overrides(tree, capsys, monkeypatch):
    base = json.loads((tree / "azure/limits.json").read_text())
    base["function"]["max_instances"] = 5
    (tree / "base.json").write_text(json.dumps(base))
    assert guard(tree, capsys, "--base-file", str(tree / "base.json"))[0] == 0
    base["function"]["max_instances"] = 0
    (tree / "base.json").write_text(json.dumps(base))
    expect(tree, capsys, "C10", "--base-file", str(tree / "base.json"))
    monkeypatch.setenv("LIMITS_APPROVED", "1")
    assert guard(tree, capsys, "--base-file", str(tree / "base.json"))[0] == 0
