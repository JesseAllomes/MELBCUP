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
