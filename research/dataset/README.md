# Dataset build (protocol v0.5)

Provenance copy of the scripts that built the research dataset, plus count-only reports.

- `collect_adaptive.py`, `rcq.py`: collector of one racing.com `getMeeting` dump per Australian
  meeting, 2022-07-01 to 2026-10-29 (12,129 files).
- `build.py`: dump → `runners`, `races` tables with the protocol v0.5 rules (quotes as change events;
  race-level feed liveness; scratch dating by last fluctuation). Paths point at the session
  scratchpad where the dumps live; run `python3 -I build.py` then `python3 -I validate.py`.
- `manifest.json`: sha256 of every output file.
- `reports/`: inclusion funnels, field availability, column dictionaries, build metadata, and the
  validation report (outcome statistics on the **train** block only).
