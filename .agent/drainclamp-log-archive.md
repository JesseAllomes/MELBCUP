<!-- drainclamp-build: log archive; schema=1 -->
# DrainClamp log archive

Overflow from DC:LOG, keyed by the 8-character entry id. Logically
append-only. Never auto-loaded into context, and never read during resume —
resume uses `.agent/drainclamp-state.md` alone. This file is for forensics.
- 2026-10-29T07:10:59+00:00 8c17ed1b Gate 0-2: audit, charter-free grill, state externalised for MELBCUP
- 2026-10-29T07:12:39+00:00 58b49675 m1: package scaffold, env settings, pytest+ruff harness
- 2026-10-29T07:17:41+00:00 a1e05e60 m2: PuntersEdge + FormFav clients, card assembly with graceful degradation, 30 tests
- 2026-10-29T07:19:34+00:00 10d9afa9 m3: 18-factor form model, market/feed blend, discounted Harville place probs, 43 tests
- 2026-10-29T07:22:20+00:00 40485c37 m4: singles EV, trifecta/first four/quaddie structures, Sportsbet multis, Kelly staking, 57 tests
- 2026-10-29T07:28:04+00:00 b0ac4008 m5: live board with adaptive price polling, password-protected phone web app, 75 tests
- 2026-10-29T07:29:05+00:00 29605fdd m6: Render blueprint, .python-version, README with phone setup
- 2026-10-29T08:53:14+00:00 46cc835e m7: real-data run, next-to-go prices, manual credit controls, 1,131-race backtest and fitted weights deployed
- 2026-10-29T09:59:53+00:00 f1d66719 History page with per-pick tally, racebook redesign, field-not-yet guard, saved history sealed
- 2026-10-31T05:03:14+00:00 6b648089 az: Azure migration project opened; az1-az3 added (verify, dry run, cutover)
- 2026-10-31T05:07:32+00:00 1cd38880 az1: inventory in .agent/azure-inventory.md; source not in any repo, sites empty, no job logs; blocked on owner (source access)
- 2026-10-31T05:23:13+00:00 bf07a233 owner: grant any permissions needed; owner away - proceed autonomously; Render stays through Cup day
- 2026-10-31T05:27:51+00:00 4214fe2d az1: function review done (.agent/reviews/azure-func-review.md); collector stays off through Cup week
- 2026-10-31T07:19:13+00:00 c3b3a920 owner: launch all, cost audit first, auto-deploy main->Azure behind cost guard. Applied: budget AUD20 alerts 25/50/100%+forecast (both emails), func 512MB x1, storage lifecycle+1d soft delete, Foundry keys off, Log Analytics 0.1GB/day on jobs env, OIDC deploy app 7ab2c182 (Contributor on RG, main only)
- 2026-10-31T07:47:00+00:00 e2372d2a az2: Function in git + guarded deploy live; collector ON 07:43Z in parallel with GitHub collector; GitHub collector parked after first Azure hour validates
- 2026-10-31T08:30:33+00:00 b20a3e38 az3: Azure collector validated (first hour: 329 records, 21 cycles, 0 gaps, 0 dups, same mix as GitHub); live-collector.yml manual-only; archive-to-gcs.yml and Render unchanged
