# Validation protocol: does anything beat the bias-corrected market?

Status: **DRAFT v0.2, not frozen.** v0.2 adopts the Astra review: contaminated races, the
decision clock, conditional ROI, stopping and multiplicity, and freezing the selection procedure. Sections marked _(fill at freeze)_ are completed from the dataset
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
| final | 2026-05-01 – 2026-09-28, less the examined races below | sealed; opened once, against the frozen commit. **Semi-blind** (see below): it can fail a claim, but a pass is only provisional |
| excluded | 2026-09-29 – 2026-10-29 | the development month: every race at every meeting on these dates is out of all confirmatory tests |
| forward | races starting 2026-11-01 00:00 AEST to 2027-04-30 23:59 AEST | the clean prospective test. **Required for every claim** before it is called a pass |

If tune2 fails, the project goes back to train/tune1. The next confirmatory look then needs new
data (forward races). tune2 is never re-used as a fresh test.

**Examined races (excluded from every confirmatory test, listed in `research/examined.csv`).**

- **The development month.** All races on 2026-09-29 to 2026-10-29: the PuntersEdge/FormFav
  collection used to fit weights, blend, value caps, factors and confidence bands; the agents'
  tests; and racing.com spot checks such as Caulfield 2026-10-10.
- **Individual spot checks.** Doomben 2026-08-01, whose race 1 finishing order and prices were
  printed while checking the data. Any other race whose outcome was displayed during
  development is added before the freeze.
- **Disclosed, not excluded.** The Betfair agent's held-out study (BSP market and horse-history
  variables, Betfair data, 2025-01 to 2026-09) looked at outcomes over the tune and final dates
  through a different dataset. No racing.com form was examined there, but its conclusions (e.g.
  price moves and last-start variables add nothing beyond BSP) shaped expectations. This is why
  the historical final block is semi-blind and the forward block decides.

## 3. Prices, timing and history (as-of rules)

- **Decision time T.** The race's scheduled start, as recorded by racing.com (`races.time`),
  minus 30 minutes (primary). T-10 and T-60 are secondary and exploratory.
  - The recorded start is the final schedule. If a meeting was re-timed, it reflects the
    re-timing, which was announced before T in the normal course.
  - Races whose recorded start differs from the first fluctuation day by more than a day are
    excluded as unreliable timing, and counted.
  - Forward: the app logs T against the schedule it saw at that moment.
- **Quote at T.** For each bookmaker, the last fluctuation at or before T. Its age is T minus the
  quote's timestamp. Quotes older than 900 seconds are unusable.
- **Bookmakers.** Sportsbet (`sb`) and Ladbrokes (`lb`).
- **M_i.** Each bookmaker's quotes are made margin-free within the race (normalise 1/price over
  the quoted starters). `M_i` is the mean of the available bookmakers' margin-free probabilities,
  renormalised over starters.
- **Favourite.** Shortest margin-free M at T. Co-favourites (ties to 1e-9) are all "favourites"
  for claim C.
- **History features (primary).** Only races on **earlier calendar days**. No result from the same
  day is used, at the same meeting or any other: the race before at the same meeting has often
  only just started by T, and the data has no result-availability timestamp.
- **Same-day history (exploratory only).** Same-meeting bias and same-day connections' form use
  earlier race numbers at the same meeting. They become primary only if a result-availability
  timestamp is obtained.
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
- **Selection procedure, frozen now.**
  1. **Screening on train.** Rolling-origin CV with 6 folds by quarter, each trained on all
     earlier train dates. Each family is fitted alone with the offset.
  2. **Keep or drop.** A family is kept if its mean CV log-loss gain is above 0 in at least 4 of
     the 6 folds.
  3. **Combined fit.** The kept families are fitted together, with λ chosen from
     {0.3, 1, 3, 10, 30} by the same CV.
  4. **Refining on tune1.** May drop families or re-tune λ, but may not add families that failed
     screening.
- **Fixing the feature list.** The resulting list and λ are written into amendment A, with the
  commit ID, **before** tune2 is opened.
- **Trees.** Gradient-boosted trees are exploratory only. They become primary only through
  amendment A.

## 6. Primary tests (one per claim)

**Intervals.** Every interval is a 95% percentile bootstrap over race-days (10,000 resamples,
seed 20261031), on the block being tested.

**Late scratches and probability scoring (claims A and C).** P and the market are computed at T
over the runners then accepted. If a runner is scratched after T, both are renormalised over the
actual starters, identically, before scoring. Races with a dead heat are excluded (funnel).

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
  - Historical: if any runner is scratched after T, that race's bets are excluded, because
    deductions are not in the data. The historical ROI is therefore labelled **conditional on no
    late scratching**. The excluded exposure (bets, stake, and what they would have returned
    ignoring deductions) is published beside it.
  - Forward: every placed bet counts, with the bookmaker's actual settlement: deductions, refunds
    and voids included. Nothing is excluded.
- **Statistic:** ROI.
- **Pass:** the historical interval lower bound is above 0, **and** the forward ROI interval lower
  bound is above 0 at the fixed end date (section 6a). A positive point estimate alone is not a
  pass.

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

### 6a. Multiplicity and stopping

- **One family.** The three claims form one family. Each primary interval uses
  1 − 0.05/3 = **98.33%** (Bonferroni), on the final block and again on the forward block.
- **Forward stopping rule.** The forward test runs on a fixed calendar window: races from
  2026-11-01 to 2027-04-30. It is evaluated **once**, after that window, whatever the interim
  numbers show.
  - No interim looks are used for decisions.
  - The window is not extended.
  - Fewer than 1,000 claim-B bets, or 300 claim-C nominations, in the window means
    **inconclusive**, not "keep going".
- **Overall verdict.** A claim is supported only if it passes on the final (semi-blind) block
  **and** the forward block. Any other combination is reported as it stands.

## 7. Reporting

- Every primary statistic and interval is reported, whatever the outcome.
- The inclusion funnel and results on excluded races are reported.
- Staying races (≥ 2,800 m), Group 1 and fields of 16+ get their own row. A pass overall is not a
  pass for Cup-type races.
- Price movement from T to the jump is evidence, not profit.

## Amendments

_(none yet)_
