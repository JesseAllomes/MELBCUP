# NFL player props: stats model and same-game correlation

Owner goal (2026-11-08): the NBA treatment for NFL player props. Verdict first: **the model beats naive
synthetic-line baselines on every stat out of sample, but that is not evidence it beats the market**; no
free source has historical NFL prop prices. It therefore enters the app at a small blend weight
(model 0.25), and the same-game correlations are the main new value.

## Data (token-free, free)
- nflverse `stats_player` weekly CSV releases, seasons 2018-2025 plus 2026 through week 9
  (`python tools/nfl/history.py` -> `data/nfl/*.csv.gz`, about 1.1 MB each, not committed). Regular season,
  QB/RB/WR/TE/FB player-games with any pass attempt, carry or target.
- Splits: dev 2018-2023 (fit and calibrate), select 2024, sealed test 2025, forward 2026 (nine weeks).

## Method (`tools/nfl/props.py`)
- Mean: EWMA of the player's earlier games (decay chosen per stat from 0.80/0.88/0.94 on dev), shrunk to the
  role mean with 1 or 3 pseudo-games. Passing stats use games with 10+ attempts; others any offensive touch.
- Distribution: negative binomial, variance = mu*(s0 + b*mu) (yards are gamma-like: b>0), fitted by least
  squares on dev; logistic calibration p = sigmoid(ca*logit(tail)+cb) like NBA. Same tail function at runtime
  (`nba_legs.chance`, pure Python).
- Opponent-allowed and home/away factors were tested and **not adopted**: on 2024 they moved log loss by
  at most 0.002 (see the `select ll` line per stat) and the runtime has no schedule. Fitted values in
  `tools/nfl/model_props.json`; runtime constants in `melbcup/nfl_fit.py`.
- Evaluation: synthetic lines because historical prop prices are not available: Over = (median of the player's
  last 8 games)+0.5; TD and interception bets use the 1+ line. Only prop-eligible players (EWMA mean above a
  per-stat threshold, 4+ prior games). Baselines: `const` = training over-rate, `roll` = the player's own
  Laplace hit rate over the last 8 games.

## Results: log loss at synthetic lines (lower is better; dBase = model - const)
`n` = eligible player-games. Full output: `research/nfl/props_results.txt`.

```
stat                 split         n   model   const    roll   dBase  mean_p  hit
passingYards         dev        2814  0.6590  0.6927  0.6943 -0.0337  0.486  0.486
passingYards         select      536  0.6671  0.6924  0.6932 -0.0253  0.505  0.479
passingYards         TEST        516  0.6745  0.6922  0.6898 -0.0177  0.505  0.477
passingYards         fwd         239  0.6617  0.6951  0.6941 -0.0334  0.493  0.527
completions          dev        2807  0.6544  0.6913  0.6968 -0.0369  0.470  0.470
completions          select      534  0.6918  0.6945  0.7046 -0.0028  0.507  0.496
completions          TEST        516  0.6562  0.6917  0.7042 -0.0355  0.497  0.473
completions          fwd         237  0.6616  0.6953  0.6899 -0.0336  0.500  0.502
passingTouchdowns    dev        2640  0.6214  0.6606  0.6542 -0.0392  0.373  0.373
passingTouchdowns    select      493  0.6514  0.6659  0.6778 -0.0145  0.380  0.383
passingTouchdowns    TEST        492  0.6262  0.6653  0.6567 -0.0390  0.366  0.382
passingTouchdowns    fwd         227  0.5992  0.6544  0.6398 -0.0553  0.360  0.361
interceptions        dev        2381  0.6928  0.6929  0.7277 -0.0001  0.512  0.512
interceptions        select      429  0.6938  0.6946  0.7275 -0.0008  0.511  0.476
interceptions        TEST        400  0.6934  0.6939  0.7254 -0.0005  0.511  0.490
interceptions        fwd         190  0.6907  0.6922  0.7111 -0.0014  0.510  0.526
rushingYards         dev        6837  0.6684  0.6892  0.6944 -0.0208  0.456  0.456
rushingYards         select     1327  0.6793  0.6894  0.6944 -0.0101  0.451  0.457
rushingYards         TEST       1286  0.6725  0.6914  0.6940 -0.0189  0.454  0.468
rushingYards         fwd         558  0.6547  0.6812  0.6916 -0.0265  0.449  0.410
receivingYards       dev       11578  0.6679  0.6880  0.6929 -0.0201  0.449  0.449
receivingYards       select     1919  0.6734  0.6929  0.6926 -0.0194  0.448  0.473
receivingYards       TEST       1960  0.6604  0.6835  0.6943 -0.0231  0.451  0.427
receivingYards       fwd         891  0.6578  0.6897  0.6920 -0.0319  0.458  0.458
receptions           dev       11006  0.6492  0.6733  0.6747 -0.0241  0.401  0.401
receptions           select     1915  0.6562  0.6812  0.6799 -0.0251  0.405  0.420
receptions           TEST       1907  0.6399  0.6623  0.6704 -0.0224  0.397  0.373
receptions           fwd         841  0.6594  0.6858  0.6842 -0.0263  0.411  0.432
scrimmageYards       dev       12846  0.6669  0.6878  0.6933 -0.0209  0.448  0.448
scrimmageYards       select     2239  0.6750  0.6919  0.6929 -0.0169  0.443  0.468
scrimmageYards       TEST       2169  0.6610  0.6833  0.6938 -0.0223  0.448  0.426
scrimmageYards       fwd         939  0.6614  0.6876  0.6928 -0.0262  0.455  0.447
rushingTouchdowns    dev        6713  0.5309  0.5631  0.5700 -0.0322  0.251  0.251
rushingTouchdowns    select     1186  0.5477  0.5933  0.5825 -0.0456  0.256  0.278
rushingTouchdowns    TEST       1204  0.5502  0.5714  0.5854 -0.0212  0.260  0.258
rushingTouchdowns    fwd         540  0.5526  0.5948  0.5788 -0.0422  0.254  0.280
receivingTouchdowns  dev       13822  0.5069  0.5218  0.5487 -0.0150  0.216  0.216
receivingTouchdowns  select     2389  0.5135  0.5320  0.5514 -0.0185  0.208  0.224
receivingTouchdowns  TEST       2467  0.5090  0.5224  0.5495 -0.0134  0.212  0.216
receivingTouchdowns  fwd        1087  0.4998  0.5185  0.5444 -0.0187  0.215  0.213
touchdowns           dev       14687  0.5777  0.5978  0.6173 -0.0201  0.285  0.285
touchdowns           select     2475  0.5923  0.6179  0.6269 -0.0256  0.285  0.307
touchdowns           TEST       2652  0.5877  0.6043  0.6228 -0.0166  0.284  0.292
touchdowns           fwd        1211  0.5867  0.6096  0.6238 -0.0229  0.281  0.298
```

Reading: dev, select and the sealed 2025 test agree in sign and size (dBase about -0.02 on yards and
receptions, -0.02 to -0.04 on QB counts and TDs). Interceptions are essentially unpredictable
(dBase -0.003): treat as market-only. 2026 so far is consistent (n small, hit rates noisy).

## Same-game correlation (`tools/nfl/correlation.py`)
Gaussian-copula normal-score method as NBA: z = Phi^-1 of the randomised NB CDF of each actual count, by
relation self/team/opp and stat pair, fitted on 2018-2023, checked on 2024-25 and 2026. A pair is kept only
if |r| >= 0.05, the out-of-sample sign agrees and |oos| >= half of |fit|. Of 55 pairs at |fit| >= 0.05, 54 have
the same out-of-sample sign; fit vs oos correlation 0.98. Strongest (fit / oos): QB pass yds with his
catchers' rec yds +0.32 / +0.32, QB completions with receptions +0.36 / +0.31, QB pass TDs with
catchers' TDs +0.23 / +0.25; within a player rush yds and rush TD +0.24 / +0.26, rec yds and rec TD
+0.27 / +0.23. Opponent pairs are small (opposing QBs' pass yds +0.08 / +0.13; QB TDs +0.14 / +0.07).
Table: `research/nfl/correlation.txt`; kept pairs in `melbcup/nfl_fit.CORR`. Unders flip the sign.
Same-player mechanical pairs (rec yds with rush+rec yds, +0.95) are included as fitted; the nesting rule in
`nba_legs._nested` covers same-stat ladders only.

## App wiring
- `melbcup/nfl_model.py`: pure Python, `chance`/`annotate`/`rho`, BLEND_W = 0.25 (model weight, logit space).
  Means: `data/nfl/means.json`, refreshed by `python tools/nfl/history.py && python tools/nfl/means.py`
  (weekly in season; 320 players as of 2026 week 9).
- `melbcup/nfl_legs.py`: legs carry model chance and team; `N.apply_market(..., w=BLEND_W)` blends it with
  the de-vigged market; players without a mean stay market-only. Same-game multis go through
  `N.joint_chance`, whose `_rho` now dispatches `sport == "nfl"` legs to `nfl_model.rho` (NBA path unchanged).
- Blend refit: `python tools/nfl/blend_fit.py` reads the catalogue raw snapshots (blob `nba`,
  `catalogue/raw/nfl/`), settles from ESPN, and accumulates settled pairs in `data/nfl/blend_pairs.jsonl`;
  it prints a suggested weight once 400 pairs exist and never edits BLEND_W itself.

## Limits (honest)
- No market prices in the evaluation: beating a median-line baseline says the means and spreads are sane,
  not that there is edge. For NBA the market beat the model (best weight 0); expect the same here, hence 0.25.
- Synthetic lines are not the book's lines; touchdown lines are 1+ only; passing-TD lines use the median rule.
- No injury, depth-chart, weather, game-script or opponent information at runtime; a player with a role change
  is slow to move (EWMA). Means are only as fresh as the last refresh run.
- Correlations are fitted on normal scores of the base model, so they describe residual co-movement only; opponent
  and team-total effects (pace, game script) are partly inside them. No joint-probability backtest against SGM
  prices exists.
- 2026 forward sample is nine weeks.
