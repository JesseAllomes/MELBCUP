# AFL: market vs model (free data)

Reproduce: `python -m tools.sports.afl.fetch`, `.build`, `.test` (seeded bootstrap). Tests: `tests/test_afl_sport.py`.
Machine output: `research/sports/afl/holdout_results.json`, `model.json`.

## Source and limits
- One source: the aussportsbetting.com AFL results + odds workbook. The site returns a Cloudflare 403
  to scripts (not evaded), so `fetch.py` pulls a public GitHub mirror of the same file
  (dclaz/bscores `data/afl.xlsx`). Snapshot runs to 2026-08-02. Mirror provenance is unverified.
- **Terms: "personal use only; do not make this data available on another website."** So the raw
  workbook and any odds-bearing table stay local and are NOT published. Published dataset is
  results + pre-game Elo + rest days only (odds columns dropped).
- afltables.com was reachable but not used: the workbook already carries results. No player
  props exist in any free AFL source found, so no prop-type analysis is possible.
- Rows: 3533 games, 2009-2026 (2026 partial, 180 games). Odds: all-book average h2h 2009+;
  single-book open/close (Pinnacle to 2018-04-02, bet365 after) for h2h 2013+, line 2013+,
  total 2014+. Lines mostly half-points; pushes dropped.

## Protocol
Tune on seasons <= 2024, sealed hold-out = 2025 (216 games, one look). 2026 partial = second
forward check, never tuned on. Baseline = proportional margin removal of the single book's
closing price. 95% ranges: seeded bootstrap over games of paired log-loss difference.

## What was tried (22 items, `tried` in the json)
Elo grid 9 (K 10/20/30 x home edge 20/30/40; picked K=10, HGA=40, K sits on the grid edge);
h2h power (favourite-longshot) / recal / elo / elo+rest (4); line power+recal, total power+recal
(4); ROI at edges 0/3/5% for 3 h2h models (9) and line/total at 0/3% (4) -- counts overlap.
Per-test Bonferroni alpha = 0.0023, so the 95% ranges below are generous to any "win".

## Hold-out results (log loss, lower is better; diff = candidate minus market)
| Market | n | Market LL | Best candidate diff (95% range) | Verdict |
|---|---|---|---|---|
| H2H close 2025 | 216 | 0.5306 | recal +0.0002 (-0.0036, +0.0041); elo +0.0005; elo+rest +0.0019; power k=1.00 = identical | nothing beats market |
| H2H close 2026 partial | 180 | 0.5219 | recal -0.0030 (-0.0072, +0.0012); elo -0.0028 | range spans 0, not kept |
| Line close 2025 | 216 | 0.6943 | power +0.0005; recal +0.0018 (-0.0001, +0.0038) | market best |
| Total close 2025 | 216 | 0.6932 | recal -0.0017 (-0.0054, +0.0022) | range spans 0 |
Average-of-books h2h LL 0.5322 vs single-book close 0.5306 vs open 0.5414: closing single
book is the sharper reference. Line and total are near coin-flip (0.693): the line absorbs all
the information, so a bet there is only margin.
Power k fitted at 1.00 for h2h (no favourite-longshot bias to fix); for line/total it ran to the
grid edge 1.40 on a flat surface and lost out of sample.

## Calibration (said vs got, 95% Wilson), raw single-book close, all seasons 2013-2026, nothing fitted
H2H home win prob: 0-.20 said .135 got .128 [.090,.179] n215; .20-.35 .285/.303 [.261,.349] n416;
.35-.50 .423/.460 [.416,.504] n496; .50-.65 .575/.600 [.561,.637] n626; .65-.80 .722/.705
[.669,.739] n655; .80-1 .877/.911 [.881,.934] n443. Every band's range covers "said" except the
top band, whose lower end (.881) only just clears .877 -- one of 6 bands, so luck-sized.
Sides: home fav .708/.720, home dog .317/.339, away fav .683/.661, away dog .292/.280; all ranges
contain "said". Line: home-cover said .500 got .504 [.485,.522] n2847. Total: over said .501 got
.484 [.465,.503] n2644; over-priced-under-50% band .485/.435 [.387,.484] n400 is the one
nominal miss, among 16+ bands tried, so not trusted.

## ROI at ONE book's price (hold-out 2025, flat 1 unit)
Blind home h2h -4.8% [-20%,+13%]; blind away -15.3% [-30%,+0.1%]; line blind first/second side
-3.5% / -5.3%; total over -11.6%, under +2.6% [-9.9%,+15.7%] (blind, not a signal).
Model-picked h2h bets (model p x close odds > 1): recal 72 bets -16.3% [-57%,+33%]; elo 66 bets
-13.0%; at +3% edge 16 bets +25% [-100%,+206%] (noise, hit rate 12.5%). Longshots dominate the
"edge" bets and hit less than priced. No best-price-across-books ROI is claimed.

## Verdict
Nothing beats the market. The de-margined single-book closing price is the model; recalibration,
Elo and rest add nothing outside their 95% ranges on the sealed 2025 season (2026 partial leans
positive for recal/elo but still spans zero). Reliability: h2h is the only informative market
(LL 0.53) and is well calibrated, with a possible slight underpricing of heavy favourites (>80%)
not yet proven; line and total are efficient (LL 0.693), their only cost is ~4.7% margin. Props:
no free data, untested. Caveats: mirror provenance, 216-game hold-out gives log-loss ranges of
about +-0.004, so small edges are undetectable; 2013+ single-book history only.
