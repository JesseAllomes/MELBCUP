# Horse racing: free data, market first, honest hold-out

Branch `sport-racing`. Everything below is rebuilt by the scripts in `tools/sports/racing/`
(`fetch.py`, `build.py`, `test.py`, `report.py`, `publish.py`); raw downloads live outside git.

## Verdict (plain)

1. **Nothing beats the market by a margin we could bank.** Back every runner at Sportsbet and you
   lose 28% (the margin). That was true on the hold-out (2025-26) and on the forward months
   (Aug-Oct 2026).
2. **The one correction that works is the favourite-longshot one.** Raising the de-margined chance
   to the power 1.13 (fitted on 2022-25) improves log loss by +0.0048 nats per race (95% range
   +0.0034 to +0.0061) on the hold-out, and by +0.0054 (+0.0025 to +0.0085) on the forward months.
   The app already uses 1.14 (`MARKET_ALPHA`); this study confirms it independently.
3. **Betfair's starting price (BSP) is already calibrated** (alpha 1.00) and beats the uncorrected
   Sportsbet price on identical races by +0.0107 nats (+0.0088 to +0.0127). After the power
   correction the bookmaker price is within 0.006 of BSP. The most trustworthy price is the
   exchange; Ladbrokes and tote are not distinguishable from Sportsbet once corrected.
4. **Form-type features add almost nothing**: +0.0010 nats over the power-corrected price
   (+0.0003 to +0.0017) on the hold-out. That is at the edge of the noise, tiny, and not confirmed
   by a betting test (see ROI). Not recommended for deployment.
5. **No +EV claim.** "Value" bets from the feature model show +13% to +16% ROI at Sportsbet's
   price on the hold-out (95% range clears zero for two of five variants), but the 99% range
   (a rough 5-variant correction) includes zero, the sample is 600 to 900 bets, and the forward
   months (250 to 485 bets) are +12% to +20% with ranges that include zero. Promising, not
   established. The Sportsbet price here is the one at the start of the race, not one the owner
   could necessarily take earlier.

## Sources and rows

| Dataset | Source (free, no login) | Rows | Races | Seasons |
|---|---|---|---|---|
| `dataset.csv.gz` | racing.com `getMeeting` dumps, every Australian meeting, collected once on 2026-10-29 (`research/dataset/collect_adaptive.py`, preserved on branch `data`) | 820,073 starters | 85,802 | 2022-23 to 2025-26 full; 2026-27 to 29 Oct 2026; 1 month of 2021-22 |
| `betfair.csv.gz` | Betfair Data Scientists public ANZ thoroughbred BSP files | 1,284,154 runners | 131,049 | 2019-20 (Dec onward) to 2026-27 (to Sep 2026) |

`fetch.py` restores the racing.com dumps from the `data` branch (no new load on racing.com) and
downloads the Betfair files (robots allows, cached, 2 s sleep). Five April 2025 meeting files were
truncated at the source and are skipped (`build_meta.json`). 203 dead-heat races are kept for
fitting but left out of log-loss scoring. 83% of racing.com starters join to a Betfair BSP row
(Hong Kong is not in the Betfair files and is dropped from tests).

Prices per starter: Sportsbet (`sb`), Ladbrokes (`lb`), two totes, racing.com starting price
(`sp`), Sportsbet's first fluctuation, Betfair BSP and pre-play average. Sportsbet coverage 88.5%
of starters. Place prices at Sportsbet, Ladbrokes and tote are kept too.
Player props do not exist in racing, so the "type" splits are by market type, state, field size,
distance, race type and going.

## Protocol

- Train and tune on 2022-23, 2023-24, 2024-25 only (Betfair file: 2019-20 to 2024-25).
- **Sealed hold-out: 2025-26** (the latest full season). Looked at once the code was frozen.
- Forward check: 2026-27 (Aug to Oct 2026), touched only after the hold-out.
- Intervals: 95% bootstrap over race days (2,000 resamples) for log loss and ROI; Wilson 95% for
  hit rates. ROI also at 99% as a rough correction for the five look-alike value rules.
- Margin removal: proportional (baseline); power / favourite-longshot (alpha fitted on train);
  conditional-logit feature layer on top. Kept only if it wins out of sample.
- **Things tried: 37** model, calibration and ROI cells (see `tried_log` in
  `holdout_results.json`), plus 196 type-by-band calibration cells. Counts are reported with
  the results.

## Results

### Log loss per race by price source (hold-out 2025-26, each on its own complete races)

| Source | Overround | Races | Proportional | Power (alpha from train) | Gain of power (95%) |
|---|---|---|---|---|---|
| sb | 1.217 | 16,866 | 1.7693 | 1.7645 (a=1.130) | +0.0048 (+0.0034 to +0.0061) |
| lb | 1.220 | 16,866 | 1.7700 | 1.7649 (a=1.131) | +0.0052 (+0.0038 to +0.0064) |
| tote_v | 1.184 | 16,847 | 1.7680 | 1.7654 (a=1.087) | +0.0027 (+0.0017 to +0.0036) |
| tote_n | 1.184 | 16,848 | 1.7673 | 1.7638 (a=1.093) | +0.0034 (+0.0025 to +0.0044) |
| sp | 1.238 | 18,076 | 1.7591 | 1.7541 (a=1.137) | +0.0049 (+0.0037 to +0.0063) |
| bsp | 1.005 | 16,547 | 1.7599 | 1.7599 (a=1.002) | +0.0000 (-0.0000 to +0.0000) |

### Sources on identical races (Sportsbet, Ladbrokes, tote, Betfair BSP all present)

| Source | Races | Log loss (proportional) | Gain vs Sportsbet (95%) |
|---|---|---|---|
| sb | 16,329 | 1.7715 | baseline |
| lb | 16,329 | 1.7722 | -0.0006 (-0.0015 to +0.0002) |
| tote_v | 16,329 | 1.7696 | +0.0019 (-0.0006 to +0.0043) |
| bsp | 16,329 | 1.7608 | +0.0107 (+0.0088 to +0.0127) |

### Model layers on Sportsbet prices (hold-out; positive gain = better)

| Comparison | Races | Base LL | New LL | Gain (95%) | Clears 95% |
|---|---|---|---|---|---|
| power vs proportional | 16,866 | 1.7693 | 1.7645 | +0.0048 (+0.0034 to +0.0061) | yes |
| features vs proportional | 16,866 | 1.7693 | 1.7635 | +0.0058 (+0.0044 to +0.0072) | yes |
| features vs power | 16,866 | 1.7645 | 1.7635 | +0.0010 (+0.0003 to +0.0017) | yes |
| FORWARD 2026-27: power vs proportional | 3,962 | 1.7675 | 1.7621 | +0.0054 (+0.0025 to +0.0085) | yes |
| FORWARD 2026-27: features vs proportional | 3,962 | 1.7675 | 1.7613 | +0.0062 (+0.0027 to +0.0099) | yes |

Feature coefficients (standardised): barrier_frac +0.012, wt_diff -0.042, rating_diff +0.038, age_c +0.027, gelding -0.198, mare -0.211, jockey_resid -0.006, trainer_resid +0.003, horse_resid -0.004

### Calibration, Sportsbet power-corrected, hold-out

| Band | n | Said | Got | 95% range of got | Outside |
|---|---|---|---|---|---|
| 0.00-0.02 | 34,925 | 0.010 | 0.009 | 0.008-0.010 | **yes** |
| 0.02-0.04 | 24,301 | 0.030 | 0.030 | 0.028-0.033 | no |
| 0.04-0.07 | 26,587 | 0.054 | 0.056 | 0.053-0.058 | no |
| 0.07-0.10 | 18,203 | 0.085 | 0.085 | 0.081-0.089 | no |
| 0.10-0.15 | 18,884 | 0.123 | 0.124 | 0.120-0.129 | no |
| 0.15-0.20 | 12,873 | 0.174 | 0.175 | 0.169-0.182 | no |
| 0.20-0.30 | 14,570 | 0.243 | 0.243 | 0.236-0.250 | no |
| 0.30-0.40 | 6,446 | 0.343 | 0.345 | 0.334-0.357 | no |
| 0.40-1.00 | 4,972 | 0.510 | 0.499 | 0.486-0.513 | no |

### Calibration by market type: cells outside their 95% range (n >= 300)

196 cells tested, 10 outside the range; chance alone gives about 9.8.

| Type | Group | Band | n | Said | Got | 95% range |
|---|---|---|---|---|---|---|
| state | SA | 0.30-0.40 | 417 | 0.342 | 0.288 | 0.246-0.333 |
| field | 8-10 | 0.00-0.02 | 13,314 | 0.011 | 0.008 | 0.007-0.010 |
| distance | 1200-1400 | 0.00-0.02 | 16,129 | 0.010 | 0.008 | 0.007-0.010 |
| distance | 1900-2400 | 0.40-1.00 | 338 | 0.503 | 0.447 | 0.395-0.500 |
| race type | handicap/class | 0.04-0.07 | 13,517 | 0.054 | 0.058 | 0.054-0.062 |
| race type | handicap/class | 0.40-1.00 | 1,928 | 0.500 | 0.476 | 0.453-0.498 |
| race type | maiden | 0.00-0.02 | 13,173 | 0.009 | 0.007 | 0.005-0.008 |
| going | Good | 0.00-0.02 | 20,492 | 0.010 | 0.008 | 0.007-0.010 |
| going | Heavy | 0.04-0.07 | 2,575 | 0.054 | 0.069 | 0.060-0.080 |
| going | Heavy | 0.40-1.00 | 435 | 0.514 | 0.460 | 0.413-0.507 |

### Place market (fields of 8+, top 3), implied chance normalised to 3 places

| Book | Band | n | Said | Got | 95% range |
|---|---|---|---|---|---|
| sb_place (overround 1.24) | (0.0, 0.1] | 22,587 | 0.062 | 0.042 | 0.040-0.045 |
| sb_place (overround 1.24) | (0.1, 0.2] | 28,063 | 0.150 | 0.129 | 0.125-0.133 |
| sb_place (overround 1.24) | (0.2, 0.3] | 29,179 | 0.247 | 0.232 | 0.227-0.236 |
| sb_place (overround 1.24) | (0.3, 0.4] | 23,336 | 0.347 | 0.346 | 0.340-0.352 |
| sb_place (overround 1.24) | (0.4, 0.5] | 17,392 | 0.448 | 0.466 | 0.458-0.473 |
| sb_place (overround 1.24) | (0.5, 0.65] | 15,436 | 0.565 | 0.618 | 0.610-0.625 |
| sb_place (overround 1.24) | (0.65, 1.0] | 4,439 | 0.705 | 0.803 | 0.791-0.814 |
| tote_v_place (overround 1.19) | (0.0, 0.1] | 24,736 | 0.063 | 0.047 | 0.044-0.050 |
| tote_v_place (overround 1.19) | (0.1, 0.2] | 30,517 | 0.149 | 0.140 | 0.136-0.144 |
| tote_v_place (overround 1.19) | (0.2, 0.3] | 26,365 | 0.249 | 0.248 | 0.243-0.253 |
| tote_v_place (overround 1.19) | (0.3, 0.4] | 21,519 | 0.348 | 0.358 | 0.352-0.365 |
| tote_v_place (overround 1.19) | (0.4, 0.5] | 16,662 | 0.451 | 0.470 | 0.462-0.477 |
| tote_v_place (overround 1.19) | (0.5, 0.65] | 13,687 | 0.574 | 0.601 | 0.592-0.609 |
| tote_v_place (overround 1.19) | (0.65, 1.0] | 6,419 | 0.757 | 0.733 | 0.722-0.743 |
| lb_place (overround 1.22) | (0.0, 0.1] | 20,005 | 0.066 | 0.038 | 0.035-0.041 |
| lb_place (overround 1.22) | (0.1, 0.2] | 31,655 | 0.150 | 0.126 | 0.122-0.130 |
| lb_place (overround 1.22) | (0.2, 0.3] | 29,605 | 0.249 | 0.237 | 0.232-0.242 |
| lb_place (overround 1.22) | (0.3, 0.4] | 23,048 | 0.347 | 0.352 | 0.346-0.358 |
| lb_place (overround 1.22) | (0.4, 0.5] | 16,549 | 0.447 | 0.469 | 0.462-0.477 |
| lb_place (overround 1.22) | (0.5, 0.65] | 14,805 | 0.564 | 0.615 | 0.608-0.623 |
| lb_place (overround 1.22) | (0.65, 1.0] | 4,765 | 0.707 | 0.804 | 0.793-0.815 |

### ROI at ONE book (Sportsbet price), flat $1, hold-out

| Rule | Bets | ROI | 95% | 99% |
|---|---|---|---|---|
| back every runner | 161,869 | -28.0% | -29.4 to -26.7 | -29.7 to -26.1 |
| band 0.00-0.02 (fair chance) | 27,607 | -55.5% | -62.1 to -49.1 | -64.0 to -47.1 |
| band 0.02-0.04 (fair chance) | 24,448 | -35.9% | -41.1 to -31.1 | -42.4 to -29.2 |
| band 0.04-0.07 (fair chance) | 29,283 | -24.8% | -28.1 to -21.4 | -29.2 to -20.3 |
| band 0.07-0.10 (fair chance) | 19,627 | -24.0% | -27.5 to -20.1 | -28.6 to -19.0 |
| band 0.10-0.15 (fair chance) | 22,350 | -18.6% | -21.3 to -16.0 | -22.6 to -15.2 |
| band 0.15-0.20 (fair chance) | 13,755 | -16.1% | -18.7 to -13.5 | -19.7 to -12.7 |
| band 0.20-0.30 (fair chance) | 15,244 | -12.1% | -14.0 to -10.2 | -14.5 to -9.5 |
| band 0.30-0.40 (fair chance) | 5,752 | -11.1% | -13.8 to -8.4 | -14.8 to -7.3 |
| band 0.40-1.00 (fair chance) | 3,695 | -10.2% | -12.7 to -7.5 | -13.4 to -6.9 |
| value power edge1.0 | 420 | +1.4% | -11.5 to +16.5 | -15.3 to +21.0 |
| value power edge1.05 | 299 | -1.5% | -14.3 to +12.2 | -19.6 to +14.5 |
| value feature edge1.0 | 1,162 | +3.3% | -7.1 to +14.0 | -10.5 to +18.7 |
| value feature edge1.05 | 896 | +13.3% | +0.0 to +27.2 | -3.1 to +32.4 |
| value feature edge1.1 | 639 | +15.6% | +1.5 to +29.8 | -1.2 to +34.7 |

Forward 2026-27 (rules fixed beforehand):

| Rule | Bets | ROI | 95% | 99% |
|---|---|---|---|---|
| all runners | 38,074 | -28.0% | -30.9 to -25.2 | -31.9 to -24.1 |
| value feature edge1.0 | 485 | +12.0% | -7.0 to +30.8 | -12.7 to +34.7 |
| value power edge1.0 | 90 | +16.0% | -22.4 to +52.5 | -33.3 to +64.0 |
| value feature edge1.05 | 370 | +20.1% | -3.2 to +41.7 | -13.5 to +49.4 |
| value power edge1.05 | 66 | +37.1% | -11.1 to +84.9 | -28.7 to +99.1 |
| value feature edge1.1 | 247 | +16.4% | -10.7 to +40.7 | -17.2 to +47.6 |
| value power edge1.1 | 46 | +41.1% | -20.0 to +112.2 | -40.0 to +144.3 |

Backing every runner at each book (shows the margin each one charges): sb -28.0%, lb -27.8%, tote_v -24.6%, sp -28.4%

### Betfair file, longer history (train 2019-20 to 2024-25, hold-out 2025-26)

| Price | Overround | Races | Proportional | Power | Gain of power (95%) |
|---|---|---|---|---|---|
| bsp | 1.004 | 19,509 | 1.7823 | 1.7823 (a=1.005) | +0.00001 (-0.00003 to +0.00007) |
| preplay_wavg | 1.008 | 19,487 | 1.7890 | 1.7889 (a=1.019) | +0.00006 (-0.00014 to +0.00026) |

## Reading the tables

- **Calibration is good once corrected.** The power-corrected Sportsbet chance is within its 95%
  range in every band except the very longest (under 2%: said 1.03%, got 0.88%). Longshots still
  win slightly less often than even the corrected price says; the effect is small in absolute
  terms but it is the one persistent miss, strongest in maidens (0.95% said, 0.65% got).
- **By market type: 10 of 196 cells outside their 95% range; chance alone gives about 10.** No
  state, field-size, distance, race-type or going split clears the noise except the same
  longshot tail, and the thin favourite cells in heavy going and 1900 to 2400 m (about 440 and
  340 runners; both over-rated, not enough to act on). Nothing is adjusted for.
- **Place market** (3 places, normalised): Sportsbet and Ladbrokes are too cheap on short places
  and too generous on long ones (said 70% got 80% for the shortest band; said 6% got 4% for the
  longest), so place prices carry a larger favourite-longshot bias than win prices. The tote is
  much closer to fair. This is calibration only: the place margin (overround 1.19 to 1.24) is what
  the owner pays.
- **Which markets are more reliable:** exchange (BSP) most, then tote, then fixed-odds books after
  the power correction; win more than place (place prices have more bias and more margin).
- **ROI by band**: every price band loses at Sportsbet, from -55% (under 2%) to -10% (favourites
  above 40%). Longer prices lose more; never apply a band's average to its cheap end.

## Caveats

- Sportsbet's price is the one racing.com held when the race was settled (equal to the starting
  price). It is a typical single-book price, not necessarily one available earlier.
- The feature layer uses only information from earlier days (jockey, trainer, horse residuals
  against the market), but weight, rating and barrier come from the race-day field.
- Conditional-logit fitting uses the first winner in dead-heats.
- Consistent with `research/RESULTS.md` (alpha about 1.13, no demonstrated edge from form
  families). The app's `MARKET_ALPHA` stays at 1.14; `racing/tuning.json` can move it within
  1.0 to 1.3 once enough live races are logged.

## Paused work finished

- `melbcup/racing_store.py`: saves each meeting's RaceCheck picks to
  `racing/<date>/<venue>/checks.json` after every check and restores them when the meeting loads
  (needs `NBA_ACCOUNT`; otherwise nothing is stored); appends one line per graded race to
  `racing/log/<date>.jsonl`.
- `tools/racing/learn.py`: token-free; fits alpha from the log, shrinks it to the prior
  (3,000-race weight), clamps to 1.0 to 1.3, writes `racing/tuning.json`.
- `melbcup/model/probability.py`: `set_tuning` applies it; LiveBoard reads it at start.

## Published (container `nba`, `sports/racing/`)

`dataset.csv.gz`, `betfair.csv.gz`, `model.json`, `holdout_results.json`, `build_meta.json`.
Small samples are in `tools/sports/racing/sample/`.
