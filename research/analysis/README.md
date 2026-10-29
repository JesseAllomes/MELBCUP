# Protocol v1 analysis

Scripts for PROTOCOL.md sections 4–6 and amendment A. Results are in `results/`.

**Requirements.**

- Python 3.13, numpy 2.5, pandas 3.0. No other dependencies.
- The dataset from `research/dataset/`: build it with `MELBCUP_ROOT=<folder> python3 -I build.py`,
  where `<folder>` holds `big/meetings/*.json.gz` (the racing.com dumps). The dumps are on this
  repository's `data` branch. Check the build against `research/dataset/manifest.json`.

**Run**, from this folder, with:

- `MELBCUP_DATA=<folder>/upsets`: the folder holding `out/` and `manifest.json`;
- `MELBCUP_RESULTS=<new folder>`: where this run writes.

Writing into `results/` is refused, because it holds the frozen v1 outputs. So is overwriting any
existing file. Settlement tests: `python3 test_evaluate.py`.

| Step | Script | Blocks read for outcomes | Writes |
|---|---|---|---|
| Screening and combined fit | `python3 screen.py` | train | `$MELBCUP_RESULTS/screen_*.csv`, `combined_*.csv`, `selection_train.json` |
| tune1 refinement | `python3 tune1.py` | train, tune1 | `$MELBCUP_RESULTS/tune1_refine.json` |
| Pin model-v1 | `python3 pin.py` | train, tune1 | `$MELBCUP_RESULTS/model-v1.json` (the pinned model stays in `results/`) |
| tune2, once | `python3 tune2.py` | tune2 | refuses: the one look exists at `results/tune2_result.json`; it always uses `results/model-v1.json` |

`evaluate.py` holds the fitting, prediction, claims and bootstrap code. It refuses every block
except train, tune1 and tune2.

**Reproduction (2026-10-29).** See `results-repair-2026-10-29/README.md`:

- byte-identical screening outputs and `model-v1.json`;
- `tune1_refine.json` identical except for the added Brier and paired-interval fields.
