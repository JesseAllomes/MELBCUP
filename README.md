# MELBCUP live observations (branch `live`)

Written only by `.github/workflows/live-collector.yml` running `tools/live_collector.py` (on main).
Files under `observations/<UTC date>/` are append-only: each is written once and never changed.
The record format, timestamps (`obs_utc`, `recv_utc`, racing.com's own), heartbeat (`cycle`) and
outage rules are documented at the top of `tools/live_collector.py`. A missing observation stays
missing: nothing is back-filled.
