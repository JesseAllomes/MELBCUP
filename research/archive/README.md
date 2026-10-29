# MELBCUP raw-data archive

| File | What |
|---|---|
| `meetings-YYYY.tar` | racing.com `getMeeting` dumps (`big/meetings/*.json.gz`), one per Australian meeting, by year |
| `racingcom-history.tar`, `racingcom-runs.tar` | earlier racing.com pulls |
| `betfair-raw.tar` | Betfair data scientists' public ANZ thoroughbred files |
| `BUNDLES.sha256` | SHA-256 of each bundle |
| `MANIFEST.sha256` | SHA-256 of every file inside the bundles (17,774 files) |
| `files.jsonl` | per file: path, bytes, SHA-256, collection timestamp (UTC, the time the collector wrote it) |
| `VERSIONS.json` | collector and query versions (SHA-256 of the scripts), collection time range, dataset-build manifest hash |
| `collect_adaptive.py`, `rcq.py`, `collect_big.py`, `*.log` | the collector, query definitions and collection logs as run |

**Restore:** `sh restore.sh <target>`. It checks every bundle, extracts them, then checks every
file against `MANIFEST.sha256`. Then point `MELBCUP_ROOT` at `<target>` to rebuild the research
dataset (`research/dataset/build.py` on main).

## Where the archive lives

| Copy | Status |
|---|---|
| Bundles in the session scratchpad (`archive/`) | built 2026-10-29; full test restore verified (17,774 files) |
| GitHub `data` branch, commit `b52e2f3` (public) | fresh clone verified against `MANIFEST.sha256`: all 17,774 files match |
| Private durable storage | **pending**: needs a bucket and credentials from the owner |

The metadata here (`MANIFEST.sha256`, `files.jsonl`, `VERSIONS.json`, `BUNDLES.sha256`) belongs to
the bundles. The collector scripts as run are in `research/dataset/` (rcq.py there has the public key
inlined; `VERSIONS.json` records the hashes of the originals).
