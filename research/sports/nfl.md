# NFL: free historical data, market-first model, honest test

## Sources
- nflverse/nfldata `games.csv` (GitHub, free): results plus closing moneyline, spread and total
  with prices, one consolidated source (not several books). Fetched by `tools/sports/nfl/fetch.py`.
- aussportsbetting.com `nfl.xlsx` was tried first: it is behind a Cloudflare challenge (HTTP 403),
  and we do not bypass that. Not used.
- Player props: no free historical prop lines exist, so no prop model. nflverse player stats are free
  but without lines there is nothing to price against. Markets covered: moneyline, spread, total.
- Reproduce: `python3 -m tools.sports.nfl.fetch && python3 -m tools.sports.nfl.build &&
  python3 -m tools.sports.nfl.test && python3 -m tools.sports.nfl.report <out>/holdout_results.json`.
  Raw files stay out of git; `data/sports/nfl/sample.csv` is a 25-row sample.

## Data
- 7,425 games, seasons 1999-2026 (2026 is in progress; 7,398 played).
- Prices exist for 2006-2026: 5,444 games with moneyline and spread prices, 5,441 with total prices.
- Margin removed proportionally. Pushes (spread/total) are blank outcomes and refunded in ROI;
  moneyline ties are dropped.

## Method
- Baseline = raw no-vig market probability. Variants are logistic regressions on logit(market):
  slope only (favourite-longshot style), slope+intercept, plus Elo difference (own Elo, pre-game,
  no look-ahead), rest difference, favourite flag, total line, week.
- Variants tried: 12 (ml 5, spread 4, total 3, each versus the market). A variant is "selected"
  only if its 95% bootstrap range on the dev walk-forward (2016-2024, fit on prior seasons)
  excludes zero. Seal: 2025 is the hold-out (fit on <= 2024, looked at once). 2026 (about 120
  games per market) is a partial-season forward check. Bonferroni-style ranges (12 comparisons)
  are in `holdout_results.json` (`ci_bonf12`).
- Calibration bands tried: 6 bands x 2 sides x 3 markets = 36 per period; expect about 2 outside
  the 95% range by luck.

## Results
### Dev walk-forward 2016-2024: log loss, variant vs raw no-vig market

| market | variant | n | log loss | diff vs market | 95% range | beats market? |
|---|---|---|---|---|---|---|
| ml | mkt | 2466 | 0.6088 | 0.0000 | 0.0000 to 0.0000 | no |
| ml | slope | 2466 | 0.6089 | 0.0001 | -0.0000 to 0.0002 | no |
| ml | platt | 2466 | 0.6088 | -0.0000 | -0.0009 to 0.0009 | no |
| ml | platt+elo | 2466 | 0.6090 | 0.0002 | -0.0010 to 0.0014 | no |
| ml | platt+rest | 2466 | 0.6090 | 0.0002 | -0.0010 to 0.0013 | no |
| ml | platt+elo+rest | 2466 | 0.6092 | 0.0004 | -0.0010 to 0.0018 | no |
| spread | mkt | 2411 | 0.6928 | 0.0000 | 0.0000 to 0.0000 | no |
| spread | platt | 2411 | 0.6931 | 0.0004 | -0.0013 to 0.0021 | no |
| spread | platt+elo_resid | 2411 | 0.6931 | 0.0004 | -0.0014 to 0.0023 | no |
| spread | platt+rest | 2411 | 0.6933 | 0.0005 | -0.0012 to 0.0023 | no |
| spread | platt+fav | 2411 | 0.6930 | 0.0002 | -0.0015 to 0.0021 | no |
| total | mkt | 2452 | 0.6929 | 0.0000 | 0.0000 to 0.0000 | no |
| total | platt | 2452 | 0.6936 | 0.0006 | -0.0006 to 0.0019 | no |
| total | platt+tline | 2452 | 0.6939 | 0.0010 | -0.0010 to 0.0029 | no |
| total | platt+week | 2452 | 0.6942 | 0.0013 | -0.0004 to 0.0029 | no |

### Sealed hold-out 2025: log loss, variant vs raw no-vig market

| market | variant | n | log loss | diff vs market | 95% range | beats market? |
|---|---|---|---|---|---|---|
| ml | mkt | 284 | 0.6070 | 0.0000 | 0.0000 to 0.0000 | no |
| ml | slope | 284 | 0.6070 | 0.0000 | -0.0006 to 0.0007 | no |
| ml | platt | 284 | 0.6069 | -0.0001 | -0.0027 to 0.0026 | no |
| ml | platt+elo | 284 | 0.6078 | 0.0008 | -0.0020 to 0.0038 | no |
| ml | platt+rest | 284 | 0.6072 | 0.0002 | -0.0029 to 0.0031 | no |
| ml | platt+elo+rest | 284 | 0.6082 | 0.0012 | -0.0021 to 0.0046 | no |
| spread | mkt | 284 | 0.6922 | 0.0000 | 0.0000 to 0.0000 | no |
| spread | platt | 284 | 0.6935 | 0.0013 | -0.0025 to 0.0051 | no |
| spread | platt+elo_resid | 284 | 0.6952 | 0.0031 | -0.0013 to 0.0075 | no |
| spread | platt+rest | 284 | 0.6933 | 0.0012 | -0.0026 to 0.0050 | no |
| spread | platt+fav | 284 | 0.6929 | 0.0008 | -0.0038 to 0.0056 | no |
| total | mkt | 285 | 0.6936 | 0.0000 | 0.0000 to 0.0000 | no |
| total | platt | 285 | 0.6936 | -0.0000 | -0.0023 to 0.0022 | no |
| total | platt+tline | 285 | 0.6945 | 0.0009 | -0.0032 to 0.0052 | no |
| total | platt+week | 285 | 0.6937 | 0.0001 | -0.0022 to 0.0023 | no |

### Forward check 2026 (partial season): log loss, variant vs raw no-vig market

| market | variant | n | log loss | diff vs market | 95% range | beats market? |
|---|---|---|---|---|---|---|
| ml | mkt | 121 | 0.6446 | 0.0000 | 0.0000 to 0.0000 | no |
| ml | slope | 121 | 0.6448 | 0.0003 | -0.0007 to 0.0014 | no |
| ml | platt | 121 | 0.6432 | -0.0014 | -0.0050 to 0.0022 | no |
| ml | platt+elo | 121 | 0.6424 | -0.0022 | -0.0061 to 0.0016 | no |
| ml | platt+rest | 121 | 0.6403 | -0.0043 | -0.0081 to -0.0003 | yes |
| ml | platt+elo+rest | 121 | 0.6392 | -0.0054 | -0.0094 to -0.0011 | yes |
| spread | mkt | 116 | 0.6936 | 0.0000 | 0.0000 to 0.0000 | no |
| spread | platt | 116 | 0.6911 | -0.0025 | -0.0078 to 0.0028 | no |
| spread | platt+elo_resid | 116 | 0.6921 | -0.0014 | -0.0078 to 0.0046 | no |
| spread | platt+rest | 116 | 0.6900 | -0.0035 | -0.0089 to 0.0016 | no |
| spread | platt+fav | 116 | 0.6917 | -0.0019 | -0.0092 to 0.0052 | no |
| total | mkt | 122 | 0.6942 | 0.0000 | 0.0000 to 0.0000 | no |
| total | platt | 122 | 0.6936 | -0.0007 | -0.0039 to 0.0029 | no |
| total | platt+tline | 122 | 0.6991 | 0.0049 | -0.0011 to 0.0110 | no |
| total | platt+week | 122 | 0.6935 | -0.0008 | -0.0040 to 0.0026 | no |

### Calibration (said vs got), Hold-out 2025; * = said outside 95% range of got

| market | side | price band (said prob) | n | said | got | 95% range |
|---|---|---|---|---|---|---|
| ml | home | 0.0-0.3 | 35 | 0.225 | 0.200 | 0.100 to 0.359 |
| ml | home | 0.3-0.4 | 36 | 0.346 | 0.417 | 0.271 to 0.578 |
| ml | home | 0.4-0.5 | 48 | 0.441 | 0.417 | 0.288 to 0.557 |
| ml | home | 0.5-0.6 | 47 | 0.554 | 0.574 | 0.433 to 0.705 |
| ml | home | 0.6-0.7 | 48 | 0.645 | 0.542 | 0.403 to 0.674 |
| ml | home | 0.7-1.0 | 70 | 0.796 | 0.814 | 0.708 to 0.888 |
| ml | away | 0.0-0.3 | 70 | 0.204 | 0.186 | 0.112 to 0.292 |
| ml | away | 0.3-0.4 | 48 | 0.355 | 0.458 | 0.326 to 0.597 |
| ml | away | 0.4-0.5 | 46 | 0.445 | 0.413 | 0.283 to 0.557 |
| ml | away | 0.5-0.6 | 49 | 0.558 | 0.592 | 0.452 to 0.718 |
| ml | away | 0.6-0.7 | 36 | 0.654 | 0.583 | 0.422 to 0.729 |
| ml | away | 0.7-1.0 | 35 | 0.775 | 0.800 | 0.641 to 0.900 |
| spread | home | 0.4-0.5 | 104 | 0.487 | 0.490 | 0.396 to 0.585 |
| spread | home | 0.5-0.6 | 180 | 0.509 | 0.517 | 0.444 to 0.589 |
| spread | away | 0.4-0.5 | 134 | 0.488 | 0.448 | 0.366 to 0.532 |
| spread | away | 0.5-0.6 | 150 | 0.509 | 0.533 | 0.454 to 0.611 |
| total | over | 0.4-0.5 | 120 | 0.490 | 0.508 | 0.420 to 0.596 |
| total | over | 0.5-0.6 | 165 | 0.507 | 0.527 | 0.451 to 0.602 |
| total | under | 0.4-0.5 | 118 | 0.490 | 0.492 | 0.403 to 0.581 |
| total | under | 0.5-0.6 | 167 | 0.507 | 0.473 | 0.399 to 0.549 |

### Calibration (said vs got), Pooled 2006-2025; * = said outside 95% range of got

| market | side | price band (said prob) | n | said | got | 95% range |
|---|---|---|---|---|---|---|
| ml | home | 0.0-0.3 | 494 | 0.234 | 0.239 | 0.203 to 0.278 |
| ml | home | 0.3-0.4 | 661 | 0.353 | 0.345 | 0.310 to 0.382 |
| ml | home | 0.4-0.5 | 716 | 0.446 | 0.437 | 0.401 to 0.474 |
| ml | home | 0.5-0.6 | 867 | 0.555 | 0.528 | 0.495 to 0.561 |
| ml | home | 0.6-0.7 | 1093 | 0.648 | 0.618* | 0.588 to 0.646 |
| ml | home | 0.7-1.0 | 1450 | 0.783 | 0.798 | 0.776 to 0.818 |
| ml | away | 0.0-0.3 | 1450 | 0.217 | 0.202 | 0.182 to 0.224 |
| ml | away | 0.3-0.4 | 1093 | 0.352 | 0.382* | 0.354 to 0.412 |
| ml | away | 0.4-0.5 | 840 | 0.444 | 0.469 | 0.436 to 0.503 |
| ml | away | 0.5-0.6 | 743 | 0.552 | 0.563 | 0.527 to 0.598 |
| ml | away | 0.6-0.7 | 661 | 0.647 | 0.655 | 0.618 to 0.690 |
| ml | away | 0.7-1.0 | 494 | 0.766 | 0.761 | 0.722 to 0.797 |
| spread | home | 0.4-0.5 | 2229 | 0.485 | 0.482 | 0.462 to 0.503 |
| spread | home | 0.5-0.6 | 2933 | 0.512 | 0.494 | 0.476 to 0.512 |
| spread | away | 0.4-0.5 | 2362 | 0.486 | 0.504 | 0.484 to 0.524 |
| spread | away | 0.5-0.6 | 2800 | 0.512 | 0.517 | 0.499 to 0.536 |
| total | over | 0.4-0.5 | 2054 | 0.490 | 0.490 | 0.468 to 0.511 |
| total | over | 0.5-0.6 | 3162 | 0.508 | 0.502 | 0.484 to 0.519 |
| total | under | 0.4-0.5 | 2381 | 0.490 | 0.509 | 0.489 to 0.529 |
| total | under | 0.5-0.6 | 2835 | 0.507 | 0.498 | 0.480 to 0.517 |

### ROI at the single listed price (flat 1 unit, pushes refunded)

| market | bet rule | bets | ROI | 95% range |
|---|---|---|---|---|
| ml | blind_all_sides_holdout | 568 | -0.050 | -0.137 to 0.044 |
| ml | blind_all_sides_pooled_2006_2025 | 10562 | -0.032 | -0.053 to -0.009 |
| ml | model_edge_gt_0_holdout | 21 | -0.251 | -0.693 to 0.248 |
| ml | model_edge_gt_3pct_holdout | 2 | - | - |
| spread | blind_all_sides_holdout | 568 | -0.045 | -0.124 to 0.033 |
| spread | blind_all_sides_pooled_2006_2025 | 10324 | -0.025 | -0.044 to -0.006 |
| spread | model_edge_gt_0_holdout | 67 | -0.144 | -0.380 to 0.092 |
| spread | model_edge_gt_3pct_holdout | 9 | -0.333 | -0.783 to 0.334 |
| total | blind_all_sides_holdout | 570 | -0.044 | -0.122 to 0.036 |
| total | blind_all_sides_pooled_2006_2025 | 10432 | -0.027 | -0.046 to -0.008 |
| total | model_edge_gt_0_holdout | 66 | 0.033 | -0.200 to 0.271 |
| total | model_edge_gt_3pct_holdout | 16 | -0.138 | -0.631 to 0.357 |


## Verdict
- Nothing beats the market. No variant has a log-loss range below zero on dev (2016-2024), so the
  published model is the raw no-vig market for all three markets. On the 2025 hold-out every
  variant is within noise of the market and the spread and total variants are slightly worse.
- 2026 forward: the rest-difference moneyline variants look better (range below zero on about 120
  games) but they failed in dev and 2025, were not selected, and sit among 12 variants tested.
  Treat as a lead to re-test at season end, not as an edge.
- Blind betting at the single listed price loses the margin (about -2.5% to -3.2% pooled, ranges
  excluding zero). Model-edge bets in 2025 are tiny samples (2 to 67 bets) with ranges spanning
  zero; none supports a +EV claim.
- Reliability by market type: spread and total prices are the best calibrated (all bands inside
  the 95% range in 2025, near 50/50 with little to add). Moneyline is the weakest: pooled 2006-2025
  home 0.6-0.7 favourites win less than priced (got 0.618 vs said 0.648) and the mirror away
  0.3-0.4 dogs win more (0.382 vs 0.352), both outside the 95% range. Blind ROI on that dog band was
  +7%, +3%, +25%, -6% across 2006-15, 2016-24, 2025, 2026 (standard error about 6% in the large
  blocks): consistent in sign but unproven, one band of 36, found post hoc. The slope variant
  (favourite-longshot correction) did not beat the market out of sample. Not adopted.
- Prices are one consolidated closing source, not Sportsbet. A real test at Sportsbet prices
  needs those prices collected going forward.

## Published
Azure Blob container `nba`: `sports/nfl/dataset.csv.gz`, `sports/nfl/model.json`,
`sports/nfl/holdout_results.json`.
