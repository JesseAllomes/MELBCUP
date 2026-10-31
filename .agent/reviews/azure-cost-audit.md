# Azure cost audit (read-only), 2026-10-31
Sub "Azure subscription 1" (pay-as-you-go, no spending limit; Defender not registered). Month-to-date spend AUD 0.00
(budget currentSpend; Cost Management query not available on this sub). No public IPs, NAT, VNet, Log Analytics or App
Insights exist. Vars: `RG=rg-personal-automation-aue F=func-personal-v5ethud2i3cfq S=stpersonalv5ethud2i3cfq`

## Findings table
| Resource | Billing model (as found) | Runaway risk | Cap (command ref below) |
|---|---|---|---|
| CAE cae-personal-v5ethud2i3cfq | Consumption profile only, no Dedicated, no vnet, no log destination | Low: nothing bills idle. No logs either (blind) | none needed; if Log Analytics added use C8 |
| Container Apps (non-job) | none exist | None | n/a |
| 5 jobs lotto-* | per-second 0.5 vCPU/1 GiB while running. Cron parked `0 0 29 2 *` (draws, comps, jackpots, entries); reenter Manual. parallelism 1, completionCount 1, retryLimit 0 everywhere. Timeouts: draws 1800s, jackpots 1800s, comps 5400s, entries 180s, reenter 2700s | Medium once unparked: schedules can overlap (5-min cron vs 3-10 min runs); manual starts have no concurrency cap. Timeouts bound each run. entries timeout 180s kills 3-10 min runs (functional bug) | C2 kill switches; keep retryLimit 0; any timeout raise raises the cap |
| Function app func-... (Flex FC1) | on-demand: GB-s + executions, free grant 100k GB-s / 250k exec. alwaysReady none, maximumInstanceCount 1, instanceMemoryMB 2048, alwaysOn false, functionTimeout 20s | Low: scale limit 1 is the hard bound. 2048 MB is 4x the cost of 512 MB per second | C3 memory 512 if collector fits; C4 stop after window |
| Timers | `collect` every minute (8-day window via COLLECTOR_START/STOP_UTC, returns early outside it); `publish` hourly at :07 | After 2026-11-07T13:00Z collect still fires 1440x/day as no-ops (free but wakes instance + storage lease writes forever) | C4 disable timer after window |
| HTTP `reenter` | ANONYMOUS route, HMAC check, no IP restriction (siteConfig allow-all) | Low/Med: unauthenticated flood costs ~USD 3 per 1M requests (401s) and is bounded by 1 instance. Valid-signature path starts a job per delivery | C5 GitHub-hooks IP allowlist |
| App Insights / Log Analytics | none (no APPLICATIONINSIGHTS_CONNECTION_STRING, no workspaces) | None today. host.json sampling only matters if added | C8 if ever added |
| Storage stpersonal... | StorageV2 Standard_LRS Hot, shared key off, public blob off. Soft delete 7d (blobs+containers), no versioning, no change feed. Lifecycle: only melbcup-archive cool@30d. Used capacity ~0; 93 txns on 10-30 | collector rewrites state.json every minute (soft delete keeps every overwrite 7d); live-observations/pending relies on `publish` deleting; webhook-replays (1-byte blobs) never deleted. All small | C6 lifecycle + C7 soft-delete 1d |
| Key Vault kv-personal-v5ethud2i3cf | Standard, RBAC, 5 secrets, soft delete 7d, no HSM keys | Negligible: ~USD 0.03/10k ops; 3 secrets read per job start | none |
| AI Services jesseallomes-6864-resource | S0 (pay per use), kind AIServices, 0 deployments, no commitment plan, no connections, project only. API keys enabled (disableLocalAuth=false), public access on | Nil now (no deployment = no spend). Risk is a leaked key or a future model deployment/Provisioned throughput | C9 disable keys; keep 0 deployments |
| SWA x2 (swa-melbcup, swa-lotto) | Free tier | None (Free has hard bandwidth limits, no overage) | none |
| User identity, serverFarm | free / the FC1 plan above | None | none |
| Budget personal-automation-aud20-ceiling | AUD 20/month, 2026-10..2036. Thresholds are percent: 5/15/50/100% = AUD 1/3/10/20. Emails jesseallomes@gmail.com only. Actual cost only, no forecast, no action group | It alerts, it never stops anything. srsinc address absent | C1 |
| Roles | Function identity: custom Job Starter on the RG, Blob/Queue/Table data, KV Secrets User | Job Starter on whole RG lets the function start any job | acceptable; scope to reenter job if desired |

## Commands
```bash
export AZURE_CONFIG_DIR=<scratchpad>/azcfg; AZ=<scratchpad>/azvenv/bin/az; SUB=78e367c0-cd4d-4334-8c02-69fa04c8bffd
# C1 budget AUD 20 with alerts at AUD 5/10/20 actual + 20 forecast, both emails (PUT replaces same-named budget)
$AZ rest --method put --url "https://management.azure.com/subscriptions/$SUB/providers/Microsoft.Consumption/budgets/personal-automation-aud20-ceiling?api-version=2023-05-01" --body '{"properties":{"category":"Cost","amount":20,"timeGrain":"Monthly","timePeriod":{"startDate":"2026-10-01T00:00:00Z","endDate":"2036-10-01T00:00:00Z"},"notifications":{"a5":{"enabled":true,"operator":"GreaterThanOrEqualTo","threshold":25,"thresholdType":"Actual","contactEmails":["jallomes@srsinc.com.au","jesseallomes@gmail.com"]},"a10":{"enabled":true,"operator":"GreaterThanOrEqualTo","threshold":50,"thresholdType":"Actual","contactEmails":["jallomes@srsinc.com.au","jesseallomes@gmail.com"]},"a20":{"enabled":true,"operator":"GreaterThanOrEqualTo","threshold":100,"thresholdType":"Actual","contactEmails":["jallomes@srsinc.com.au","jesseallomes@gmail.com"]},"f20":{"enabled":true,"operator":"GreaterThanOrEqualTo","threshold":100,"thresholdType":"Forecasted","contactEmails":["jallomes@srsinc.com.au","jesseallomes@gmail.com"]}}}}'
# C2 kill switches (jobs): re-park a job, stop a run, or flip the env flag the worker already honours
$AZ containerapp job update -g $RG -n lotto-entries --cron-expression "0 0 29 2 *"
$AZ containerapp job execution list -g $RG -n lotto-entries -o table ; $AZ containerapp job stop -g $RG -n lotto-entries --job-execution-name <name>
$AZ containerapp job update -g $RG -n lotto-entries --set-env-vars ENTRIES_DISABLED=1
# C3 function memory (only after confirming collector peak RSS < ~400 MB); max instances already 1, alwaysReady none
$AZ functionapp scale config set -g $RG -n $F --instance-memory 512 --maximum-instance-count 1
# C4 stop collector no-op wakeups after the window (run after 2026-11-07T13:00Z); panic stop: COLLECTOR_DISABLED=1
$AZ functionapp config appsettings set -g $RG -n $F --settings AzureWebJobs.collect.Disabled=true
# C5 webhook allowlist: GitHub hook CIDRs (adds implicit deny-all; do both IPv4 and IPv6 from /meta; also check SCM rule)
for ip in $(curl -s https://api.github.com/meta | python3 -c "import sys,json;print(' '.join(json.load(sys.stdin)['hooks']))"); do $AZ functionapp config access-restriction add -g $RG -n $F --rule-name gh-$RANDOM --action Allow --ip-address $ip --priority 100; done
# C6 lifecycle (replaces whole policy, so existing melbcup-archive rule is kept) + C7 soft delete 1 day
cat > lc.json <<'J'
{"rules":[{"name":"cool-melbcup-archive-after-30-days","enabled":true,"type":"Lifecycle","definition":{"filters":{"blobTypes":["blockBlob"],"prefixMatch":["melbcup-archive/"]},"actions":{"baseBlob":{"tierToCool":{"daysAfterModificationGreaterThan":30}}}}},
{"name":"purge-webhook-replays-7d","enabled":true,"type":"Lifecycle","definition":{"filters":{"blobTypes":["blockBlob"],"prefixMatch":["webhook-replays/"]},"actions":{"baseBlob":{"delete":{"daysAfterModificationGreaterThan":7}}}}},
{"name":"purge-stale-pending-3d","enabled":true,"type":"Lifecycle","definition":{"filters":{"blobTypes":["blockBlob"],"prefixMatch":["live-observations/pending/"]},"actions":{"baseBlob":{"delete":{"daysAfterModificationGreaterThan":3}}}}}]}
J
$AZ storage account management-policy create -g $RG --account-name $S --policy @lc.json
$AZ storage account blob-service-properties update -g $RG --account-name $S --enable-delete-retention true --delete-retention-days 1
# C8 only if App Insights / Log Analytics is ever added: cap 0.1 GB/day, 30d retention, 5% sampling
$AZ monitor log-analytics workspace create -g $RG -n law-personal --quota 0.1 --retention-time 30 --sku PerGB2018
$AZ monitor app-insights component update -g $RG --app <ai-name> --cap 0.1 --stop-sending-notification-when-hit-cap false
# C9 Foundry: kill API keys, confirm zero deployments
$AZ resource update --ids $($AZ cognitiveservices account show -g rg-jesseallomes-9487 -n jesseallomes-6864-resource --query id -o tsv) --set properties.disableLocalAuth=true
$AZ cognitiveservices account deployment list -g rg-jesseallomes-9487 -n jesseallomes-6864-resource   # must stay []
```
NB: a pay-as-you-go sub has no native hard cap. Budgets only email; the real stops are max instance 1, job timeouts, parking cron and C2.

## Monthly cost estimate, planned steady state (assumptions stated; USD list prices, AUD ~ USD x1.5)
Container Apps Consumption: USD 0.000024/vCPU-s + 0.000003/GiB-s. At 0.5 vCPU/1 GiB = USD 0.054/hour. Monthly free grant per
subscription 180k vCPU-s + 360k GiB-s + 2M requests = exactly 100 hours of this job size. Jobs bill active seconds incl. image pull.
| Scenario (30 days) | Job-hours | Basis | Billed beyond grant |
|---|---|---|---|
| Typical | ~98 h | draws 1.5 + jackpots 1 + comps 22.5 (45 min avg) + reenter 1 + entries 72 (2 h burst/day, 12 runs/h x 6 min) | ~USD 0 (AUD 0) |
| High | ~290 h | comps 90 min daily = 45, entries 4 h burst/day x 12 runs/h x 10 min = 240, others 4 | 190 h = USD 10 (AUD ~15) |
| Hard ceiling if cron left on 24/7 | ~480 h | entries every 5 min x 180s timeout = 432 h + others | USD 20 (AUD ~31) |
Entries runs longer than 5 min overlap the next trigger, so concurrency doubles but cost equals job-hours (already counted).
Functions Flex (on-demand): USD 0.000026/GB-s + USD 0.40/1M exec; free 100k GB-s + 250k exec per month per subscription.
Collector 8 days = 11.5k timer runs + 192 publish + a few webhooks (~12k exec, free). At 2 GB: 3 s avg = ~70k GB-s (free);
10 s avg = 230k GB-s = ~USD 3.4 (AUD 5). At 512 MB the same loads are 17k / 58k GB-s, both free. After the window, no-op wakeups
cost ~0 compute. Assumes 1 s minimum billing per run and no always-ready instances (none configured).
Storage: ~10-30k txns/day during the 8 days (state.json PUT + observation PUTs + timer lease/host blobs), ~USD 0.065/10k writes
=> under USD 1 total; capacity ~1 GB peak at USD 0.02/GB. Idle days ~100 txns. KV < USD 0.05. SWA/Foundry/identity 0.
| Total/month | Typical | High | Worst-case ceiling |
|---|---|---|---|
| AUD | ~1-3 | ~20-25 | ~40-45 |
Current AUD 20 budget is therefore about the High case: alert is correct, but it will not stop spend.

## Ranked must-do before launch
1. C1: replace budget with AUD 5/10/20 actual + forecast alert, srsinc + gmail addresses (today: gmail only, % thresholds as 1/3/10/20).
2. Jobs: fix entries replicaTimeout (180s vs 3-10 min runs) knowingly, since raising it lifts the ceiling; cap entries burst by
   unparking only for the window and re-park afterwards (C2). Keep retryLimit 0, parallelism 1. Consider a no-overlap guard in the worker.
3. C5 + C4: allowlist GitHub hook IPs on the anonymous webhook; disable collect timer after 2026-11-07T13:00Z.
4. C3 + C7 + C6: shrink function memory to 512 MB if it fits; soft delete 1 day; lifecycle delete for webhook-replays and stale pending blobs.
5. C9: disable Foundry API keys, keep zero deployments (no Provisioned throughput/commitment); never add Log Analytics/App Insights
   without C8 caps (env currently ships no logs, so debugging is blind; weigh against the cap).
Also noted: function app settings hold GITHUB_TOKEN / GITHUB_WEBHOOK_SECRET as plain app settings (jobs use KV refs): move to KV references.
