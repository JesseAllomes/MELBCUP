# Results under protocol v1

**Status: search closed. No demonstrated incremental edge** over the bias-corrected market.

v1's final evaluation was not performed; its holdout is reserved for round 2 (amendment C).
`model-v1` is preserved unchanged. The app is unchanged.
Corrections to the record are in amendment B (PROTOCOL.md).

Model `model-v1` (amendment A, commit `5439f10`) was looked at once on tune2 (2026-01-01 to
2026-04-30). Intervals are 98.33% race-day bootstrap. Raw output is in
`research/analysis/results/tune2_result.json`.

## tune2 verdicts

| Claim | Statistic | Estimate | 98.33% interval | Verdict |
|---|---|---|---|---|
| A. Winner model | log-loss gain over M^α, nats per race (2,547 races) | +0.0003 | −0.0016 to +0.0023 | **inconclusive** |
| B. Betting edge | ROI (3 bets; 3 more excluded for late scratchings) | −100% | −100% to −100% (degenerate) | **fail under the frozen gate**; statistically uninformative (three bets) |
| C. Upset rule | nominee won − benchmark won | – | – | **untested** (0 nominations); inconclusive by rule |

**Claim B.**

- The bootstrap resamples three observed losses, so every resample returns −100%. The zero width
  shows there is too little data, not that the future return is certain.
- The verdict stands as the frozen gate defines it, and the gate is not changed retrospectively.
  Under it, claim B's final block is not opened.
- The dead-heat settlement bug corrected in amendment B does not affect these three bets. None
  was a winner.

**Claim C.** `model-v1` produced no qualifying upset nominations, so the rule was never exercised.

## What this does and does not show

- **Shows:** the form, sectional, stewards', pace, jockey and barrier families screened here, as
  defined in FACTORS.md and combined in `model-v1`, gave **no demonstrated improvement** over M^α
  at T-30. Nine families passed fold screening, each worth well under 0.001 nats per race.
- **Does not show:**
  - that form information is worthless;
  - that no factor can identify an outsider better than its price;
  - that betting on this model loses money.
  The evidence is too thin, or the rule never fired.
- **The odds adjustment (M^α, α ≈ 1.13):**
  - Point estimates favour it over the raw market: +0.0070 nats per race on tune2 (no interval
    was computed at that look) and +0.0040 on tune1.
  - The tune1 95% interval, computed after the fact, is +0.0010 to +0.0070. tune1 was used to
    fit α, so this is descriptive only.
  - It is **promising, not established**. No calibration comparison has been made under a
    declared rule.
  - Applying M^α and renormalising preserves each race's favourite, so it cannot change
    top-pick strike rate. It changes only the size of the probabilities.
  - Deployment to the app is **deferred** until that comparison exists.

## Limitations

- **Forward test.**
  - Decision times are reconstructed from later dumps ("T approximate").
  - Claim-B paper returns exclude late-scratching races.
  - It can test future predictive performance under those assumptions. It cannot establish
    executable betting profitability.
  - That needs live-logged schedules, quotes at the decision time and scratching times.
- **Reproducibility.**
  - The code and paths are documented in `research/analysis/README.md`.
  - The 12,129 raw meeting dumps (about 470 MB) are not in the repository. Without them the
    dataset can be re-collected but not byte-reproduced; `research/dataset/manifest.json` holds
    the output hashes.

## Next

- Preserve `model-v1`.
- Collect live schedules, quotes and scratchings, timestamped at decision time, for a prospective
  evaluation.
- v1's final evaluation was **not performed**. The holdout is reserved for round 2, which runs
  under its own protocol (amendment C). The holdout stays semi-blind, so forward data remains
  the decisive confirmation.
