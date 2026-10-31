# Audit: runaway-cost and loop paths, Lotto (ACA jobs) and MELBCUP (Flex function). Read-only, 2026-10-31
Paths: R=azure/runner.py, E=workers/entrant.mjs, Q=workers/entry_queue.py, FA/CR=func/pkg/function_app.py, collector_runtime.py.
Price assumptions (approx, verify): ACA job $0.000024/vCPU-s + $0.000003/GiB-s (0.5 vCPU/1 GiB = $0.000015/s, free 180k vCPU-s/mo);
Flex on-demand ~$0.000026/GB-s (free 100k GB-s/mo), $0.40/M executions. Cron in all 4 job JSONs is the parked `0 0 29 2 *`; all are
AZURE_JOBS_DISABLED=1, so everything below is latent until cutover. Good already: replicaRetryLimit 0, parallelism 1, replicaCompletionCount 1,
push/commit retries capped at 4 with 5-20 s backoff (R:235-261, commit_entries.sh:21-32), no `while True` in R, SIGTERM handler (R:56-62).

## Highest cost / loop risks
1. **Public webhook is anonymous and scales out.** FA:126 `AuthLevel.ANONYMOUS`; no maximumInstanceCount, memory or http throttle in repo (host.json has none).
   Scenario: scanner or attacker POSTs garbage; each hit is a billed execution (401 after HMAC). Worst cost: Flex default 100 instances x 2048 MB;
   1000 req/s x 0.1 s x 2 GB = 200 GB-s/s = ~$19/h; 100 instances busy 24/7 = ~$6.7k/mo ceiling. Fix: maximumInstanceCount<=2, instanceMemoryMB 512
   (ceiling ~$67/mo), host.json `extensions.http.maxConcurrentRequests<=10, maxOutstandingRequests<=20`, access restriction to GitHub `hooks` CIDRs
   (api.github.com/meta), webhook subscribed to `issues` events only (every other event is a billed no-op 202).
2. **Replay guard is bypassable, so one valid payload starts unlimited jobs.** FA:144-150 dedupes on `X-GitHub-Delivery`, an UNSIGNED header; a captured
   body+signature replayed with fresh delivery ids passes HMAC (CR:185-187) and each call starts a 2700 s job (~$0.04 plus real competition entries,
   live ENTRANT_LIVE=1). No running-execution check (FA:152-182), so N parallel jobs race on git push and duplicate entries. Fix: dedupe on signed
   `issue.id` (blob name `issue-<id>`, create AFTER a successful start, delete on failure), refuse if an execution of the job is Running, cap 6 starts/h
   via a counter blob, and 429 beyond.
3. **Lost-log re-entry loop on entries.** R:376-394 commits the log only in `finally`; entries job replicaTimeout is 180 s (job-lotto-entries.json) while
   ENTRANT_TIMEOUT_S defaults 420 (R:65-69), so SIGKILL beats both. E:502 runs 6 Chromium contexts in 1 GiB (OOM likely, chromium.launch() has no flags, E:512).
   Scenario: OOM or kill, log not committed, next 5-min tick (R:136-142 bucket is 5 min wide, not an exact minute) re-submits the same forms, dies again.
   Cost: 288 runs/day, 120 real runs/day in rush (hourly mode, Q:256), x180 s ~ $0.32/day, but real-world duplicate entries are the harm.
   Fix: replicaTimeout<=285 with ENTRANT_TIMEOUT_S<=150 and a per-item 90 s watchdog around `one()` (E:517-535); ENTRANT_CONCURRENCY<=3; skip node when queue empty
   (E:512 launches Chromium even for 0 items); write a `.lock`/marker commit before submitting.
4. **Cron overlap multiplies runs.** ACA schedules fire regardless of a running execution. entries is 5-min cron: any replicaTimeout>=300 (e.g. someone
   "fixes" D1 by raising it to 420+) gives overlapping executions: double Chromium, double entries. `entry_due` treats minutes 5-9 as one slot (R:139), so a
   `* * * * *` typo makes 5 runs per burst slot. Fix: guard rule replicaTimeout < cron interval; a per-slot lock (blob lease or marker file) in runner.
5. **Function timeout 20 s vs 30 s request timeout, cadence throttle.** host.json:3, PKG gql timeout=30, CR:31-39. Overlong cycles are killed before upload and state
   save, so the next minute repeats the same work (cost floor 1440 x up to 20 s x memory = 57.6k GB-s/day at 2 GB = ~$1.5/day on-demand, ~$9 over the 8-day window
   for zero data). The self-throttle (CR:58-70) halves cadence exactly when slow. Fix: memory 512 MB, timeout 55 s, gql timeout 10 s, decide throttle explicitly.
6. **Timers never stop.** FA:64 collect and FA:100 publish keep firing every minute/hour after COLLECTOR_STOP_UTC (2026-11-07T13Z); collect returns early but still
   costs a cold-started invocation per minute (43k/mo). publish has no window/disable check and reads `os.environ["GITHUB_TOKEN"]` first (FA:113), failing hourly.
   Fix: disable via app setting `AzureWebJobs.collect.Disabled=1` at end (CI/guard enforces stop date <= now+10 d), delete the app after the Cup.
7. **Publish backlog is unbounded and self-sustaining.** FA:106-123 lists, downloads and merges every pending hour in memory (CR:120-123), every hour, inside a
   20 s timeout. If the PAT expires or GitHub 422s, pending/ blobs grow 1440/day, each hourly retry re-downloads them all (O(n^2) read), then OOMs at 512 MB or times out
   forever. Fix: cap 3 hours per run, oldest first, alert (App Insights alert or a failure marker) after 2 failures; idempotent path check before commit (review D5).
8. **State blob rewritten every minute and growing.** FA:58-61, 95: `last` keys embed full query text and are never pruned (review D10); cold start downloads it each minute.
   Cost is small now (1440 PUTs/day) but latency grows toward the 20 s kill (risk 5). Fix: hash keys, prune to watched races, hard limit state.json <= 256 KB (fail and reset).
9. **Self-dispatching sleeper in entries.yml.** entries.yml:73-83 sleeps up to 3 h billed (300-min timeout) then `gh workflow run entries.yml` (line 83); the cron (line 16) is
   a second starter, saved from multiplying only by `concurrency` (pending runs replaced). Free while the repo is public; if it goes private, ~24 h/day runner minutes.
   On cutover both entries.yml and Azure would run: duplicate entries (review D2). Fix: disable the workflow at cutover; guard bans new self-dispatch.
10. **workflow_run / push fan-out into site.yml.** site.yml:6-14 triggers on workflow_run [comps, entries], on push to data/**, on schedule, plus entries.yml:72 and reenter.yml:63
    dispatch it: ~3 deploys per entries run. Azure pushes to main directly (R:234), so each Azure commit triggers a Pages deploy (up to ~130/day in rush). cancel-in-progress limits
    the pile, no loop (site pushes nothing). Free if public. Fix: path filter only, drop workflow_run and redundant dispatches; batch Azure commits.
11. **comps crawl has no cap and saves only at the end.** R:275 `workers.comps` runs with no `--max` and no timeout; comps.py:159-176 appends only after the whole loop; `get`
    retries 4x with 60 s timeouts (comps.py:40-50, worst ~250 s per page) plus a billed per-page sleep (comps.py:172). A kill at 5400 s loses everything and tomorrow
    re-crawls the same backlog (~$0.08/run, bounded by replicaTimeout; the loop is the repeat). Fix: `--max 300`, `timeout=` on every step, save every 50 like source_auscomps (:123).
12. **Issue paging in jackpots.** R:318-324 up to 100 sequential pages x 45 s each (4500 s worst) exceeds jackpots replicaTimeout 1800 s and runs BEFORE the data push (R:340):
    a slow API loses the day's data. If issues exceed 10k (PRs included), dedupe misses and one duplicate issue per alert per day is created with the owner's PAT. Fix: MAX_ISSUE_PAGES<=10,
    use `search/issues?q=key in:title`, push first.
13. **Per-run clone grows with data.** R:192-209 re-clones sparse data on every run: entries/reenter pull data/comps (4.8 MB) + data/entries (0.4 MB); comps adds analysis. Draws 19 MB and
    jackpots 13 MB are cloned daily. Ingress is free, but time is billed and git history grows (56 commits now, +130/day from Azure). Fix: guard on repo-size thresholds
    (max clone MB per job in limits.json), rotate log.jsonl yearly.
14. **Unbounded subprocess steps.** No timeout on: git clone/checkout (R:192-209), workers.comps/comp_odds/skill_rank (R:275,288,289), entry_queue (R:377,426), commit_entries.sh (R:373),
    workers.reenter (R:407), draws, jackpots (R:307,334). replicaTimeout is the only backstop. Fix: timeout= on all (ratchet in the guard).
15. **Image and config drift.** Jobs use `ghcr.io/jesseallomes/lotto-project-azure:latest` (not even the new lotto-azure-runner image); Dockerfile:5,7 use floating base tags and
    Playwright pinned, Node "best guess". Every ENTRANT_PROFILE_JSON secret is mounted in all five jobs. Fix: pin `@sha256:` in jobs; limits.json lists which jobs may hold the secret.
16. **Unobservable.** No Log Analytics on the environment (azure-inventory finding 3), so a runaway is silent; adding Log Analytics unguarded creates its own cost (per-GB ingest).
    Fix: when added, workspace dailyQuotaGb<=0.5 and a Cost Management budget with action (see guard C9).
Not a loop: issue created by jobs (title "[jackpot] ...", jackpots.py:131) does not match "reenter"/"remove"; closing an issue is an `issues closed` event the handler ignores.

# Cost guard spec: `tools/cost_guard.py` (stdlib only, Python 3.12, one file, no network, no Azure calls; exit 0 pass, 1 violations, 2 config error)
Usage: `python3 tools/cost_guard.py --limits azure/limits.json [--live live.json ...] [--json]`. Output one line per violation `RULE path:line message`, then a summary
with computed worst-case $/month per job and per function. Deterministic: no clock except `--now` (default today UTC) for the stop-date rule.

## Inputs
- `azure/limits.json` (checked in, owner-approved only; CODEOWNERS on it and on the script). Keys: `prices` {aca_vcpu_s, aca_gib_s, flex_gb_s, flex_per_million_exec};
  `budget_usd_month` {total:15, hard_cap_function:70}; `jobs` {<name>: {trigger:"Schedule"|"Manual", max_runs_per_day, min_interval_min, max_replica_timeout_s, max_cpu:0.5,
  max_memory_gi:1, parallelism:1, replica_completion_count:1, replica_retry_limit:0, may_hold_secrets:[...], max_env:{ENTRANT_CONCURRENCY:3, ENTRANT_TIMEOUT_S:150}}};
  `function` {max_instances:2, max_instance_memory_mb:512, always_ready:0, max_function_timeout_s:60, allowed_functions:{collect:{timer_max_per_day:1440}, publish:{timer_max_per_day:24},
  reenter:{route:"github/reenter", anonymous:true}}, max_collect_window_days:10, max_http_concurrent:10, max_http_outstanding:20};
  `allowed_resource_types` [list]; `ratchet` {unbounded_subprocess:<current count>, unbounded_while:0, self_dispatch_workflows:["entries.yml"], workflow_run_allowed:{"site.yml":["comps","entries"]}}.
- `azure/jobs/<name>.json`: exported ARM job (the job-lotto-*.json shape: properties.configuration.{triggerType,replicaTimeout,replicaRetryLimit,scheduleTriggerConfig.{cronExpression,
  parallelism,replicaCompletionCount}}, properties.template.containers[].{image,resources,env}). Same files re-exported live by CI (`az containerapp job show`, read-only) are passed via `--live`.
- `azure/function/{host.json,function_app.py,app.json}`: app.json = exported Flex config (properties.functionAppConfig.scale.{maximumInstanceCount,alwaysReady,instanceMemoryMB},
  appSettings names and COLLECTOR_* values, sku). `azure/inventory.json` = `az resource list` names/types for the allowlist check.

## Checks (each a failing rule id)
- C1 cron: parse 5-field cron (`*`, `*/n`, `a-b`, `a-b/n`, lists, numeric only; anything else = config error) and enumerate firing minutes over 7 days; fail if runs/day > max_runs_per_day or min gap < min_interval_min.
  Parked `0 0 29 2 *` passes (0 runs counted, mark PARKED).
- C2 job envelope: triggerType must equal limits (no `Event`); replicaTimeout<=max; replicaTimeout < min cron gap in seconds (no overlap); cpu, memory<=max; parallelism==1; replicaCompletionCount==1;
  replicaRetryLimit<=1 (limits say 0); env values within max_env; image matches `@sha256:[0-9a-f]{64}` or `:sha-[0-9a-f]{40}`, never `:latest`; ENTRANT_PROFILE_JSON only on jobs in may_hold_secrets;
  entries needs ENTRANT_TIMEOUT_S+120 <= replicaTimeout.
- C3 cost model: per job runs/day x replicaTimeout x (cpu x aca_vcpu_s + mem x aca_gib_s) x 30; sum jobs + function; fail > budget_usd_month.total. Function worst case = max_instances x memGB x 2,592,000 s x flex_gb_s
  must be <= hard_cap_function.
- C4 function scale: maximumInstanceCount<=max_instances; instanceMemoryMB<=512; alwaysReady empty; host.json functionTimeout parsed (hh:mm:ss) <= max and > 0 (never "-1" or missing);
  extensions.http maxConcurrentRequests/maxOutstandingRequests present and <= limits; applicationInsights sampling enabled.
- C5 function code (ast over function_app.py): decorators found must equal allowed_functions; each timer's 6-field schedule computed per day <= timer_max_per_day; only `reenter` may be ANONYMOUS and only route `github/reenter`;
  inside `reenter`, a call to `valid_signature` must precede any call to blobs/urlopen/DefaultAzureCredential/json.loads; no `time.sleep` > 5 in function_app.py; COLLECTOR_STOP_UTC default (and app.json value) <= now + max_collect_window_days
  and parseable; `collect` and `publish` must both reference `within_window`/COLLECTOR_DISABLED (publish currently fails: intended).
- C6 resources: every `type` in inventory.json must be in allowed_resource_types; any new type (Log Analytics, Front Door, ACR, Event Hub, extra Flex plan, SWA SKU>Free) fails until the owner edits limits.json.
  If Log Analytics is allowed, workspaceCapping.dailyQuotaGb<=0.5 is required.
- C7 static code (ast for .py, regex for .mjs/.sh/.yml): (a) count calls to subprocess.run/Popen/check_*, urllib.request.urlopen, and runner `command(`/`run_soft(` lacking an explicit non-None `timeout=`;
  must be <= ratchet.unbounded_subprocess (current baseline recorded; value may only fall). (b) `while True|1` or `while (true)` with no `break`/`return` inside = fail; with break allowed only if the function has a counter
  or deadline. (c) `time.sleep` constant>60 or inside an unbounded loop in azure/, workers/, function = fail. (d) retry loops `for _ in range(N)` containing urlopen/git push/requests: N<=5.
  (e) module constants: R MAX_ISSUE_PAGES<=10; E default `max =`<=50; E CONCURRENCY default<=3; comps.run invoked in R with `--max`. (f) secrets scan: `ghp_`, `github_pat_`, `da2-` excluded only in the allow-listed collector, `AccountKey=`, `sig=`.
- C8 workflows (line scanner, no YAML lib): every job has `timeout-minutes` (<=limits); every workflow with `git push`/commit_entries.sh has `concurrency:` with cancel-in-progress false; `gh workflow run X` inside X
  only if listed in self_dispatch_workflows; `workflow_run` only per workflow_run_allowed; any workflow with both `on: push` (no `paths:`) and a pushing step fails; `issues:` workflows must carry both
  `github.event.issue.user.login == github.repository_owner` and a `startsWith(...title` guard; cron fires/day <= 300 total across workflows. Any string literal used as an issue title that begins `reenter|remove`
  (case-insensitive) fails.
- C9 budget alarm: azure/inventory.json must contain a Microsoft.Consumption/budgets (or Cost Management budget) with amount<=budget_usd_month.total x 2 and an action group; warn-only until it exists.
- C10 ratchet vs main: if `git show origin/main:azure/limits.json` parses, any numeric limit larger than main's, or any list that gained an item, is LOOSENED = fail unless env `LIMITS_APPROVED=1`
  (set only by the workflow when the PR carries the `limits-approved` label applied by the owner). Also fail if tests `python3 -m unittest tests.test_azure_runner` fail.

## CI wiring
1. New `.github/workflows/azure-guard.yml`: `on: pull_request` + `push: branches:[main]` (paths azure/**, workers/**, .github/workflows/**, tools/**) + `workflow_call`; steps: checkout (fetch-depth 2),
   `python3 tools/cost_guard.py --limits azure/limits.json`, upload JSON summary. Mark `guard` a required status check on main.
2. Every deploy path calls it first: azure-image.yml (now triggered on azure/** push) gets `jobs.guard: uses: ./.github/workflows/azure-guard.yml` and `build: needs: guard`. The Azure job/function deploy workflow
   (to be added; manual `workflow_dispatch` only, never push or webhook) runs guard, then `az containerapp job show` / `az functionapp show` read-only exports to `live/` and re-runs
   `cost_guard.py --live live/` so drift (portal edits, Codex deploys) also blocks, then deploys with `needs: guard`. Deployment is refused when exit != 0.
3. Cutover checklist enforced by guard output: entries.yml and reenter.yml disabled (`gh workflow list --all` state, optional C8b), AZURE_JOBS_DISABLED removed only after C1-C6 pass with real crons.
