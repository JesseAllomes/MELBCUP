# NHL: free-data market-vs-model test

Reproduce: `fetch.py` -> `build.py` -> `test.py` (-> `publish.py`) in `tools/sports/nhl/`; raw files stay out of git. Tests: `tests/test_sports_nhl.py`.
Blobs (container `nba`): `sports/nhl/dataset.csv.gz`, `sports/nhl/model.json`, `sports/nhl/holdout_results.json`.

## Sources and rows
- Odds and scores: sportsbookreviewsonline.com NHL archive (free, not barred by robots, 3 s pause, cached). aussportsbetting.com was tried first and sits behind a Cloudflare challenge, so it was not used and not bypassed. 19,155 games, 16 seasons: 2007-08 to 2022-23 (2012-13 lockout and 2020-21 short, 2022-23 is a part-season of 339 games, the archive stops in Nov 2022). Regular season and playoffs (17,918 / 1,220; 17 rows unmatched to the API). Closing and opening moneyline, closing and opening total with over/under prices. Puck line with both prices exists only from 2014-15 (10,434 games). One source's price, not a best-of-books maximum.
- Results: public NHL API (api-web.nhle.com weekly schedule pages, 4 workers, 0.6 s pause, cached). Matches 19,138 of 19,155 games on date, teams and score; gives how each game ended: regulation 14,701, OT 2,495, shootout 1,942.
- Player stats and props: no free historical NHL prop prices exist, so there is no prop dataset and no prop calibration. Nothing paid was used.

## What was tried (count)
4 models per market (market; market with a favourite-longshot slope and intercept; + Elo (or team scoring-rate projection for totals); + Elo and back-to-back rest) = 12; 3 Elo K values; 45 calibration bands; 60 ROI rules. Elo K and the variant were chosen on 2020-21 only (fit on 2007-08 to 2019-20; puck line from 2014-15). The validation pick was refit on <= 2020-21 and scored once on the sealed 2021-22 season (full, 1,401 games), then on the 2022-23 part-season as a second look. With 60 ROI rules and 45 bands, about 3 and 2 would clear a 95% range by luck; read any single hit against that.

## Log loss, 2021-22 sealed (lower is better; market = proportional margin removal)
| market | n | market | chosen model | market minus chosen (95% range) |
|---|---|---|---|---|
| moneyline | 1,401 | 0.6431 | market (validation picked it) | 0 |
| puck line | 1,399 | 0.6690 | market + Elo | -0.0003 (-0.0011, +0.0005) |
| total | 1,325 | 0.6911 | market (validation picked it) | 0 |

Every variant on the hold-out (market loss minus variant loss; positive = variant better; reported, never used to choose):
- moneyline: slope/intercept +0.0001 (-0.0004, +0.0005); + Elo +0.0001 (-0.0004, +0.0006); + Elo and rest +0.0007 (-0.0001, +0.0016)
- puck line: slope -0.0004 (-0.0008, +0.0001); + Elo -0.0003 (-0.0011, +0.0005); + Elo and rest +0.0001 (-0.0009, +0.0009)
- total: slope -0.0008 (-0.0014, -0.0002); + scoring projection -0.0008 (-0.0014, -0.0002); + projection and rest -0.0010 (-0.0016, -0.0003) (all significantly worse than the market)
Validation (2020-21) losses, market vs best variant: moneyline 0.6556 vs 0.6557; puck line 0.6555 vs 0.6555; total 0.6905 vs 0.6906. No add-on cleared its 95% range. The fitted favourite-longshot slope is 1.008 (ML), 1.031 (PL), 0.931 (total): essentially 1, so the proportional margin removal is fine. 2022-23 part-season: differences all within +-0.0015 and straddle 0.

## Calibration, said vs got (margin-removed home / home-covers / over chance), with 95% ranges
All 16 seasons (diagnostic, n = 19,154 ML; 10,434 PL; 17,597 totals): every band inside its range in all three markets, e.g. ML 0.596 said, 0.593 got (n 7,654); 0.413 said, 0.405 got (n 2,474); PL 0.311 / 0.313 (n 3,673); totals 0.469 / 0.467 (n 4,554). 2021-22 alone: ML 0.55-0.65 band 0.595 said, 0.66 got (0.61-0.71), outside its range; the home-win rate was 54.1% and underdogs under-hit; PL 0.45-0.55 band 0.501 said, 0.432 got. Both are single-season noise beside 45 bands tried and are absent in the full sample. Totals went over 53.7% in 2021-22 against 49.3% overall: the line was a touch low that year, which a rule fitted on older seasons cannot know.

## ROI at the single closing price (flat 1 unit, 95% range)
2021-22 moneyline: favourites +4.4% (+0.4, +8.6), underdogs -12.0% (-18.6, -5.8). This is the one result that clears zero, and it does not repeat: 2022-23 favourites -5.3% (-13.9, +3.4); across all seasons every moneyline band loses on the home side (0.55-0.65 band -3.6%, -5.3 to -1.7, n 7,654; 0.65+ band -2.6%, -5.2 to -0.1). Puck line 2021-22: favourites -6.3% (-10.4, -2.2), underdogs +2.0% (-4.7, +8.7); all-season bands -3% to -5%. Totals 2021-22: overs +2.1% (-3.2, +7.2), unders -10.9% (-15.9, -5.6); all-season both sides -2% to -5%. Average margin: ML 2.4%, PL 3.3%, totals 4.5% (the archive's one source). Model-edge bets (model above the price by 3 points): zero bets in every market, because the chosen models equal the market and the margin is never beaten. Never claim +EV from a single season's side ROI; in the full sample none is positive.

## Verdict
Nothing beats the market. Moneyline, puck line and totals are well calibrated across 16 seasons; Elo, rest and scoring-rate add-ons do not improve log loss beyond their 95% ranges (totals add-ons are worse). The only positive ROI (2021-22 favourites) is one season, not repeated, and one of 60 rules tried. Most reliable (closest said-vs-got, largest n, lowest margin): moneyline, then puck line; totals are well calibrated but carry the widest margin (4.5%) and the line moves with scoring trends year to year. Longer prices still hit less than shorter ones within a band: do not apply a band average to its cheap end. Not tested: player props (no free price history), regulation-only (60-minute) markets, and the 2023-24 and 2024-25 seasons (no free odds source reachable: the archive stopped, aussportsbetting is challenge-blocked). Next step if more data is wanted: another season of real prices at the book actually used (Sportsbet).
