# Results under protocol v1

Model `model-v1` (amendment A, commit `5439f10`), looked at once on tune2 (2026-01-01 to
2026-04-30). Intervals are 98.33% race-day bootstrap. Raw output:
`research/analysis/results/tune2_result.json`.

## tune2 verdicts

| Claim | Statistic | Estimate | 98.33% interval | Verdict |
|---|---|---|---|---|
| A. Winner model | log-loss gain over M^α, nats per race (2,547 races) | +0.0003 | −0.0016 to +0.0023 | **inconclusive** |
| B. Betting edge | ROI (3 bets; 3 more excluded for late scratchings) | −100% | −100% to −100% | **fail** (by rule) |
| C. Upset rule | nominee won − benchmark won (0 nominations) | – | – | **inconclusive** |

**Claim B.** The fail rests on 3 bets. The protocol sets no tune2 minimum, so the rule's verdict
stands. Under the tune2 gate, claim B's final block is **not opened**, and B has no confirmatory
support under this protocol.

**Claim C.** The pinned correction never moves a non-favourite's chance 25% above its
bias-corrected market chance, so there is nothing to test. Forward, B and C will fall far short of
their minimums and be inconclusive (amendment A).

## What this says

- The **bias-corrected market** is the one robust gain. With α ≈ 1.13, favourites are a bit
  stronger and outsiders a bit weaker than the margin-free prices imply. M^α beats the raw market
  by 0.007 nats per race on tune2 and by 0.004 on tune1.
- The form, sectional, stewards', pace, jockey and barrier factors add **almost nothing** on top of
  live two-bookmaker prices at T-30.
  - Nine families passed screening, each worth well under 0.001 nats per race.
  - The combined model is not distinguishable from M^α on tune2.
- Nothing found here identifies, ahead of time, an outsider more likely to win than its price
  says.

## Not yet done

- **Final block** (2026-05-01 to 2026-09-28): still sealed. Under the protocol it may now be opened
  once, for claims A and C, against `model-v1`. That is left to the owner.
- **Forward window:** from the `model-v1` commit to 2027-04-30. It needs racing.com dumps collected
  after the window closes.
