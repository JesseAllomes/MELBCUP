# MELBCUP raw data (branch `data`)

Raw source data behind `research/` on main. Everything else can be rebuilt from this branch and
the code on main.

| Path | What | Used by |
|---|---|---|
| `big/meetings/*.json.gz` | 12,129 racing.com `getMeeting` dumps, every Australian meeting 2022-07-01 to 2026-10-29 (collected 2026-10-29 with `big/collect_adaptive.py`) | `research/dataset/build.py` (set `MELBCUP_ROOT` to a checkout of this branch) |
| `racingcom/history`, `racingcom/runs` | earlier racing.com pulls (Aug–Oct 2026 meetings, horse run histories) | early app research |
| `betfair/raw` | Betfair data scientists' public ANZ thoroughbred files | the Betfair study (PROTOCOL.md section 2) |

Output hashes of the v0.5 build: `research/dataset/manifest.json` on main.
