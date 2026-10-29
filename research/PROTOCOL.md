# Validation protocol: does anything beat the bias-corrected market?

**Status: v1, FROZEN** (tag `protocol-v1`; freeze record in section 8). Changes from here are
dated amendments only. v0.5 closed the Fable adversarial review:
- the fit set for confirmatory models;
- fail and inconclusive verdicts for every claim;
- change-event quotes;
- scratch dating;
- claim C roles fixed at T;
- F17 wet features made exploratory;
- paper settlement for forward bets;
- training likelihood, bootstrap statistic and penalty scaling defined.

v0.4: v0.4 replaces within-race z-scoring, which erased
magnitudes the pace and favourite factors exist to test, with per-feature transformations
fitted on training data.

- v0.2 adopted the first Astra review.
- v0.3 closes the second:
  - the historical clock is stated as an assumption;
  - the runner universe and missing quotes are defined;
  - the factor definitions are made executable;
  - one interval rule;
  - one dead-heat and scratching precedence;
  - exact folds, with α fitted inside each fold;
  - trees stay exploratory.

**Freezing.**

- Items marked _(fill at freeze)_ are completed from the dataset build without looking at any
  outcome in tune1, tune2 or final.
- The protocol is frozen by a commit tagged `protocol-v1` before any tune1 result is opened.
- After that, changes are dated amendments, never edits, and none may change the rules for the
  final or forward blocks.

## 1. Question and model

    P_i = M_i^α · exp(f(X_i)) / Σ_j M_j^α · exp(f(X_j))

- **M_i:** the margin-free bookmaker consensus at the decision time T (section 3).
- **α:** one bias-correction exponent (section 4).
- **f:** a learned correction (section 5). f = 0 is the baseline.

There are three claims, each with one primary test (section 6). Passing one is not passing another.

- **A. Winner model:** P is better calibrated and sharper than M^α.
- **B. Betting edge:** win bets chosen from P at prices live at T make money beyond chance.
- **C. Upset rule:** at T, nominate at most one non-favourite, or abstain. The nominee beats a
  fixed benchmark.

Neither the favourite's strike rate nor overall log-loss is a requirement for B or C.

Place, trifecta and First Four are outside this protocol.

## 2. Data, blocks, examined races

- **Source.** racing.com's public form service: every Australian race meeting from 2022-07-01 to
  2026-10-29, one gzipped `getMeeting` per meeting (collector:
  `scratchpad/big/collect_adaptive.py`; query: `rcq.py`).
- **Dataset build.** `scratchpad/upsets/build.py`, with a sha256 manifest. Manifest hash and code
  commit: see section 8 (manifest sha256 `d0e420ca…7d17c42d`, code commit `3f9dd3b`).

**Blocks, by race date.** Nothing outside a block's role is computed from it.

| Block | Dates | Role |
|---|---|---|
| history only | 2022-07-01 – 2022-12-31 | builds history features; never scored |
| train | 2023-01-01 – 2025-06-30 | screening folds (section 5), α, f, λ |
| tune1 | 2025-07-01 – 2025-12-31 | development; repeated looks allowed |
| tune2 | 2026-01-01 – 2026-04-30 | **one** look at the candidate fixed in amendment A |
| final | 2026-05-01 – 2026-09-28, less examined races | opened once, against the frozen commit. **Semi-blind**: it can fail a claim, but a pass is provisional |
| excluded | 2026-09-29 – 2026-10-29 | development month; out of every confirmatory test |
| forward | races with T after the timestamp of the commit tagged `model-v1` (the model pinned in amendment A), up to 2027-04-30 23:59 (Australia/Melbourne) | the clean prospective test; **required for every claim** |

**The tune2 gate.**

- Each claim gets its own tune2 verdict (section 6).
- If a claim **fails** on tune2, the final block is **not** opened for that claim. That claim
  then has no confirmatory support under this protocol.
- If a claim is inconclusive or passes on tune2, its final block is opened.
- tune2 is never reused.

**Reading history is not a look.** Building history features for a later race mechanically reads
earlier races' results, including races in tune2, final or forward. That is not a look at those
blocks, provided no statistic over them is computed or displayed.

**Examined races** (`research/examined.csv`) are excluded from every confirmatory test:

- every race on 2026-09-29 to 2026-10-29;
- Doomben 2026-08-01 race 1 (its result was printed during data checks);
- any race whose outcome was displayed in development, added before the freeze.

**Disclosed, not excluded:** the Betfair study looked at 2025-01 to 2026-09 outcomes through
Betfair data (BSP and history variables, no racing.com form). Hence the final block is
semi-blind.

## 3. Decision time, runners, market (all as known at T)

**T.** racing.com's recorded scheduled start (`races.time`) minus 30 minutes. T-60 and T-10 are
exploratory.

**Historical timing is an assumption, not evidence.**

- The recorded start is the last schedule racing.com holds. If a race was re-timed (even by
  20 minutes), T is computed from the re-timed start, and whether the change was known before T
  cannot be checked.
- Historical results are therefore labelled **"T approximate"**.
- Races are excluded as untrustworthy timing, and counted, if either:
  - the recorded start is more than 24 hours from the last price fluctuation; or
  - no fluctuation falls within the 3 hours before the recorded start.
- **Forward dataset.** Built by the same code from racing.com dumps collected after the window,
  so forward timing is also "T approximate". It is prospective because the model was pinned
  before those races ran.
- **Forward audit.** Where the app logged a decision live (the schedule it saw, the decision
  timestamp, the quotes used), the two are compared as an audit. The audit is not the primary
  analysis.

**Quotes at T.**

- racing.com's `flucsWin` are **change events**: an entry appears only when the price changes.
  The freeze records a check of this: the share of entries whose price equals the previous one.
- For bookmaker b in {sb (Sportsbet), lb (Ladbrokes)}, a runner's quote at T is its last
  fluctuation at or before T, whatever its age. A stable price is still a live price.
- Entries with no price or a zero price are ignored.
- **Feed liveness (race-level).** Each of sb and lb must have at least one fluctuation on any
  runner in that race in [T − 900 s, T]. Otherwise the race is excluded (pre-decision filter) and
  counted.
- **Starting price never fills a missing quote.**

**Runner universe at T, U.**

- Every entry not recorded as scratched; **plus**
- every entry recorded as scratched whose **last fluctuation at either bookmaker is at or after
  T**. These are **late scratchings**.
- Entries recorded as scratched whose last fluctuation at both bookmakers is **before** T are
  treated as scratched before T and are not in U, whatever the quote's age.
- The count of recorded scratchings whose last fluctuation falls in (T − 900 s, T) is published.
  Those are the cases this dating can misclassify.

**Market M (primary: complete two-bookmaker coverage).**

- A race is market-eligible only if **every runner in U** has a quote at T (a fluctuation at or
  before T) from **both** sb and lb.
- For each bookmaker, m_b,i = (1/q_b,i) / Σ_{j∈U} (1/q_b,j).
- M_i = (m_sb,i + m_lb,i) / 2. This already sums to 1 over U, so there are no unquoted runners
  in the primary analysis.
- Secondary (exploratory):
  - sb-only, where every runner in U has an sb quote at T;
  - partial coverage, where unquoted runners are dropped and the race is flagged.

**Favourite.** The runner with the **highest** M_i. Co-favourites are runners within 1e-9 of the
maximum. For claim C, all co-favourites count as favourites.

**Eligibility is checked in two stages.**

1. **Pre-decision filters** (knowable at T; they define what the model acts on):
   - Australian meeting;
   - not a trial or jump-out;
   - |U| ≥ 5;
   - market-eligible;
   - feed live (both books);
   - timing not excluded;
   - not an examined race.
2. **Post-race scoring rules** (facts known only afterwards; they decide how an acted-on race is
   scored, never whether the model acts):
   - late scratchings;
   - dead heats;
   - result present.
   Their counts are published.

**History features.**

- Only races on **earlier calendar days** (Australia/Melbourne) are used. No same-day result is
  used, at any meeting.
- Same-day features (same-meeting bias, connections' same-day form) are exploratory, in columns
  prefixed `sameday_`.

**Field whitelist (past runs).**

- Used: finish, margin, starting price, barrier, weight carried, jockey, trainer, gear changes,
  positions settled/800/400, `timeSectional`, `timing` (topSpeed, distanceTravelled), stewards'
  comment, race distance, race class, track condition (final), `handicapRating` (flagged as
  possibly revised: effects are reported with and without it).
- Never used: horse-profile or current fields, `speedValue`, `tempo`, and **today's** track
  condition or rail for any primary feature (their final values cannot show what was known at T).

**Scaling.** No within-race standardisation. A conditional logit already ignores any race-level
constant, and dividing by a race's own spread destroys magnitudes. Each feature's transformation
is specified in `research/FACTORS.md`:

- **Continuous features:** standardised globally, with mean and SD fitted on the training runners
  of the fit in question.
- **Binary flags:** left as 0/1.
- **Products:** formed from already-standardised parts.

Anything fitted (means, SDs, shrinkage targets) uses only that fit's training data. Race-level
quantities (e.g. a race's leader count) enter only through interactions with runner-varying
features, never alone.

## 4. Bias-corrected market

- **α.** One universal exponent, fitted by maximum likelihood (conditional logit on log M) on the
  training data of each fit, and not bookmaker-, time- or field-size-specific:
  - inside each screening fold, on that fold's training dates only;
  - for tune1 evaluation, on all train dates;
  - for the pinned model (amendment A), on **train + tune1** together with f (section 5).
- **Raw market (α = 1).** Always reported as the secondary baseline.

## 5. Correction f and the selection procedure (frozen)

**Form.**

- Conditional logit with α·log M as a fixed offset.
- f is linear in the family features defined in `research/FACTORS.md`, each transformed as
  specified there, with fold-train scaling.
- **Missing values:** set to the fold-train mean (0 after standardisation), plus one
  missing-indicator per family. If a standardiser's SD is 0, the feature is set to 0.
- **Training likelihood.**
  - Late scratchings are dropped from their race, and the market and features are renormalised
    over the actual starters.
  - Dead-heat races are excluded.
  - Races with no recorded result are excluded.
- **Penalty.** The objective is the **mean** per-race log-likelihood minus (λ / 2)·‖w‖², so λ
  means the same strength whatever the training size. The offset coefficient α is not
  penalised.

**Screening folds.**

- **Fold k** (k = 1…6) trains on scored train races from 2023-01-01 up to the day before
  quarter Q_k, and validates on Q_k:
  - Q1 = 2024-01–03
  - Q2 = 2024-04–06
  - Q3 = 2024-07–09
  - Q4 = 2024-10–12
  - Q5 = 2025-01–03
  - Q6 = 2025-04–06
- In each fold, α, the scaling and the shrinkage targets are fitted on that fold's training data
  only.

**Selection steps.**

1. **Screening.** Each primary family is fitted alone, on the offset, with λ = 3. A family is
   **kept** if its validation log-loss is lower than the offset-only model's in at least 4 of the
   6 folds.
2. **Combined.** The kept families are fitted together. λ is chosen from {0.3, 1, 3, 10, 30} by
   mean validation log-loss over the 6 folds.
3. **Refining on tune1.** Kept families may be dropped, and λ re-chosen from the same grid. No
   family that failed screening may be added. No new families, transforms or definitions.

**Amendment A** (before tune2) records the final family list and λ. It also **pins the model**:
α, f's coefficients, every standardiser and every shrinkage target, all fitted on **train + tune1**.

- The pinned model is committed and tagged `model-v1`.
- It is used unchanged for tune2, final and forward. There is no refit after amendment A.
- Amendment A also records the claim-B bet rate and claim-C nomination rate per 1,000 eligible
  races on tune1. This checks the forward minimums are reachable. If the projected forward counts
  are below them, that is stated, and the forward result for that claim is expected to be
  inconclusive. The minimums are not changed.

**Trees and other learners** are exploratory throughout this protocol and cannot become primary.

## 6. Primary tests

**Intervals (one rule).**

- Percentile bootstrap over race-days, with 10,000 resamples and seed 20261031.
  - A race-day is a calendar date in Australia/Melbourne, across all meetings.
  - Each statistic is a **ratio of sums** over the resampled days:
    - claim A: summed log-loss difference over summed races;
    - claim B: summed return over summed stakes;
    - claim C: summed difference over summed nominations.
- Confirmatory blocks (tune2, final, forward) use the **98.33%** interval: quantiles **0.00833**
  and **0.99167** (Bonferroni across the three claims).
- tune1 and train results use 95% intervals and are descriptive.

**Scoring rules, in this order of precedence.**

1. **Late scratching (a runner in U did not start).**
   - Claims A and C: P and M^α are renormalised over the actual starters, identically, before
     scoring.
   - Claim B historical: the race's bets are excluded; the result is labelled **conditional on no
     late scratching**; the excluded exposure (bets, stake, notional return without deductions)
     is published.
   - Claim B forward: **paper bets**, settled exactly as historical (late-scratching races
     excluded and labelled the same way), at the quote at T from the recorded bookmaker. No real
     bets are assumed.
2. **Dead heat for first.**
   - Claims A and C: the race is excluded from scoring and counted.
   - Claim B: a winning bet returns q_i / k, where k is the number of horses in the dead heat
     (two-way returns half; three-way a third).
3. **No result recorded:** excluded from all claims and counted.

**A. Winner model.**

- **Statistic:** mean over scored races of [log-loss(M^α) − log-loss(P)].
- **Pass:** the interval lies entirely above 0.
- **Fail:** the interval lies entirely at or below 0.
- **Inconclusive:** otherwise.
- **Secondary:** Brier score; calibration by probability band, price band, distance, class and
  state; raw market.

**B. Betting edge.**

- **Rule.** At T, back runner i with level $1 stakes if all of these hold:
  - P_i × q_i − 1 ≥ 0.05, where q_i = max(q_sb,i, q_lb,i) among usable quotes, and the bookmaker
    giving that maximum is recorded at T;
  - P_i ≥ 0.04;
  - q_i ≤ 21.
  More than one runner per race may be backed.
- **Statistic:** ROI.
- **Pass:** the interval's lower bound is above 0.
- **Fail:** the upper bound is at or below 0.
- **Inconclusive:** otherwise.

**C. Upset rule.**

- **Rule.** At T, among non-favourites with P_i ≥ 0.10, take the one with the highest
  P_i / (M_i^α / Σ_j M_j^α). Nominate it if that ratio is ≥ 1.25. Otherwise abstain.
- **Benchmark.** The highest-M non-favourite in the same race. All roles (favourites, nominee,
  benchmark) are fixed at T. If the benchmark is the nominee, the race still counts, with a
  difference of 0.
- **Void nominations.** A nomination is **void** if the nominee **or** the benchmark is a late
  scratching. It is removed from the statistic. Both void types are counted and published. No
  substitute is nominated.
- **Statistic:** over non-void nominations, sum of [nominee won − benchmark won] over the number
  of nominations.
- **Pass:** the interval lies entirely above 0.
- **Fail:** the upper bound is at or below 0.
- **Inconclusive:** otherwise.
- **Secondary:** nominee log-loss and ROI at q.

**One verdict per claim.** tune2, the final block and the forward window each give exactly one
verdict per claim: pass, fail or inconclusive. No subgroup, decision time or bet type can change
it.

### 6a. Forward stopping and the overall verdict

- **Window.** The forward window is fixed (section 2) and evaluated **once**, after it closes.
  - There are no interim decisions and no extension.
  - Fewer than 1,000 claim-B bets or 300 claim-C nominations makes that claim
    **inconclusive**.
- **Overall verdict.** A claim is **supported** only if it passes on both the final and forward
  blocks. A forward fail is a fail. It cannot be re-tested on the same forward window.

## 7. Reporting

- Every primary statistic and interval, whatever the outcome.
- The full inclusion funnel: pre-decision filters by year and state, then the post-race scoring
  counts.
- Field availability by field, bookmaker, decision time and year.
- Results on excluded races (exploratory).
- Separate rows for staying races (≥ 2,800 m), Group 1 races and fields of 16 or more. A pass
  overall is not a pass for Cup-type races.
- Price movement from T to the jump is reported as evidence, not profit.

## 8. Freeze record

Filled from the dataset build alone. No model, factor or claim statistic has been computed on
tune1, tune2 or final.

**Build.**

- Code: `research/dataset/` at commit `3f9dd3b0b5316266550b74116df9d4dd6ee49c37`.
- Output manifest (sha256 of 55 output files): `research/dataset/manifest.json`, itself sha256
  `d0e420cac1e3f26b1d78d99da543d076d909e3cc1eb2cc2bd8a0b6d17d17c42d`.
- Source: 12,129 meeting dumps; 90,163 races; 1,085,407 entries.

**Change-event check.** Of 47,723,713 consecutive fluctuation pairs (both books), 1,664,394
(3.49%) repeat the previous price. The series are predominantly change events. A repeat does not
affect "last fluctuation at or before T", but it does count towards feed liveness.

**Inclusion funnel at T-30** (`research/dataset/reports/funnel_*.csv`):

| Step | Removed | Remaining |
|---|---|---|
| All races in the dumps | | 90,163 |
| Not Australian | 3,295 | 86,868 |
| Trial or jump-out | 0 | 86,868 |
| \|U\| < 5 | 1,309 | 85,559 |
| Not market-eligible | 13,854 | 71,705 |
| Feed not live | 39,239 | 32,466 |
| Timing untrusted | 0 | 32,466 |
| Examined | 1,106 | 31,360 |

Pre-decision-eligible races by block:

| Block | Races |
|---|---|
| history only | 2,183 |
| train | 17,597 |
| tune1 | 3,718 |
| tune2 | 2,554 |
| final | 5,308 |
| excluded | 0 |

**Post-race scoring counts** among the eligible races (all blocks):

- ok 29,275;
- late scratching 1,920;
- no result 105;
- dead heat 58;
- no winner recorded 2.

Recorded scratchings whose last fluctuation falls in (T − 900 s, T), the cases scratch dating can
misclassify, total 120 across eligible races (train 79).

**Field availability** by field, bookmaker, decision time and year:
`research/dataset/reports/field_availability.csv`.

**Scope consequence.** Feed liveness removes about half of otherwise usable races, mostly meetings
whose prices rarely move in the 15 minutes before T-30. Every claim therefore applies only to races
with a live two-bookmaker market at T-30. That is also the only population the app can act on.

**Data-quality findings fixed at freeze.**

- `horse.age` and `horse.sex` are values at collection (2026-10-29), not at the race. Only
  `age_at_race_est` may be used.
- `timeSectional` is one race-level value repeated on every runner. F1 uses the runner's last-600 m
  time from the timing sections (`res_last600_s`) instead (FACTORS.md F1).
- `distanceTravelled` of 0 is treated as missing.
- racing.com's `startingPrice` equals the provider "OP" price. It is unreliable at some Queensland
  bush meetings. It is used only for expected wins in history features (FACTORS.md), never as a
  quote.
- Entries neither scratched nor started (emergencies) are in U under the literal rule. A race where
  one lacks a quote is not market-eligible.
- Five dumps (2025-04-14 to 2025-04-17) failed to parse. 346 races had no recorded start and were
  dropped at parse.
- July 2022 has no Ladbrokes prices. This affects only the history-only block, which is never
  scored.

**Disclosure.** Before this freeze, the v0.4 dataset report displayed **market-only** baselines on
tune1 and tune2:

- the SP favourite's strike rate by block;
- SP against Sportsbet log-loss, pooled over train, tune1 and tune2.

No model or factor was involved. The validation script now restricts every outcome statistic to
the train block.

## Amendments

_(none yet)_
