# Dataset build (protocol v0.5)

Provenance copy of the scripts that built the research dataset, plus count-only reports.

- `collect_adaptive.py`, `rcq.py`: collector of one racing.com `getMeeting` dump per Australian
  meeting, 2022-07-01 to 2026-10-29 (12,129 files).
- `build.py`: dump → `runners`, `races` tables with the protocol v0.5 rules (quotes as change events;
  race-level feed liveness; scratch dating by last fluctuation). Paths point at the session
  scratchpad where the dumps lived. Run `MELBCUP_ROOT=<folder> python3 -I build.py`, then
  `MELBCUP_ROOT=<folder> python3 -I validate.py`, where `<folder>` holds `big/meetings/` and
  receives `upsets/`. Needs Python 3.13, numpy 2.5 and pandas 3.0, about 8 GB of RAM, and about
  25 minutes with a warm cache.
- `manifest.json`: sha256 of every output file.
- `reports/`: inclusion funnels, field availability, column dictionaries, build metadata, and the
  validation report (outcome statistics on the **train** block only).
