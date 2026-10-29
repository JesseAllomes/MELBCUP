> **Status in this repository (2026-10-29).**
> - `research/evaluator.py` is a **candidate evaluator for protocol v2**. `research/analysis/evaluate.py`
>   remains authoritative for every v1 result.
> - The export adapter (`research/analysis/export_predictions.py`), the suites
>   `tests/test_research_evaluator.py` and `tests/test_evaluator_parity.py`, and
>   `research/__init__.py` were added from the support archive. All 27 tests pass, and
>   `research/evaluator.py` is byte-identical to the supplied copy. The support archive does not
>   replace the committed evaluator or any v1 result.
> - `tests/test_evaluator_parity_synthetic.py` (run with `MELBCUP_DATA=x MELBCUP_RESULTS=<tmp>`)
>   checks 12 point estimates against v1 on 5 random scenarios of 400 races, with scratchings,
>   dead heats, bets and nominations. All agree to 1e-9.

# Saved-prediction evaluator

Run `python -m research.evaluator --help` from the repository root. The evaluator uses only
Python's standard library. It never fits a model, chooses features, estimates alpha or tunes
thresholds. Any model can supply its decision-time runner probabilities.

## Existing pinned v1 model

The adapter requires NumPy and pandas (`pip install numpy pandas`) and the **trusted** original
dataset containing `manifest.json` and `out/runners.pkl.gz`, `out/races.pkl.gz`. Pickle is an
executable format: use only your own dataset. Both input files and the manifest are checked
against the pinned model before export.

```bash
python -m research.analysis.export_predictions \
  --data-root /path/to/dataset \
  --model research/analysis/results/model-v1.json \
  --block train \
  --output-dir /path/to/new-train-export

python -m research.evaluator \
  --predictions /path/to/new-train-export/predictions.csv \
  --outcomes /path/to/new-train-export/outcomes.csv \
  --block train \
  --model research/analysis/results/model-v1.json \
  --protocol research/PROTOCOL.md \
  --output /path/to/new-train-report.json
```

Repeat with `--block tune1` and new output paths for development diagnostics. The adapter permits
only train and tune1. Evaluating the train+tune1-fitted model on either is an **in-sample**
diagnostic, not reproduction of earlier fold-held-out or train-only-fit tune1 figures.
To reproduce those figures, export predictions from the corresponding saved fit, not model-v1.

The original pickles are not in this checkout. The adapter has synthetic integration tests;
no real research outcomes were evaluated while building these tools.

## CSV contract for any model

`predictions.csv` has one row per runner accepted at the decision time, including runners that
are subsequently scratched:

```csv
race_id,runner_id,day,block,model_prob,market_prob,corrected_prob,win_price,bookmaker
r1,1,2024-01-01,train,0.6,0.5,0.5,2.0,sb
r1,2,2024-01-01,train,0.3,0.3,0.3,3.0,lb
r1,3,2024-01-01,train,0.1,0.2,0.2,5.0,sb
```

`day` is the Australia/Melbourne calendar date used for day-clustered inference. Supply it
explicitly: the evaluator does not infer timezones from dates. Probabilities must be finite,
positive, and sum to one per race (tolerance 1e-6). Fields are never filled from starting prices.
One report covers one block. Duplicate keys, incomplete runner results, and unpredicted actual
starters raise errors. Model probabilities are never silently repaired.

`market_prob` is the raw no-vig market. Supply either the frozen `corrected_prob` column or
`--alpha YOUR_FROZEN_EXPONENT`, which computes normalised market_prob**alpha. Supplying alpha
explicitly overrides the corrected column. This also supports segment-calibrated baselines by
providing saved corrected probabilities rather than asking the evaluator to fit them.

`win_price` is the quote selected using information available at decision time; `bookmaker`
identifies it. A blank quote prevents betting on that runner but does not remove it from
probability scoring. The evaluator trusts the supplied decision-time data; it cannot establish
that historical quotes were executable or reconstruct historical scratch timestamps.

`outcomes.csv` is separate:

```csv
race_id,runner_id,starter,won,result_available
r1,1,true,true,true
r1,2,true,false,true
r1,3,true,false,true
```

`result_available` is optional and defaults to true. Supply every predicted runner, or mark the
race unavailable. An entirely absent race result is counted as missing; a partial result raises
an error. A race with no winner is unscored. Actual scratches have starter=false, won=false.
Dead heats have won=true for every joint winner. Predictions, bet selections and nominations
are fixed before results are examined, including on races with missing results.

## Metrics and settlement

- Multiclass log loss, **summed-per-race** Brier score and top-pick strike rate for the model,
  corrected market and raw market. Co-top picks share credit equally. Calibration uses fixed
  ten-percentage-point bins; it is descriptive and pooled over runners, not an inferential test.
- Claim A: corrected-market log loss minus model log loss. Separate paired comparisons report
  corrected versus raw market in log loss and Brier, and model versus corrected in Brier.
- Claim B: level $1 bets, conditional settlement by default. If any decision-time runner does
  not start, all bets in that race are excluded. Excluded stakes and notional returns are
  reported. A joint winner returns quote divided by the **total race-wide** number of winners,
  regardless of which other winners were backed. Missing results remain unsettled exposure.
- Claim C: at most one non-favourite nomination, compared with the highest-market non-favourite
  on the same race. Roles stay fixed at decision time. Scratching either horse voids the
  nomination, without substitution. Dead heats are excluded from A and C. All co-favourites are
  excluded from nomination; exact selection ties use lexical runner_id order.

Default thresholds match the v1 values: edge >=5%, win probability >=4%, price <=21; nomination
probability >=10% and model/corrected-market ratio >=1.25. These are evaluator defaults, **not a
round-2 preregistration**. Nomination ties use runner_id, whereas the old evaluator used barrier
for benchmark ties; this is a documented semantic difference, not a silent replacement of v1.

For recorded settlements, use a rules file containing `"settlement": "recorded"` and supply
`return_per_unit` on every selected bet's outcome. This is the gross return per $1, including
refunds (=1), voids (=1), deductions and dead-heat adjustments. No deduction is guessed or
applied twice. This mode requires supplied settlements and does not prove a bet was accepted.

## Uncertainty and verdicts

Day-clustered percentile bootstrap, 10,000 resamples, seed 20261031, confidence level 0.9833.
Every draw samples whole eligible days with replacement, including days with zero bets or
nominations. Statistics are ratios of sums, not averages of daily ROIs. Comparisons are paired
on identical races. Resamples with zero denominators are omitted and counted explicitly.

Each interval reports `rule_verdict` and `evidence_verdict`. The first implements the declared
interval/sign rule and any supplied event minimum. The second is inconclusive when there is
insufficient observed variation or fewer than two event days. For example, three losses still
produce the empirical interval [-1,-1] and rule verdict fail, but receive an evidence warning.
No-event metrics have null estimates/limits and an inconclusive verdict. These warnings do not
rewrite the frozen historical result or create a new statistical confidence guarantee.

Override settings with a JSON file supplied via `--rules`, for example:

```json
{
  "level": 0.9833,
  "resamples": 10000,
  "seed": 20261031,
  "min_bets": 1000,
  "min_nominations": 300,
  "settlement": "conditional"
}
```

Minimum counts default to zero to avoid imposing forward-only requirements on historical
development reports. Set the preregistered minimums explicitly for each confirmatory run.
Secondary metric intervals are descriptive; only the protocol determines which claims belong
to a confirmatory family. The report does not decide cross-period support automatically.

## Output and protected blocks

Each new JSON report contains settings, all three baselines, paired comparisons, calibration,
exclusion/exposure counts and a race-by-race audit of selections and returns. It records the
input/model/protocol SHA-256 hashes, evaluator hash, git commit and UTC generation time. JSON
contains null rather than NaN. Reports and export directories refuse overwrites.

The CLI defaults to train. Blocks tune2, final and forward require the deliberate
`--confirmatory --protocol /path/to/frozen-protocol --model /path/to/pinned-model` invocation.
This prevents accidental evaluation; it does not establish that the protocol authorises a run,
enforce a one-look policy across filenames, or make a semi-blind dataset independent.
The library API has no filesystem side effects and leaves access control to its caller.

Tests (no pytest needed for the core suite):

```bash
python -m unittest discover -s tests -p test_research_evaluator.py -v
```
