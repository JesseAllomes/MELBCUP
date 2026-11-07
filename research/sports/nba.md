# NBA: free-data market-vs-model test

Reproduce: `fetch.py` -> `build.py` -> `test.py` in `tools/sports/nba/` (raw files stay out of git). Tests: `tests/test_sports_nba.py`.
Blobs (container `nba`): `sports/nba/dataset_games.csv.gz`, `dataset_props.csv.gz`, `model.json`, `holdout_results.json`.

## Sources and rows
- Games: sportsbookreviewsonline.com NBA archive (free, robots allows, 3 s pause, cached). 19,618 games, 2007-08 to 2022-23 (16 seasons; 2022-23 is a part-season of 659 games, the archive stops). Final score, open and close spread, open and close total, closing moneyline. One source's line, not several books.
- Props: 1,079 player-stat-games, 2024-25 (2025-02-20 to 04-13), 47 player-stats, consensus line and over/under prices of about 7 books (DunkAPI, bought earlier, cached; nothing new was bought for this run). Joined to ESPN box scores for prior-10-game minutes.
- No free source of historical player-prop prices exists, so the prop test is small and one season.

## What was tried (count)
4 game models (market; market with favourite-longshot slope; Elo only; market + Elo), 50 price/line bands, 3 prop models, 29 prop cuts. Choice among models made on 2020-21 only. 2021-22 (last full season) is the sealed hold-out; 2022-23 part-season is a second look.

## Games, moneyline (log loss, lower is better)
| | market | + FLB slope | Elo only | market + Elo |
|---|---|---|---|---|
| 2020-21 (choice) | 0.6200 | 0.6203 | 0.6523 | 0.6205 |
| 2021-22 sealed | 0.6074 | 0.6073 | 0.6406 | 0.6083 |
| 2022-23 part | 0.6394 | 0.6398 | 0.6506 | 0.6392 |
Model better than market, 2021-22, with 95% range: FLB +0.0001 (-0.0001, +0.0003); Elo -0.033 (-0.045, -0.021); market+Elo -0.0010 (-0.0020, +0.0001). Nothing beats the market; the validation pick was the market itself.

Calibration of the margin-removed home-win chance (said vs got), 2007-2020, 17,641 games: every one of 8 bands inside its 95% range (e.g. 0.65 said, 0.646 got, n 3205; 0.866 said, 0.869 got). Hold-out bands also all inside (n 47 to 249 each, wide ranges). No favourite-longshot bias worth a correction.

ROI at the archive's single closing moneyline: favourites -4.1% (-5.1, -3.1), underdogs -3.7% (-6.1, -1.4), 2007-2020. Hold-out: favourites -2.9% (-6.9, +0.8), underdogs -2.7% (-11.7, +6.1). Model-side bets lose (Elo edge 3%+: -9.4% on 950 bets, range -17.6 to -0.9). No band is reliably positive; the few positive hold-out cells (away +2.1%, 0.7-0.8 underdogs +8.1%) have ranges straddling zero and are what 50 bands produce by luck.

## Spreads and totals
Prices are not in the archive; ROI assumes -110 (assumed). Home covers 49.4% (48.6-50.1) over 17,348 games; over hits 49.6% (48.8-50.3); both lose about 5.5% at -110. Hold-out: 48.5% and 49.9%, inside range. Bands by total and by spread size: all ranges contain 50% except large favourites (spread 10+) 48.4% (46.6-50.2), which also includes 50%.

## Player props (2024-25, consensus price, 1,079 bets)
Market over chance averages 0.493, overs hit 47.5% (44.6-50.5). Date split (fit first 593 rows, score 486 from 2025-03-17): market log loss 0.6921; one shift +0.0006 (-0.0029, +0.0040); shift+slope -0.0011; per-stat shifts shrunk n/(n+800) +0.0008 (-0.0007, +0.0024). None clears the noise.
Per prop type, over hit vs market's 0.49: assists 54.0% (48.1-59.8), points 46.4% (40.6-52.3), rebounds 43.8% (38.1-49.7), threes 45.8% (39.8-52.0). Overs at consensus price lose: all -9.8% a bet; rebounds -16.5%, threes -14.4%, points -12.5%; assists over +3.6% but its range spans zero (and unders there -14.7%). No cut is outside its 95% range (29 cuts tried, so one or two outside would still be luck). Minutes: 28-33 and 33+ prior minutes behave like the whole; under 28 has 18 rows.
Said-vs-got shape: overs priced 0.60+ hit 50% (n 16); priced under 0.40 hit 27% (n 37): the longer the price, the less often it hits, so a band average must not be applied to its cheap end.

## Verdict
Nothing beats the market. Moneyline, spread and total prices are well calibrated and cost the usual 4-5% margin. Props: the market is the best predictor on 2024-25; any tilt (assists over, rebounds/threes under) is inside the noise on one season and needs another season of real prices before it can be used. More reliable (closest said-vs-got, large n): moneyline favourites and underdogs, totals; least reliable: props, small n and wide ranges, over side priced too short for rebounds/threes. Not done: the nightly `learn.py` and wiring of `nba/tuning.json` (settled forward log not available here); with these results its shifts would stay at zero until 300 settled bets.
