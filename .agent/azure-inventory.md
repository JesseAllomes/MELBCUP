# Azure inventory: MELBCUP (az1, 2026-10-31)

Resource group rg-personal-automation-aue (australiaeast). Read-only check.

| Current | Azure resource | Status |
|---|---|---|
| Render web app (FastAPI, uvicorn) | static web app swa-melbcup (polite-dune-0706f6300.5.azurestaticapps.net, Free) | **empty**: Azure placeholder; a Static Web App cannot run the FastAPI server as is |
| live-collector.yml (every 20 min) | func-personal-v5ethud2i3cfq (Flex, Python 3.12), GITHUB_REPOSITORY=JesseAllomes/MELBCUP | COLLECTOR_DISABLED=1, window 2026-10-30T13Z to 2026-11-07T13Z; host answers **503** |
| archive-to-gcs.yml (GCS) | storage stpersonalv5ethud2i3cfq containers live-observations, melbcup-archive, collector-state | contents unread (no blob data role) |

Function app also hosts the Lotto re-enter webhook (LOTTO_REENTER_JOB_RESOURCE_ID, GITHUB_WEBHOOK_SECRET).

Findings
1. No Azure replacement for the Render app exists yet; keep Render for Cup day.
2. Function code is only in blob container function-deployment; not in any repository.
3. Function host 503 (cold start or broken deploy; unknown without logs or the package).
4. Owner's account lacks Storage Blob Data roles on the storage account.

## Review (2026-10-31, Sonnet worker): .agent/reviews/azure-func-review.md
Blockers: cross-run same_as dedupe breaks live_validate/live_gaps (D1); host functionTimeout 20 s < 30 s request timeout (D2);
silent cadence throttle on busy days (D3). Also publish not idempotent (D5), code not in git and collector diverged (D11).
No racing API key is missing (racing.com public key). Webhook HMAC/owner checks are correct; replay marker too early (D6).
Decision: Azure collector stays OFF through Cup week; GitHub live-collector.yml, archive-to-gcs.yml and Render keep running.
Fixes and code-into-git happen in az2 after Cup day.
