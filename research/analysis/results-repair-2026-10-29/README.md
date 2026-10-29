# Reproduction and evaluator repair (2026-10-29)

A reproduction of train and tune1 with the repaired evaluator. Features, penalties, thresholds,
folds, λ grid and selection rules are unchanged. The frozen v1 outputs in `../results/`
(`model-v1.json`, `tune1_refine.json`, `tune2_result.json` and the screening files) are untouched.
tune2 was **not** re-run.

**Run:** `MELBCUP_DATA=<dataset>/upsets MELBCUP_RESULTS=<this folder>`, then `screen.py`,
`tune1.py`, `pin.py`. The dataset was checked against `research/dataset/manifest.json`: all 55 files
match (sha256 `d0e420ca…`).

## Repairs

1. **Dead-heat settlement.**
   - `evaluate.win_returns` pays q/k, where k is the number of joint winners in the race, whether
     or not they were backed.
   - The old code divided by the joint winners that were backed, so backing one of two joint
     winners paid the full quote.
   - `test_evaluate.py` covers one, several and all joint winners backed, plus two of a three-way
     dead heat. The old evaluator fails the one-backed case.
2. **Explicit paths.**
   - `MELBCUP_DATA` (input) and `MELBCUP_RESULTS` (output) are required.
   - Writing into `results/` is refused, and so is overwriting any existing file.
   - `tune2.py` checks for a tune2 result both at `results/tune2_result.json` (the actual location
     of the one look) and in the output folder. It always loads the pinned `results/model-v1.json`.
     It now refuses to run.
3. **Multiclass Brier and paired intervals.**
   - Multiclass Brier is Σ_i (p_i − y_i)² per race, averaged over races, for P, M^α and the raw
     market.
   - The paired race-day bootstrap intervals of M^α against raw use identical races, for both
     log-loss and Brier.

## Differences from the frozen outputs

| File | Result |
|---|---|
| `screen_folds.csv`, `screen_summary.csv`, `combined_folds.csv`, `combined_summary.csv`, `selection_train.json` | byte-identical |
| `model-v1.json` | byte-identical (α, standardisers, coefficients, dataset fingerprint) |
| `tune1_refine.json` | identical except added fields (below); no existing value changed |

The added tune1 fields are **development evidence** (95%; tune1 was used to fit α and refine the
model):

| Measure | M^α better than raw by | 95% paired interval |
|---|---|---|
| Log-loss (nats per race) | 0.0040 | 0.0010 to 0.0070 |
| Multiclass Brier | 0.0012 | 0.0001 to 0.0023 |

Brier: P 0.78545, M^α 0.78576, raw 0.78698 (3,706 races).

The settlement repair changes no number: no claim-B bet on tune1 (or tune2) was a winner.

## Incidents found during the reproduction

- **Manifest overwritten by a smoke test.** A 20-file test run of `build.py` overwrote the
  dataset's `manifest.json` in the working folder with a 16-file manifest for the test output. A
  first `pin.py` reproduction therefore recorded a different manifest hash. Everything else was
  identical.
  - The manifest was restored from the committed copy, and every file was re-verified.
  - `build.py` now writes test-run manifests into the test output folder.
  - The reproduction was re-pinned and is byte-identical.
- **Original tune1 output overwritten in place.** The amendment-B commit (`f3077ed`) overwrote
  `results/tune1_refine.json` with a re-run carrying the new fields. The original from amendment A
  (`5439f10`) has been restored in `results/`; the re-run lives here.

These figures check the odds adjustment during development. They are not sufficient by themselves
to justify deploying it.
