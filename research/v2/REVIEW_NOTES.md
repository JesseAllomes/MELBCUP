# Review of FACTORS_V2_PROPOSAL.md against the five round-2 constraints (2026-10-29)

**Status:** proposal accepted for drafting protocol v2. Nothing here is frozen. **Protocol v2 stays a
draft until live observations establish which weight fields are usable**, and historical carried
weight stays provisional until the pre-race/post-race comparison is available.

**First sample of the live weight fields** (2026-10-29, one snapshot of 49 races, 1,202 entries,
from a local run of the collector's field query; to be confirmed on the collector's own files):

- `weightCarried` always equals `weight`; both are kilograms as text, e.g. "57.5kg".
- `weightPrevious` is null for 88 entries (no previous run). Null is kept separate from zero.
- `apprenticeAllowedClaim` is text: "0" in 978 entries, or 1.5, 2, 3 or 4.
- `apprenticeCanClaim` is a boolean.
- Two anomalies to explain:
  - 29 apprentices can claim but have "0" allowed;
  - one non-apprentice has a 1.5 kg allowance.
- This snapshot alone cannot show whether `weightCarried` is before or after the claim. The
  collector's `field_post` snapshots and the later dumps will.

**First race-day collector files** (2026-10-30, check at 03:10 UTC, `tools/live_validate.py`):

- **Timing.** Every record has its request time.
  - 569 market snapshots were taken before the start with the race open.
  - All 12 watched races have a snapshot at or before T−30.
  - Post-start records carry their closed, interim or paying status.
- **Weight fields** (1,378 pre-race entries):
  - `weightCarried` equals `weight` in every entry (54–60.5 kg).
  - `weightPrevious` is null in 135 entries.
  - Claims: "0" in 1,182 entries, 1.5, 2 or 3 kg otherwise.
  - Cross-tab: 112 apprentices are flagged able to claim with "0" allowed. These are presumably
    claims not permitted in that race or already lost; still to be explained. No non-apprentice
    claim appeared in this sample.
  - The post-race snapshot (4 races, 44 runners) matched the last pre-race values exactly. No
    weight or claim changed in the minutes after the race. Later revisions are checked against the
    next dumps.
- **Continuity.**
  - 1,633 records carry an ID and none is duplicated. The 84 records written before IDs existed
    are counted as legacy.
  - No unfinished files, and history is append-only (25 commits).
  - The two restarts on 2026-10-29 are visible as 2.6-minute gaps.
  - The scheduled run took over when run 3 stopped at 03:03 UTC.
  - One cycle at 02:22 UTC was lost to a file-rotation race between threads. It is recorded as an
    error record. The fix (one lock around writes) is on main and applies from the next run.

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
- **Owner's pre-freeze conditions (2026-10-29).** These are binding on protocol v2.
  1. **Carried weight stays provisional.** A missing claim field does not establish that historical
     weight already includes claims. Before the effect is interpreted, compare these from the live
     log: timestamped pre-race declarations (`weightCarried`, `weight`, `apprenticeAllowedClaim`,
     `apprenticeCanClaim`) and post-race values from the dumps.
  2. **Claim D must beat a market-only closing-move forecast.**
     - Compare the model's closing-price predictions against a market-only forecast of the T−30 →
       close move: M^α's own implied move, plus market-only terms such as the open→T move, fitted
       on development data.
     - A positive slope of ln(SP/M) on ln(P/P_mkt) alone could reflect the odds correction or
       shared market inputs rather than horse information.
     - The statistic should be the gain over that market-only forecast.
  3. **"No stale-book window" is qualified.** An eight-second median lag implies difficult
     execution, not that every opportunity is unbettable. Measure availability and latency directly
     from the live log: quote survival from first live observation, and cross-book lag at collection
     time.
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
