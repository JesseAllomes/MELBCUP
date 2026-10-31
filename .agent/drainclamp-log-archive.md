<!-- drainclamp-build: log archive; schema=1 -->
# DrainClamp log archive

Overflow from DC:LOG, keyed by the 8-character entry id. Logically
append-only. Never auto-loaded into context, and never read during resume —
resume uses `.agent/drainclamp-state.md` alone. This file is for forensics.
- 2026-10-29T07:10:59+00:00 8c17ed1b Gate 0-2: audit, charter-free grill, state externalised for MELBCUP
- 2026-10-29T07:12:39+00:00 58b49675 m1: package scaffold, env settings, pytest+ruff harness
