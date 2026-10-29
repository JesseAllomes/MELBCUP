# Validation protocol: does anything beat the bias-corrected market?

**Status: DRAFT v0.4, not frozen.** v0.4 replaces within-race z-scoring, which erased
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
  commit: _(fill at freeze)_.

**Blocks, by race date.** Nothing outside a block's role is computed from it.

| Block | Dates | Role |
|---|---|---|
| history only | 2022-07-01 – 2022-12-31 | builds history features; never scored |
| train | 2023-01-01 – 2025-06-30 | screening folds (section 5), α, f, λ |
| tune1 | 2025-07-01 – 2025-12-31 | development; repeated looks allowed |
| tune2 | 2026-01-01 – 2026-04-30 | **one** look at the candidate fixed in amendment A |
| final | 2026-05-01 – 2026-09-28, less examined races | opened once, against the frozen commit. **Semi-blind**: it can fail a claim, but a pass is provisional |
| excluded | 2026-09-29 – 2026-10-29 | development month; out of every confirmatory test |
| forward | races scheduled 2026-11-01 00:00 to 2027-04-30 23:59 (Australia/Melbourne) | the clean prospective test; **required for every claim** |

If tune2 fails, the work goes back to train/tune1. The next confirmatory look needs forward data.
tune2 is never reused.

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
- **Forward:** the app logs, for each decision, the schedule it saw, the decision timestamp and
  every quote used. Forward timing is evidence.

**Quotes at T.**

- For bookmaker b in {sb (Sportsbet), lb (Ladbrokes)}, a runner's quote is the last fluctuation
  at or before T. It is **usable** if its age (T minus its timestamp) is at most 900 seconds.
- **Starting price never fills a missing quote.**

**Runner universe at T, U.**

- Every entry not recorded as scratched; **plus**
- every entry recorded as scratched but with a usable quote at T from both bookmakers. These are
  treated as **late scratchings** (withdrawn after T).
- Entries recorded as scratched with no usable quote at T are treated as scratched before T and
  are not in U.

**Market M (primary: complete two-bookmaker coverage).**

- A race is market-eligible only if **every runner in U** has a usable quote at T from **both**
  sb and lb.
- For each bookmaker, m_b,i = (1/q_b,i) / Σ_{j∈U} (1/q_b,j).
- M_i = (m_sb,i + m_lb,i) / 2. This already sums to 1 over U, so there are no unquoted runners
  in the primary analysis.
- Secondary (exploratory):
  - sb-only, where every runner in U has a usable sb quote;
  - partial coverage, where unquoted runners are dropped and the race is flagged.

**Favourite.** The runner with the **highest** M_i. Co-favourites are runners within 1e-9 of the
maximum. For claim C, all co-favourites count as favourites.

**Eligibility is checked in two stages.**

1. **Pre-decision filters** (knowable at T; they define what the model acts on):
   - Australian meeting;
   - not a trial or jump-out;
   - |U| ≥ 5;
   - market-eligible;
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
  training data of each fit:
  - inside each screening fold, on that fold's training dates only;
  - for tune and final, on all train dates.
  - Not bookmaker-, time- or field-size-specific.
- **Raw market (α = 1).** Always reported as the secondary baseline.

## 5. Correction f and the selection procedure (frozen)

**Form.**

- Conditional logit with α·log M as a fixed offset.
- f is linear in the family features defined in `research/FACTORS.md`, each transformed as
  specified there, with fold-train scaling.
- **Missing values:** set to the fold-train mean (0 after standardisation), plus one
  missing-indicator per family.

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

**Amendment A** (before tune2) records the final family list, λ, the α fitted on all train, and
the commit ID.

**Trees and other learners** are exploratory throughout this protocol and cannot become primary.

## 6. Primary tests

**Intervals (one rule).**

- Percentile bootstrap over race-days, with 10,000 resamples and seed 20261031.
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
   - Claim B forward: the bookmaker's actual settlement (refunds, deductions).
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
- **Pass:** the interval's lower bound is above 0 on the final block **and** on the forward
  window.

**C. Upset rule.**

- **Rule.** At T, among non-favourites with P_i ≥ 0.10, take the one with the highest
  P_i / (M_i^α / Σ_j M_j^α). Nominate it if that ratio is ≥ 1.25. Otherwise abstain.
- **Scratched nominee.** If the nominee is a late scratching, the nomination is **void**: it is
  removed from the statistic and the void count is published. No substitute is nominated.
- **Benchmark.** The highest-M non-favourite in the same race. If the benchmark is the nominee,
  the race still counts, with a difference of 0.
- **Statistic:** mean over nominated races of [nominee won − benchmark won].
- **Pass:** the interval lies entirely above 0.
- **Secondary:** nominee log-loss and ROI at q.

**One verdict per claim.** The final block and the forward window each give exactly one verdict
per claim: pass, fail or inconclusive. No subgroup, decision time or bet type can change it.

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

## Amendments

_(none yet)_
