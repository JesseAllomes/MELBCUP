# Ability rating test: a margin-based rating against the market

**2026-10-30. Outcome statistics come from block = train only (2023-01-01 to 2025-06-30): eligible
races, scored as `screen.py` scores them, 17,479 races and 176,433 runners. The validation quarters
2024Q1 to 2025Q2 hold 9,912 races. Ratings are built from run history, which includes non-eligible
races and the history_only block. No statistic is computed on those rows, and no run on or after
2025-06-30 is ever read. Scripts and logs are in
`scratchpad/upsets/rating/`: `build_ratings.py`, `evaluate_rating.py`, `leakcheck.py`, `full_main.log`,
`full_l0.log` and `s_*.log`.**

## 0. Answer

The rating works as an ability measure. On its own, with no prices, it improves validation log-loss
by **0.157 nats/race** over picking at random. The T−30 market improves it by 0.439, so the rating
holds about a third of what the market knows.

It adds nothing beyond the market. The out-of-fold gain over the α·log M offset is
**−0.006 millinats/race [−0.013, +0.002]**, and it beats the offset in **1 of 6 folds**. The chosen
λ is 30, the largest in the grid. The coefficient is slightly negative in every fold. The same null
holds for every variant tried, for the unpenalised fit, for the favourite-wins model and against
the T−2 market.

In the owner's terms, the rating confirms or overturns a favourite differently from the market in
**0.8% of races**. Nearly all of those are tied co-favourites, and they win at the same rate as the
favourite. When the top-rated horse is not the favourite (64% of races), it wins 14.0%. Its price
said 13.7%.

## 1. Method

### 1.1 Per-run performance figure (kg scale)

For every Australian flat run that started, finished and has a recorded margin and weight
(542,847 runs, 47,917 horses, 57,662 races from 2022-07-01 to 2025-06-29; trials, jumps and Hong Kong
are excluded):

    y = (weight_kg − 56) − kg_per_length(d, going) × min(beaten_lengths, 15)
    kg_per_length = 1.25 × (1200 / d)^(1/3) / going_mult,   going_mult: Firm/Good 1.00, Soft 1.05, Heavy 1.40

| Choice | Value | Why |
|---|---|---|
| Margin | `margin_behind_len`: cumulative lengths behind the winner (winner = 0) | The winner's superiority is already in the second horse's margin. The race constant goes into the race standard. |
| Cap | 15 lengths (about the 95th percentile) | Beyond that the horse has usually been eased down. Margins up to 509 L exist in the data. |
| Lengths to kg | 1.25 kg per length at 1200 m on a good track | Between Timeform's scale (about 1.1 kg) and the Australian handicapping rule of thumb (about 1.5 kg). |
| Distance scaling | d^(−1/3) | Fitted on margin spread only, in 2023 train races (before any validation quarter). The spread of the first six finishers grows as d^0.33 (7,158 races). Timeform's 1/d would over-weight sprint margins. |
| Going scaling | Soft ×1.05, Heavy ×1.40 spread | Same 2023 fit. Lengths are worth less on rain-affected ground. |
| Weight | +1 kg of figure for each kg carried | This is the definition of a kg-scale rating. The variant without the weight adjustment is in section 3.4. |

The race's own going, distance and track speed reach the rating through the race standard below.
The going value is the final race-day record, and it is used only for past runs, never for the race
being predicted.

### 1.2 Joint model of race standard and horse ability, rebuilt for each race day

At each cut day D, the model is fitted on the runs from D − 730 days up to **the day before D (strictly
earlier Melbourne calendar days)**:

    y_k = h_horse + c_class + r_race + e_k
    minimise Σ w_k e_k² + λ_h Σ h² + λ_r Σ_j W_j r_j²,   w_k = exp(−(D − day_k)/τ)

- **h** is the horse rating in kg. It has an exponential time decay with a 180-day half-life, so
  recent runs dominate. The ridge λ_h = 1 is one fresh run's worth, which shrinks horses with few or
  old runs towards average.
- **r** is the race standard: how much faster or slower the race was than its runners' ratings
  imply, after the class effect. λ_r = 1 runner's worth. The race standard for a past race is
  re-estimated every day from all information before D. Every race standard used for day D's
  ratings therefore comes only from earlier days.
- **c** is a class effect for each racing.com class (Maiden, BM58, BM64, ..., Listed, G1). It is
  unpenalised. It mainly sets the level for weakly connected races, such as maidens full of
  debutants.
- The model is solved by alternating exact block updates. Each day warm-starts from the previous
  day's solution and runs three sweeps (150 on the first day). Convergence was checked every 120
  days: 100 extra sweeps moved target ratings by at most 0.02 kg. The rating SD across active horses
  is about 2.7 kg.

**Minimum-runs rule.** A horse is rated if it has at least 2 runs in the window. Otherwise it is
missing and gets an indicator. 87.6% of scored runners are rated, and 98.1% of races have at least
two rated runners.

### 1.3 The reviewer's leakage warning

The warning: a rating fitted jointly over all runs leaks a horse's later runs into its earlier
rows. **This build does not do that.** The joint fit (race standards and horse abilities together)
is repeated for every race day D, using only runs on Melbourne calendar days before D. It is never a
single global fit, and no rating or race standard for day D uses anything from D or later. Every
eligible train race day has its own fit.

Verification (`leakcheck.py`) took three days: 2024-02-17, 2024-11-02 and 2025-06-14. For each day,
all runs on or after D were physically deleted, and the rating was rebuilt from a cold start with
400 sweeps. The rebuilt ratings agree with the stored sequential ratings to within **0.014 kg
maximum** (mean 0.002 kg; correlation 1.00000), which is the convergence tolerance. Validation
quarters cannot leak either: a validation race's rating uses only runs before its own day. The
rating has no fitted parameter that sees outcomes in the validation quarters. The two scale
constants (distance and going spread) came from 2023 margins only.

### 1.4 Features for today's race

The field is the starters in the T−30 universe, as in `screen.py`.

- `rel` = rating − the mean rating of the rated runners in the field (kg).
- `rankscore` = 1 − (rank − 1)/(n_rated − 1) among the rated runners (1 = top-rated).
- `miss` = the runner is unrated (fewer than 2 runs).
- `rel` and `rankscore` are z-scored on fold-train moments. Missing values are filled with 0, which
  equals the training mean, as in `screen.py`.

### 1.5 Test

The test follows `screen.py` exactly:

- `Races`, `newton` and `fit_alpha` are imported from an unmodified copy of `screen.py`.
- There are six quarterly folds, 2024Q1 to 2025Q2. Each trains on 2023-01-01 up to the start of its
  quarter.
- α is fitted for each fold. The offset is α·log M_T−30.
- The objective is mean per-race log-likelihood − λ/2‖w‖².
- λ is chosen from {0.3, 1, 3, 10, 30} by mean validation log-loss.

The gain is reported over the offset-only model in nats per race. Its 95% interval comes from a
race-day cluster bootstrap (2,000 resamples of Melbourne race days, pooled over the six validation
quarters).

## 2. Results

### 2.1 Gain over the T−30 market

Gain in millinats per race; a positive number means the rating helps.

| λ | Mean validation log-loss | Mean fold gain | Folds better |
|---|---|---|---|
| 0.3 | 1.844127 | −0.168 | 1/6 |
| 1 | 1.844055 | −0.095 | 1/6 |
| 3 | 1.844003 | −0.043 | 1/6 |
| 10 | 1.843974 | −0.015 | 1/6 |
| **30 (chosen)** | **1.843965** | **−0.005** | **1/6** |

**Chosen model:** the pooled gain is −0.006 millinats/race, 95% interval [−0.013, +0.002], over
9,912 races. It is better in 1 of 6 folds (2025Q1).

Gain by fold at λ = 30, in millinats: −0.006, −0.010, −0.014, −0.002, +0.007, −0.005.

The coefficients are negative in all six folds at every λ:
- At λ = 30 (z units): w_rel ≈ −0.0002, w_rank ≈ −0.0003, w_miss ≈ −0.0001.
- At λ = 0.3, the `rel` coefficient is −0.002 to −0.004 per kg above the field mean.
- Unpenalised (λ = 10⁻⁶), `rel` is −0.001 to −0.011 per kg and the gain is −0.46 millinats
  [−0.87, −0.08], better in 2 of 6 folds. Freed from the penalty, the rating makes the fit worse.

λ keeps rising to the edge of the grid because the best weight is zero. The market already prices
the rating fully. Any weight on it is overfitting noise.

### 2.2 The rating is a real ability measure

Validation races, conditional logit on the rating features alone, with no prices:

| Model | Log-loss | Gain over uniform (nats/race) |
|---|---|---|
| Uniform | 2.2828 | — |
| Rating only | 2.1261 | +0.157 |
| T−30 market (α·log M) | 1.8440 | +0.439 |

The top-rated horse wins 22.2% of the time, and the T−30 favourite 33.3%. The rating holds about 36%
of the market's information over uniform, and all of that 36% is already in the price.

### 2.3 Owner-facing metrics (validation races)

**Favourite-wins separation.**

| Favourite-wins model | Log-loss | Gain, millinats [95% day CI] | Folds better |
|---|---|---|---|
| Logistic on logit p_fav (market) | 0.6051 | — | — |
| + favourite's rating gap to the best other runner, missing flags | 0.6053 | −0.22 [−0.46, +0.00] | 1/6 |
| P(fav) from the chosen conditional logit vs offset-only | 0.6052 vs 0.6052 | −0.00 [−0.01, +0.00] | — |

The gap coefficient is about −0.01 per SD in five folds and 0 in one.

**Favourite's win rate against its T−30 price, by where it sits on the rating:**

| Favourite is... | Races | Wins | Market p | A/E |
|---|---|---|---|---|
| Top-rated | 3,478 (35%) | 0.372 | 0.361 | 1.03 |
| Rated, not top | 5,253 (53%) | 0.296 | 0.301 | 0.98 |
| ≥2 kg below the best other runner | 1,435 (14%) | 0.274 | 0.284 | 0.97 |
| Unrated, or fewer than 2 rated in the field | 1,181 (12%) | 0.378 | 0.369 | 1.03 |

A/E is wins divided by the market probability (1.00 = the price was right). The directions are the
intuitive ones, but the spread is within about ±1.5 standard errors. The fitted models above
(trained on earlier data) find no usable signal in it.

**Confirm/overturn decisions.**

| Decision | Market alone | Chosen rating model (λ = 30) | Unpenalised rating model |
|---|---|---|---|
| Model's top pick ≠ T−30 favourite | — | 76 races (0.8%): pick wins 22.4%, favourite 19.7% (both priced at 21.1%; these are near-ties between co-favourites) | 171 races (1.7%): pick wins 21.1%, favourite 22.8%; difference −1.8 points [−12.0, +8.9] |
| Confirm (P(fav) ≥ 0.5) | 761 races, favourite wins 59.7% | 760 races, 59.6% | 735 races, 60.0%. 10 newly confirmed win 60%; 36 dropped win 53% at a price of 50% |
| Confirm (P(fav) ≥ 0.4) | 2,277 races, 51.6% | 2,276 races, 51.6% | 2,223 races, 51.8% |
| Any decision changed | — | 77 races (0.78%) | 217 races (2.2%) |

**Market-free override.** "Name the top-rated horse when it is not the favourite" applies in 6,239
of 9,717 races (64%). The top-rated horse wins 14.0% against a price of 13.7%. The favourite wins
30.9% against 31.2%. Both are priced correctly.

### 2.4 T−2 check (later market)

All 17,479 races have a full T−2 two-book market (M_T−2: the mean of the margin-free Sportsbet and
Ladbrokes T−2 quotes). Same folds; λ = 30 unless stated.

| Offset | Offset-only validation log-loss | Rating gain, millinats [95% CI] | Folds better |
|---|---|---|---|
| α·log M_T−30 | 1.8440 | −0.01 [−0.01, +0.00] | 1/6 |
| α·log M_T−2 | 1.8083 | −0.00 [−0.02, +0.01] | 2/6 |
| α·log M_T−2, unpenalised | 1.8083 | −0.58 [−1.06, −0.09] | 1/6 |

The late market moves 36 millinats from T−30. The rating holds none of that late information.

### 2.5 Sensitivity

These were all decided before seeing the results. None changes the answer.

| Variant | Chosen λ | Gain, millinats [95% CI] | Folds better |
|---|---|---|---|
| Main (180-day half-life, ≥2 runs, weight-adjusted) | 30 | −0.006 [−0.013, +0.002] | 1/6 |
| Half-life 90 days | 30 | −0.003 [−0.009, +0.003] | 1/6 |
| Half-life 365 days | 30 | −0.006 [−0.012, +0.001] | 1/6 |
| Minimum 1 run | 30 | −0.008 [−0.018, +0.002] | 1/6 |
| Minimum 3 runs | 30 | −0.004 [−0.012, +0.004] | 1/6 |
| No weight adjustment | 30 | −0.003 [−0.006, +0.001] | 2/6 |
| Main, unpenalised (λ = 10⁻⁶) | — | −0.46 [−0.87, −0.08] | 2/6 |

In every variant the smallest λ (0.3) also loses: the mean fold gain is −0.09 to −0.22 millinats.

## 3. Limitations

- **This is one rating, built simply.** It has no horse-specific distance or going aptitude, no
  sectional or speed figures, no pace or trip adjustment, and no age progression term beyond the
  time decay. A richer model could hold more than 36% of the market's information. But the market
  prices this 36% fully. A better rating would have to find ability the market misses, not just
  measure ability better. Nothing here suggests that it would.
- History starts on 2022-07-01, so early-2023 training rows have thin histories. Validation
  quarters have at least 18 months of history.
- Only one combination of λ_h, λ_r, the cap and the kg-per-length scale was built (they were set
  before testing). The sensitivity table varies the inputs most likely to matter. All are null.

## 4. Conclusion in plain English

We built the kind of rating professional form analysts and the big betting syndicates rely on. Every
past run is turned into a figure: how far the horse was beaten, how much weight it carried, and how
strong that race was, judged from what its rivals had done before. Those figures are combined, with
recent runs counting most, into a single number for each horse on each race day, using only races
run before that day.

The rating does measure ability. Without looking at any prices, it picks a third of the information
the betting market has. But **the market already knows all of it**. Adding the rating to the T−30
price does not improve prediction in any of six test quarters. It does not tell apart favourites
that win from favourites that lose. When the best-rated horse is not the favourite, it wins exactly
as often as its price says. Against the T−2 price the result is the same.

For the owner's goal, the rating changes the confirm-or-overturn call in fewer than 1 race in 100,
and those changes do no better than following the favourite. **Verdict: no. A margin-based ability
rating does not help confirm or overturn favourites beyond the price.** It backs up the earlier
finding that public form is fully in the price at T−30. Whatever the market does not know, it does
not lie in how well horses have run before.
