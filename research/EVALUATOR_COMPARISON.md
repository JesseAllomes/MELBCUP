# Comparison with the committed v1 evaluator

Compared the standalone `research/evaluator.py` with `research/analysis/evaluate.py` on
GitHub `main` at **67424a5**. The v1 evaluator already contains the settlement, Brier-score and
paired-interval repairs. Those repairs are not unique to the standalone evaluator.

## Verified agreement

On eleven synthetic race scenarios, point estimates agree to 1e-12 for claim-A log-loss gain,
model/market log loss, multiclass Brier scores, scored-race count, claim-B bet count and ROI,
late-scratching exclusions, and claim-C nomination count and win-rate difference.

The cases include normal wins/losses, two- and three-way dead heats, unbacked joint winners,
late scratches, co-favourites, no-bet races, and nominations equal to the benchmark. The two
settlement tests committed alongside v1 also pass. No real test-block outcomes were evaluated.

## Differences that can change reported results

| Item | Git v1 evaluator | Standalone evaluator |
|---|---|---|
| Bootstrap population | Only days containing scored events for that metric | All supplied eligible days, including zero-event days |
| Random generator | NumPy default_rng | Python random.Random |
| Benchmark ties | Highest market probability, then lowest barrier | Highest market probability, then lexical runner_id |
| Three identical losing returns | Fail under interval rule | Same rule verdict, plus degenerate-bootstrap warning and inconclusive evidence verdict |
| Zero events | NaN estimates/limits | JSON null estimates/limits |
| Missing result | Unscored; no selected-bet exposure output | Unscored; selections retained as unsettled exposure |
| Recorded refunds/deductions | Conditional paper settlement | Optional explicit recorded-settlement mode |
| Input validation/audit | Assumes the original dataset schema | Validates CSV probabilities/keys/results; emits race-level selections and provenance hashes |

Identical numeric seeds do not make the two random generators produce identical intervals.
The bootstrap population and benchmark tie policy are substantive choices. The standalone tool
must **not** silently replace v1 for reproducing frozen confidence intervals or verdicts.
Keep v1 authoritative for the original study. A new protocol can adopt and freeze the
standalone tool's explicitly documented definitions.

An adversarial tie case confirms the distinction: when runners 2 and 3 share second-favourite
probability but runner 3 has the lower barrier, v1 chooses runner 3 as benchmark while the
standalone evaluator chooses runner 2. If runner 3 is the nominee and wins, their claim-C
differences are respectively 0 and 1.

## Integration repair

The newer Git `screen.py` requires both `MELBCUP_DATA` and `MELBCUP_RESULTS` at import time.
The initial standalone export adapter supplied only the first, so importing against current
main failed. The adapter now supplies a temporary output folder while loading helpers and
restores both environment variables afterward. Prediction does not fit a model or write to
the original results directory. Its integration tests pass against the updated checkout.

## Repeat the checks

```bash
python -m unittest discover -s tests -p test_research_evaluator.py -v
python -m unittest discover -s tests -p test_evaluator_parity.py -v
```

The parity suite requires NumPy and pandas for v1. The standalone core needs neither. The
original large dataset is absent from this checkout, so this establishes synthetic agreement,
not equality of full-data reports.
