# Review of FACTORS_V2_PROPOSAL.md against the five round-2 constraints (2026-10-29)

**Status:** proposal accepted for drafting protocol v2. Nothing here is frozen.

| Constraint | Met? | Note |
|---|---|---|
| 1. Mechanism first, rejection condition | Yes | Each of V1–V5 states who leaves it mispriced, when, and what kills it. V4 (market memory × non-metro) carries a flagged multiple-comparison risk. |
| 2. Decision timestamp; bettability | Yes | Strictly as-of T−30. The bettability audit (quote age, survival, eight-second book co-movement) shows the T−30 paper edge does not survive to SP. Forward settlement is at the first live observation at least 60 s after the decision. |
| 3. Market-only model first | Yes | 16 segment and microstructure calibrations are null out of fold. Single-α M^α is the baseline, and horse factors are measured beyond it. |
| 4. Thresholds are fitting | Yes | Log-growth objective, a small grid, frozen before the holdout. Claim B is declared inconclusive by construction in six months rather than tuned to fire. |
| 5. Round 2 is a new experiment | Yes | Own dataset, fingerprint and forward start. tune1 and tune2 are described as reused development periods. The final block is semi-blind, and forward data is decisive. |

## Points to carry into protocol v2

- **Forward-selection optimism.** The combined +0.00213 comes from forward selection over the
  same out-of-fold screening results. Treat it as optimistic. v1 halved from train to tune2.
  Protocol v2 should re-estimate the shortlist on tune1 before pinning, under the rules above.
- **Carried weight semantics (V1).**
  - Historical `weightCarried` may have been revised after the race.
  - The live collector now records declared weight, `apprenticeAllowedClaim`, jockey and gear
    before the race (field records, `tools/live_collector.py`). Before then it logged prices and
    scratchings only.
  - The API does expose apprentice claims. "No claim field" holds only for the historical dumps.
    V1's rejection test (does a claim field remove the effect) can therefore run on live data.
- **Claim D (closing line)** tests whether the model's deviation from M^α is information the market
  later agrees with. It is not profit (closing-line value is not profit).
  - SP here is racing.com's `startingPrice` (the OP feed), which is unreliable at some Queensland
    bush meetings.
  - Settle the reference price definition and its exclusions before freezing.
- **Claim B** stays reported, not confirmatory, unless the forward window can reach 1,000 bets.
- **Evaluator.**
  - v2 should declare which evaluator it freezes: `research/evaluator.py` (all-day bootstrap,
    runner-id ties, evidence verdicts) or the v1 code.
  - The missing export adapter and test suites (EVALUATOR.md status note) should be in the
    repository first.
