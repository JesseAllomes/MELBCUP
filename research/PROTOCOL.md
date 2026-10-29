# Validation protocol: does anything beat the bias-corrected market?

Status: **DRAFT v0, not frozen.** Sections marked _(fill at freeze)_ are completed from the dataset
build without looking at any outcome in the tuning or final blocks. The protocol is frozen by a
commit tagged `protocol-v1` before any tuning-block result is opened. After that, changes are
written as dated amendments below, never as edits, and none may touch the final block's rules.

## 1. Question and model

A runner's win probability is

    P_i = M_i^α · exp(f(X_i)) / Σ_j M_j^α · exp(f(X_j))

- `M_i`: the margin-free bookmaker consensus at the decision time (section 3).
- `α`: one bias-correction exponent (section 4).
- `f(X_i)`: a correction learned from information the market underuses (section 5).
  `f = 0` is the honest baseline, and it is what the app uses today (α = 1).

Three separate claims, each with its own primary test (section 6). A pass on one is not a pass on
another.

- **A. Winner model:** P is better calibrated and sharper than the bias-corrected market.
- **B. Betting edge:** bets chosen from P at live prices make money beyond chance.
- **C. Upset rule:** before the race, nominate at most one non-favourite, or abstain. The nominee
  beats a fixed benchmark.

Place, trifecta and First Four are **not** part of this protocol. Each would get its own protocol,
baseline and error budget.

## 2. Data, universe, blocks

- **Source.** racing.com's public form service, every Australian race meeting from 2022-07-01 to
  2026-10-29, one gzipped `getMeeting` per meeting (collector:
  `scratchpad/big/collect_adaptive.py`, query in `rcq.py`).
- **Dataset.** Built by `scratchpad/upsets/build.py` with a sha256 manifest. Manifest hash:
  _(fill at freeze)_. Code commit: _(fill at freeze)_.
- **Universe.** Australian states and territories only (no `HK`). No trials, no jump-outs.

**Eligibility, evaluated at the decision time.** A race counts only if:

- it has at least 5 starters;
- exactly one winner (dead heats are excluded and counted in the funnel);
- a starting price for every starter;
- for at least 80% of starters, a live decision-time quote from the bookmaker(s) used, no older
  than **900 seconds**.

Excluded races are kept in their own table. Primary metrics are also reported on them, as
exploratory.

**Inclusion funnel and field availability**, by year, state, bookmaker and decision time:
_(fill at freeze)_.

**Blocks, by race date.** Nothing outside a block's role may be computed from it.

| Block | Dates | Role |
|---|---|---|
| train | 2022-07-01 – 2025-06-30 | fit α, select features, fit f, choose λ (time-ordered CV inside train only) |
| tune1 | 2025-07-01 – 2025-12-31 | development; may be looked at repeatedly while refining |
| tune2 | 2026-01-01 – 2026-04-30 | **one** confirmatory look at the candidate fixed after tune1 |
| final | 2026-05-01 – 2026-10-29 | sealed; opened once, against the frozen commit |
| forward | races after the freeze | required confirmation for any claim B, and for any claim A or C that passes final |

If tune2 fails, the project goes back to train/tune1. The next confirmatory look then needs new
data (forward races). tune2 is never re-used as a fresh test.

## 3. Prices, timing and history (as-of rules)

- **Decision time T.** 30 minutes before the race's scheduled start (primary). T-10 and T-60 are
  secondary and exploratory.
- **Quote at T.** For each bookmaker, the last fluctuation at or before T. Its age is T minus the
  quote's timestamp. Quotes older than 900 seconds are unusable.
- **Bookmakers.** Sportsbet (`sb`) and Ladbrokes (`lb`).
- **M_i.** Each bookmaker's quotes are made margin-free within the race (normalise 1/price over
  the quoted starters). `M_i` is the mean of the available bookmakers' margin-free probabilities,
  renormalised over starters.
- **Favourite.** Shortest margin-free M at T. Co-favourites (ties to 1e-9) are all "favourites"
  for claim C.
- **History features.** Only races at **other** meetings on earlier calendar days, plus earlier
  race numbers at the **same** meeting (race order is fixed). Other meetings the same day are
  never used, because actual jump times are not reliable.
- **Field whitelist.** For a past race, only fields recorded for that run are used: finish,
  margin, starting price, barrier, weight, jockey, trainer, gear changes, settled/800/400
  positions, last-600 sectional, `timing` splits, stewards' comment, race distance, class and
  track condition.
  - Excluded: horse-profile or "current" fields (career stats, lastFive, current rating) and
    fields that may be written after the race (`speedValue`, `tempo`).
  - `handicapRating` at a past race is used, but flagged as possibly revised. Its effect is
    reported with and without it.
- **Order and scaling.** Features are computed event by event in time order. Within-race
  z-scores are allowed, since they use the same race's pre-race values. No scaling or encoding is
  fitted on anything but train.

## 4. Bias-corrected market

- **α.** One universal exponent, fitted by maximum likelihood (conditional logit on log M) on
  train only. Not bookmaker-, time- or field-size-specific.
- **Raw market (α = 1).** Always reported as the secondary baseline.

## 5. Correction f(X)

- **Form.** Conditional logit with α·log M as a fixed offset. `f` is linear in standardised
  features, with L2 penalty λ chosen by rolling-origin CV within train.
- **Missing values.** Set to 0 after standardisation, with a missing-indicator feature per family.
- **Feature families**, from `research/FACTORS.md`: closing-sectional rank, ground made, stewards'
  excuse and bad-sign flags, run style versus expected pace, same-meeting bias, track/rail change,
  market move from open to T at each bookmaker, bookmaker disagreement, jockey up/downgrade, stable
  form (as-of), class/rating change, unproven conditions with sire wet record, barrier ×
  field × distance, false-favourite and favourite-exposed composites.
- **Fixing the feature list.** The exact list is chosen on train and refined on tune1. It is
  written into amendment A **before** tune2 is opened.
- **Trees.** Gradient-boosted trees are exploratory only. They become primary only through
  amendment A.

## 6. Primary tests (one per claim)

**Intervals.** Every interval is a 95% percentile bootstrap over race-days (10,000 resamples,
seed 20261031), on the block being tested.

**A. Winner model.**

- Statistic: mean per-race log-loss of the market at α minus log-loss of P, on eligible races.
- **Pass:** the interval lies entirely above 0 (P improves).
- **Fail:** the interval lies entirely at or below 0.
- **Inconclusive:** otherwise.
- Also reported (secondary, not deciding): Brier score; calibration by probability band, price
  band, distance, class and track; raw-market comparison.

**B. Betting edge (level $1 win bets).**

- **Rule.** At T, back runner i if all of these hold:
  - P_i × q_i − 1 ≥ 0.05, where q_i is the best live quote at T across sb/lb, and the bookmaker
    is chosen from the T quotes;
  - P_i ≥ 0.04;
  - q_i ≤ 21.
- **Settlement.**
  - Winner: paid q_i. Dead heat: half.
  - If any runner is scratched after T, that race's bets are excluded and counted, because
    deductions are not in the data.
- **Statistic:** ROI.
- **Pass:** the interval lower bound is above 0 **and** forward confirmation on at least 1,000
  post-freeze bets gives a lower bound above 0. A positive point estimate alone is not a pass.

**C. Upset rule.**

- **Rule.** At T, among non-favourites with P_i ≥ 0.10, take the one with the highest
  P_i / M_i^α (normalised). Nominate it if that ratio is ≥ 1.25. Otherwise abstain.
- **Benchmark.** On the same races, the market's highest-rated non-favourite (second
  favourite).
- **Statistic:** win rate of the nominee minus win rate of the benchmark, paired over nominated
  races.
- **Pass:** the interval lies entirely above 0.
- Secondary: nominee log-loss and ROI at q.

**The final block produces exactly one of pass, fail or inconclusive per claim.** No subgroup,
time or bet-type result can change it.

## 7. Reporting

- Every primary statistic and interval is reported, whatever the outcome.
- The inclusion funnel and results on excluded races are reported.
- Staying races (≥ 2,800 m), Group 1 and fields of 16+ get their own row. A pass overall is not a
  pass for Cup-type races.
- Price movement from T to the jump is evidence, not profit.

## Amendments

_(none yet)_
