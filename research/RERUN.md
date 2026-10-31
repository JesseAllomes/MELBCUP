# RERUN: late money, every factor, every bet type (milestone m8)

**Answer for the owner (written after the one test; the rules below were frozen before it).**
1. **Late money tells us almost nothing the late price does not.** The market does sharpen into the jump (most in the last 10 minutes), but a runner's move since the open adds at most 0.0013 nats per race at T-10, 0.0005 at T-5 and 0.0002 at T-2, and on the unseen test block it adds nothing (T-2 +0.0005, interval -0.0001 to +0.0011).
2. **No other factor helps either.** Of 20 families (form, margins, class, track/distance, fresh, barrier, weight, jockey, trainer, sectionals, pace, stewards, spread), none gains more than 0.00006 nats per race; the kept ones combined do no better than the price alone.
3. **Frozen win rule:** at 2 minutes before the jump, back a runner at its Sportsbet price when (corrected chance from the price, move and Sportsbet-v-Ladbrokes spread) x price - 1 >= 2% and chance >= 10%. **Test (Jan to Apr 2026): 3 bets (one race), 1 winner, ROI +27%, no interval possible.** The current agreed rule: 4 bets, ROI -5%.
4. **Nothing is good enough to switch on for Cup day.** Win, place and each-way fire too rarely to test; quinella, exacta and trifecta boxes lose on test (-24%, -7%, -10%; none above zero). Keep the current agreed rule and treat bets as entertainment.
5. The one real gain is the old favourite-longshot correction (chance = price^1.14): +0.0075 nats per race on test, interval +0.0040 to +0.0110. It sharpens chances but does not beat Sportsbet's margin.

## 1. Blocks and why
| Block (Melbourne dates) | Use here |
|---|---|
| train 2023-01-01 to 2025-06-30 and tune1 2025-07-01 to 2025-12-31 | development: all screening, tuning and fitting (8 expanding quarterly folds, 2024Q1 to 2025Q4, out-of-fold) |
| **tune2 2026-01-01 to 2026-04-30 (2,438 races at T-2, 120 race days)** | **the one test, run once** (`test.py` refuses a second run and refuses to run unless this file holds the frozen sha256) |
| final 2026-05-01 to 2026-09-28 | untouched: sealed for round 2 and semi-blind (the Betfair study saw its outcomes) |
| 2026-09-29 to 2026-10-29 | examined month, unused |
Why tune2: model-v1 saw it once at T-30 without move features; no T-10/-5/-2 price, move or bet statistic had ever been computed on it. Disclosed: model-v1's F12 family used a T-30 favourite move, and the protocol says tune2 is "never reused", so this spends that rule for a new claim. The round-2 holdout stays sealed.

## 2. Method
- Source: the 12,129 racing.com dumps on `data` (b52e2f3, all 12,129 hashes match MANIFEST; 5 gz files are truncated at source and were skipped). `research/dataset/build.py` rebuilt unchanged except extra snapshot columns (`late_money/build_lm.py`); my per-T consensus (`prep.py`) equals the build's at T-10 and T-2 to 1e-16. `extras.py` adds Sportsbet/Ladbrokes prices at -120, -15, the jump, the stored place prices and the stored tote dividends.
- Price path per runner: first fluc seen, then latest fluc at or before -120, -60, -30, -15, -10, -5, -2, jump; SP. Consensus M = mean of the two books' margin-free chances, over runners in the protocol universe. Races kept: every runner priced by both books, both books live in the last 15 minutes, one winner, no late scratchings.
- Model: conditional logit, offset alpha x ln M (alpha fitted per fit) plus ridge-penalised standardised features. MOVE = open to -60, -60 to -15, -15 to T (race-centred), firm/drift split, move x price; SPREAD = Sportsbet v Ladbrokes. Intervals: 2,000 resamples of race days.
- Families: all F1-F18 of FACTORS.md plus margins, class change, fresh/first-up/second-up, weight, form price. Kept if better out-of-fold in 5 of 8 folds with positive mean.

## 3. When money comes in (development, 19,986 races, 1,083 race days, price-only)
| Segment | Median abs move | Runners moving 5%+ | Share of all squared move |
|---|---|---|---|
| first fluc seen to -120 | 23% | 86% | 62% |
| -120 to -60 / -60 to -30 | 0% / 0% | 19% / 25% | 2% / 3% |
| -30 to -15 / -15 to -10 | 4.7% / 3.6% | 47% / 41% | 6% / 4% |
| -10 to -5 / -5 to -2 / -2 to jump | 7.4% / 6.3% / 6.3% | 61% / 56% / 56% | 9% / 7% / 6% |
- Firm 10%+ (price down from first seen to the jump): 38.6% of runners (79% of them already by -120, 86% by -10, 94% by -2); 20%+: 28.7% (72/82/93%); 30%+: 19.7% (66/78/91%). Drift 10%+: 43.4% (57/70/89%). Prices are quiet from -120 to -30 and busiest in the last 10 minutes. By price: 64% of runners at $3 or under firm 10%+, 63% of those at $20+ drift 10%+.
- The first fluc is the first the collector saw (often the day before), so "open" is not the bookmaker's opening price.
- **The chance of a win does rise into the jump** (19,309 common races, log-loss of the margin-free market): -120 1.8537, -60 1.8526, -30 1.8508, -15 1.8439, -10 1.8383, -5 1.8272, -2 1.8193, jump 1.8120, SP 1.8105. Winners' implied chance 19.8% at -120, 20.2% at -10, 21.0% at the jump. Last 10 minutes: +0.0263 nats; -120 to -30: +0.0029.

## 4. Does the earlier move change the true win chance? (log-loss gain, nats x 1000 per race = millinats; day-bootstrap 95%)
| T | Dev: alpha-only over raw | Dev: move+spread over alpha-only | Dev: all kept families + move | Test: move+spread over alpha-only | Test: staying 2000m+ |
|---|---|---|---|---|---|
| -10 | +7.2 [5.6, 8.9] | **+1.31 [0.45, 2.15]** | +1.01 [0.13, 1.87] | -0.24 [-1.92, +1.21] | -6.5 [-12.0, -1.4] |
| -5 | +7.0 [5.3, 8.7] | +0.51 [-0.04, 1.06] | +0.23 [-0.15, 0.62] | +0.74 [-0.10, +1.57] | -1.8 [-4.9, +1.2] |
| -2 | +6.3 [4.8, 7.8] | +0.23 [-0.15, 0.59] | +0.01 [-0.05, 0.06] | +0.51 [-0.15, +1.14] | -0.2 [-2.3, +1.9] |
Test alpha-only over raw: +8.4 [4.8, 12.0], +7.8 [4.1, 11.5], +7.5 [4.0, 11.0]. Move+spread: the one development interval above zero (T-10) is not repeated on test (sign flips) and shrinks to nothing as the jump nears, i.e. the late price already holds the move.
Calibration, actual wins / expected (A/E), T-2 (test interval for the move model):
| Group | Dev raw | Dev alpha | Dev +move | Test raw | Test alpha | Test +move [95%] |
|---|---|---|---|---|---|---|
| Firmed 10%+ since first seen | 1.04 | 1.01 | 1.00 | 1.05 | 1.03 | 1.02 [0.99, 1.05] |
| Steady (within 10%) | 0.99 | 0.98 | 0.98 | 0.99 | 0.99 | 0.98 [0.91, 1.05] |
| Drifted 10%+ | 0.93 | 1.00 | 1.02 | 0.89 | 0.95 | 0.96 [0.90, 1.03] |
| Drifted 10%+ in the last 15 minutes | 0.91 | 0.95 | 0.98 | 0.85 | 0.90 | 0.92 [0.85, 0.99] |
Firmers are priced about right once the long-shot bias is removed; most of the "drifters win less" effect is price level (long-shots). The one residual: runners that drift in the last 15 minutes still win 5 to 10% less than their price says (dev T-2 0.95 alpha, test 0.90). That says avoid them, not back anything. No family helps: best gains (millinats, T-10/-5/-2) F12 favourite gap +0.05/+0.05/+0.06, rating/class +0.02, pair +0.01, sectionals +0.005, others negative (weight -0.19, margins -0.15, excuses -0.13, form price -0.10). The kept-families model is worse than the price (-0.01).

## 5. Frozen rules, test result, verdict (frozen.json sha256 `b94503d76ebd0c14f71a93ff7b63c6e974f90ae5c748f2aeda99fef9e4ff3141`)
Tuned on out-of-fold development only (win: 5 edges x 6 minimum chances x 3 T x 2 models, objective log growth at 1% per bet; others by development ROI). Win/place/each-way: 1 unit; exotics: $1 per combination. Profit per day = units per race day (120 days).
| Bet (frozen rule) | Dev bets, ROI | Test bets | Strike | Test ROI [95% day bootstrap] | Per day | Benchmark (current rule): bets, ROI [95%] | Verdict |
|---|---|---|---|---|---|---|---|
| Win, T-2: P x Sportsbet price at T - 1 >= 0.02 and P >= 0.10 | 26, +30% | 3 (1 race) | 33% | +27% [not estimable] | +0.007 | 4, -5% [not estimable] | **not proven**, off |
| Place, T-2: place chance x stored place price - 1 >= 0.10, P >= 0.10 | 39, -2% | 2 | 0% | -100% [n/a] | -0.017 | 13, +2% [-89%, +171%] | off (untestable) |
| Each-way, T-2: combined edge >= 0.05 | 34, -16% | 1 | 0% | -100% [n/a] | -0.008 | 1, +313% [n/a] | off |
| Quinella, T-5: top-2 pair when hit chance >= 0.5 | 68, +8% | 17 | 47% | -24% [-60%, +17%] | -0.03 | 2,426 (box of 3), -17% [-23%, -11%] | **off** |
| Exacta, T-2: box top 3 when hit chance >= 0.7 | 219, -7% | 60 | 72% | -7% [-40%, +41%] | -0.21 | 2,436 (top-2 straight), -19% [-30%, -9%] | off |
| Trifecta, T-2: box top 4 when hit chance >= 0.6 | 516, -11% | 126 | 71% | -10% [-34%, +19%] | -2.45 | 1,450 (box 4, chance >= 0.2), -21% [-29%, -13%] | off |
| First four | none stored after 2023-10-18 | 0 | - | - | - | - | off (untestable) |
| Multi: doubles of frozen win bets | - | 0 | - | - | - | 0 | off |
Verdict rule: "switch on" needs a test interval wholly above zero and a positive development ROI; none qualifies. Exactas and trifectas lose less than the benchmark because the frozen boxes are chalk (about 70% strike), not because late money helps; their intervals still include the usual 10 to 20% tote loss.
- **The win rule does not use late money.** The same rule without move features fires the same 3 bets on test (22 v 26 on development). It fires on the market's top few runners (median rank 2, prices $1.90 to $10) in 13 development races, about half because the price-power correction lifts the chance above Sportsbet's price and half because the consensus already beats it; only 2 of 26 development bets had Sportsbet 10% longer than Ladbrokes. The three test bets are three co-favourites in one race ($3.30 to $3.80), so they are one event, not three.
- Looser descriptive reading (edge 0, any chance): 5 bets, ROI -24%. Other T, same thresholds: T-10 1 bet (lost), T-5 0 bets.

## 6. Side views (nothing tuned)
- **Staying races 2000m+** (205 races in test): no frozen win or place bets; the move model is no better than the price (table above; worse at T-10, -6.5 millinats [-12.0, -1.4]).
- **Melbourne Cup** (3 Cups in the scored archive, 2023-25; none in the test block). Winner's Sportsbet price, first seen / -60 / -10 / jump: 2023 $7.0/8.0/7.5/8.0 (third favourite); 2024 $126/67/67/91 (20th in the betting); 2025 $7.0/8.5/9.0/9.0 (third favourite). Runners firming 20%+ since first seen: 25, 1 winner (the jump prices implied 1.0); drifting 25%+: 13, 1 winner (0.9 implied); firming 10%+ in the last 15 minutes: 10, 0 winners (0.6 implied). Nothing to see at n = 3.

## 7. Limits
- Feed-liveness (both books in the last 15 minutes) drops about half of all races; Cup day will be live, but the test sample is the busy races. T is reconstructed from the recorded start ("T approximate").
- Sportsbet's price at T is the latest fluc, whatever its age; nothing records whether the price would have been accepted for a real stake. Place and each-way use the last stored place price (about the jump), so only T-2 is meaningful; the 4-places-at-1/4-odds terms are not stored. Tote dividends are known only after the race.
- Few bets: the win rule fires about 13 times a year in this sample, so no interval can separate it from luck. Exotic structures and thresholds were chosen by best development ROI from a wide grid, so their development ROIs are optimistic; the test numbers are the honest ones.
- Multis are legs at their own T (an upper bound), not executable. The 2026 Melbourne Cup is not in any block. A forward test needs live-logged quotes at the decision time (the live collector).

Reproduce: `research/late_money/` (`build_lm.py`, `extras.py`, `prep.py`, `describe.py`, `screen_models.py`, `tune.py`, `freeze.py`, `report_dev.py`, `dev_summary.py`, `test.py`, `side_views.py`); data under the session scratchpad `lm/`. No app code or git state was changed.
