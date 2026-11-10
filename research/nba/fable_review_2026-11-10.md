# NBA multi picker review — 2026-11-10

Question: which multis have the highest chance of actually winning at a given payout, and where does
the current picker lose. Not a search for weak odds.

Data: `forward-v2.jsonl` — 27,019 settled legs (deduped by game, label, agency; latest log), 37 games,
5 days (4–8 Nov 2026), 436 settled multis built from 1,066 distinct bets. No paid calls, no app code
changed. Scripts: `tools/nba/review/` (`sh tools/nba/review/run_all.sh forward-v2.jsonl outdir`).
Builds on the 7 Nov audit; nothing it settled is redone.

How to read the numbers: "said" = the app's chance, "got" = what happened, gap = got − said.
Leg intervals are 95% game-cluster bootstraps (37 clusters). Multi p-values come from a simulation
that draws each distinct bet once and shares it across every multi holding it, because the multis
overlap heavily (one bet sits in up to 15 multis). `*` = survives a 10% false-discovery control across
all cells tested in that table (91 pool cells, 65 picked cells).

## Verdicts in one screen

| # | Finding | Evidence | Verdict |
|---|---|---|---|
| 1 | Unders are not the leak. Picked unders hit what the app said. | 445 picked instances: said 58.5%, got 58.4%; sole killer of a lost multi 55 times, 55.6 expected | Settled for this sample |
| 2 | Unders fail often because they are ~58% legs; they are still the best leg per $ of payout. | Under ROI −1.9% [−6.8, +3.1] vs over rung −19.5% (pool), −7.5% at $1.15–1.30 | Keep unders |
| 3 | The real leak: overs on low-line players (median points line under 12). | Over rungs ≥50%: said 70%, got 62–65% on all 5 days; points −9.7 pts [−14.4, −5.5] * | Strongest signal in the log |
| 4 | Same players' unders are understated. | Points under: +9.0 pts [+4.5, +14.2] *, ROI +12.8% [+4.4, +22.8] | Same effect, other side |
| 5 | Mixed over/under stacks "said 31% got 14%" is a handful of bets. | 27 one-under stacks, 25 distinct unders, 9 won; fails multiple-test correction | Too thin, no change |
| 6 | No same-game correlation error. | Pair correlation −0.001 [−0.013, +0.012] over 39,788 pairs | Keep zero |
| 7 | Long rungs are overstated; the margin table is too low from $2.20 up. | $3–5: fitted 0.24 [0.14, 0.35] vs table 0.10 * | Fix table; no effect on auto-picks |
| 8 | Multis as a whole are calibrated. | 436: said 23.0%, got 25.5%, p = 0.30 | No global haircut needed |

## 1. What the picker offers, and what loses multis

Share of the pool vs share of picks (settled legs; picks = leg instances inside logged multis):

| Leg type | % of pool | % of picked instances | Picks per pool leg |
|---|---|---|---|
| Over, alt rung | 81.7 | 72.8 | 0.06 |
| Under, main line | 9.2 | 24.2 | 0.18 |
| Over, main line | 9.1 | 3.1 | 0.02 |
| Over rung $1.15–1.30 | 6.9 | 35.3 | 0.35 |
| Under $1.50–1.80 | 2.8 | 15.1 | 0.36 |
| Over rung $1.30–1.50 | 6.0 | 14.2 | 0.16 |
| Over rung $1.50–1.80 | 6.6 | 12.2 | 0.12 |
| Under threes | 2.0 | 9.1 | 0.31 |
| Under rebounds | 2.5 | 7.0 | 0.19 |
| Under assists | 1.7 | 5.5 | 0.22 |

Unders are picked three times as often as an average leg. Inside the stacks the owner bets
(`stacks` + `stacks_same`) they are 38% of legs. Rungs over $2.20 are never picked (floor 50%).
Agency split is even (pb 48.9%, sb 51.1%).

Failure attribution, stacks only (1,169 leg instances, 250 lost multis):

| Leg type | Instances | Said | Got | Failed | Expected failed | Excess | Sole killer | Expected [95%] |
|---|---|---|---|---|---|---|---|---|
| Over rung | 667 | 0.670 | 0.672 | 219 | 219.9 | −0.9 | 57 | 60.8 [47, 74] |
| Under main line | 445 | 0.585 | 0.584 | 185 | 184.7 | +0.3 | 55 | 55.6 [43, 69] |
| Over main line | 57 | 0.546 | 0.368 | 36 | 25.9 | +10.1 | 3 | 5.5 [1, 10] |
| Over, bench (<12) | 275 | 0.652 | 0.567 | 119 | 95.7 | **+23.3** | 31 | 26.3 [16, 37] |
| Over, starter (12–19) | 242 | 0.654 | 0.657 | 83 | 83.7 | −0.7 | 13 | 21.7 [12, 32] |
| Over, star (20+) | 207 | 0.679 | 0.744 | 53 | 66.4 | −13.4 | 16 | 18.3 [9, 28] |
| Under, bench | 191 | 0.593 | 0.571 | 82 | 77.8 | +4.2 | 27 | 23.3 [14, 34] |
| Under, star | 95 | 0.575 | 0.642 | 34 | 40.3 | −6.3 | 8 | 12.1 [5, 20] |
| Under in `stacks` (cross-game) | 266 | 0.558 | 0.508 | 131 | 117.6 | +13.4 | 38 | 36.6 [26, 47] |
| Under in `stacks_same` | 179 | 0.625 | 0.698 | 54 | 67.1 | −13.1 | 17 | 19.0 [11, 27] |

Reading: 42% of failed legs are unders (185 of 440), from 38% of legs. That is exactly their stated
failure rate, not a model error. Lost multis: 126 lost on overs only, 99 on unders only, 25 on both.
The one type that fails more than it should is overs on bench players (+23 failures on 275).
The cross-game vs same-game under split (+13 / −13) cancels and each half is inside its null range.

"Role" is a pre-game proxy, not minutes (the log has no minutes): the highest points line the market
makes ≥50% for that player in that game. 141 bench players, 266 player-games.

## 2. Calibration and return per $ by type

Why ROI is the right yardstick here: P(multi wins) = (1 / payout) × product of (1 + leg ROI). At a fixed
payout, the best multi is the one whose legs lose least per $.

| Leg type (all offered legs) | n | Said | Got | Gap [95%] | ROI [95%] | Chance of a $3 multi built only from it |
|---|---|---|---|---|---|---|
| Under main line $1.5–2.2 | 2,263 | — | — | +1.2 [−1.4, +3.9] (all unders) | −2.1% [−7.3, +3.2] | 0.321 [0.291, 0.353] (1.8 legs) |
| Under, bench players | 934 | 0.526 | 0.562 | +3.6 [+0.4, +7.0] | +2.9% [−3.3, +8.8] | 0.351 [0.314, 0.388] |
| Under, star/starter | 1,540 | — | — | — | −4.8% [−13.4, +3.5] | 0.306 [0.259, 0.354] |
| Over main line $1.5–2.2 | 2,156 | 0.481 | 0.467 | −1.4 [−4.1, +1.2] | −9.8% [−15.6, −4.6] | 0.278 [0.248, 0.307] |
| Over rung under $1.15 | 2,787 | 0.863 | 0.875 | +1.2 [−1.3, +3.3] | −5.7% [−8.4, −3.4] | 0.141 [0.093, 0.201] (14.5 legs) |
| Over rung $1.15–1.30 | 1,864 | 0.763 | 0.761 | −0.2 [−2.7, +2.2] | −7.5% [−10.6, −4.5] | 0.216 [0.178, 0.258] (5.6 legs) |
| Over rung $1.30–1.50 | 1,632 | 0.666 | 0.656 | −1.0 [−4.4, +2.8] | −9.1% [−14.2, −3.8] | 0.241 [0.199, 0.292] |
| Over rung $1.5–2.2 | 3,342 | — | — | −1.3 to −2.1 | −11.3% [−16.1, −6.0] | 0.266 [0.239, 0.296] |
| Over rung $1.15–1.5, star/starter | 2,362 | — | — | +2 to +3 (≥50% legs) | −4.6% [−8.5, −0.2] | 0.272 [0.227, 0.331] |
| Over rung $1.15–1.5, bench | 1,134 | — | — | −4.6 to −7.6 | −15.9% [−21.8, −10.1] | 0.161 [0.118, 0.213] |
| Over rung $3–5 | 3,272 | 0.239 | 0.211 | −2.8 [−4.9, −0.8] * | −21.3% [−29.4, −12.7] | not picked |
| Over rung $5+ | 6,830 | 0.107 | 0.080 | −2.7 [−3.9, −1.5] * | −35.5% [−46.1, −24.8] | not picked |
| Rung where this book beats the two-book mean by 2+ pts | 758 | 0.654 | 0.675 | +2.1 [−1.9, +5.6] | +2.7% [−5.2, +9.1] | 0.356 [0.291, 0.416] |

Signal (survives the false-discovery control, and repeats by day and agency):
- Over, points, bench: −6.6 pts [−9.3, −4.1], ROI −28.9% (n = 4,536) *.
- Over rung, bench: −4.3 pts [−6.6, −2.2] (n = 7,396) *. On legs ≥50%: −5.4, −5.2, −7.3, −8.2, −8.3 pts
  on the five days. Stars +2.7 [−0.9, +6.4] and starters +1.9 [−1.4, +5.1] on the same legs.
- Under, points, bench: +9.0 pts [+4.5, +14.2], ROI +12.8% [+4.4, +22.8] (n = 363) *; both agencies
  (pb +9.6, sb +8.8), positive on all 5 days. One main points line per player-game: the over won
  104 of 251 = 41.4% [35.5, 47.6] against a market 49.9%; starters 52.2%, stars 51.4%.
- Under, threes, bench: +7.9 pts [+1.4, +13.7] (n = 180) *.
- Legs the app calls 85%+: got 91.0% vs 88.3% said (+2.7 [+0.5, +4.7]) * — still −3.8% per $.

Noise (do not act): every stat-level split of unders (all intervals cross zero); star overs among picks
(+6.2 [+0.8, +11.1], p = 0.03, fails the correction); agency differences; picked vs unpicked legs of the
same type (no winner's curse: picked over rungs +1.3 [−1.9, +4.4], picked unders +2.3 [−4.7, +7.0]).

## 3. Structural weak points

| Area | Test | Result | Verdict |
|---|---|---|---|
| Multi calibration, all | 436 multis | said 0.230, got 0.255, null range [0.186, 0.296] | Calibrated |
| By kind | by_game 112 / stacks 188 / stacks_same 136 | 0.250→0.330 (p = 0.08) / 0.219→0.207 / 0.230→0.257 | No kind is off |
| By leg count | stacks 2 / 3 / 4 / 5 legs | 0.372→0.323 / 0.267→0.289 / 0.084→0.028 (n = 36, p = 0.16) / 0.053→0.111 | No trend; thin above 3 legs |
| By target | $2 / $3 / $5 / $10 / $20 (stacks) | 0.445→0.351 / 0.304→0.400 / 0.183→0.140 / 0.089→0.079 / 0.044→0.033 | Inside null ranges |
| Overs only vs mixed (stacks) | 83 / 40 | 0.221→0.301 (p = 0.13) / 0.304→0.125 (p = 0.011) | See below: not a structure fault |
| Exactly one under (stacks) | 31 (27 with 2+ settled legs) | 0.372→0.129, p = 0.004 single test | Fails correction for ~60 groups (needs p < 0.001) |
| Same-game correlation, main lines | 39,788 player pairs | r = −0.001 [−0.013, +0.012]; teammates +0.009 [−0.014, +0.035]; opponents −0.019 [−0.041, +0.005] | Zero is right |
| Same-game, short over rungs | 31,506 pairs | r = −0.002 [−0.012, +0.007] | Zero is right |
| Blowout proxy: teammate star with bench | 2,728 pairs | r = +0.052 [−0.017, +0.124] | No blowout effect seen; no scores/minutes in log |
| Picked same-game pairs, both won ÷ product | over+over 1,881 / over+under 207 / under+under 131 | 1.056 [0.947, 1.144] / 1.047 [0.807, 1.277] / 1.102 [0.614, 1.657] | Mixed pairs are not worse |
| Rung margin table | fitted vs table, by price | $1–1.15: 0.059 vs 0.067; $1.15–1.3: 0.078 vs 0.067; $1.3–2.2: 0.10–0.12 vs 0.076; $2.2–3: 0.172 [0.081, 0.272] vs 0.063; $3–5: 0.240 [0.136, 0.348] vs 0.10; $5–10: 0.345; $10+: 0.579 | Right under $1.30; too low above $2.20 |
| OVER_SHADE (0.013) | 2,473 native pairs | lean +0.023 [−0.003, +0.049]; bench +0.046 [+0.014, +0.080]; bench points +0.101 [+0.056, +0.153]; starters −0.006; stars +0.021 | Flat value fine; it should depend on role |
| Staleness (hours to tip) | legs ≥50% with a quote time, 12 games | <3h −0.7, 3–8h −2.1, 8–16h +0.1, 16h+ +1.9 pts; all cross zero | No age effect found; thin |
| Price move after logging (pre-tip quotes) | 12 games | lengthened >3%: ROI −19.3% [−26.3, −11.4] (n = 765); held −8.6%; shortened >3%: +4.8% [−2.8, +13.0] (n = 855) | Real pattern, 2 days only |
| Ladder smoothing + two-book mean | rungs ≥45% where market ≠ own price by 2+ pts | market higher (n = 758): market gap +2.1, own-price gap +5.8 [+1.4, +9.8]; market lower (n = 540): −3.8 vs −8.7 | The blended market beats the book's own price both ways |
| Early vs latest log of the same bet | 8,843 bets | Brier 0.1667 vs 0.1660, mean move 2.1 pts | Latest is marginally better |

Mixed stacks: the 27 one-under cross-game stacks hold 25 distinct unders (9 won, about 14 expected)
and 36 distinct overs (24 won). Dropping the most repeated losing bet leaves 4 wins of 24. Legs in
different games cannot be correlated by game script, and same-game mixed pairs test fine (1.047).
It is a cold run on about 25 unders, spread over days. Too thin to act on.

## 4. Picker changes, ranked by expected gain at the same payout

Replay: the current search (`melbcup.nba_legs`, imported read-only) re-run on each of the 10
day × agency pools with one thing changed, scored on real outcomes. Corrections are fitted
leave-one-day-out. Same-game: 37 games × 2 agencies × 4 targets. Cross-game: only 10 pools — every
cross-game row is noise (the current picker itself "got" 51% against 32% said there).

| Variant (same-game, $2–$10) | n | Said | Got [95%] | Got − current [95%, paired by pool] | $2 / $3 got |
|---|---|---|---|---|---|
| A current picker | 430 | 0.255 | 0.270 [0.230, 0.314] | — | 0.45 / 0.34 |
| H role-only correction | 429 | 0.262 | 0.333 [0.290, 0.379] | **+6.4 [+3.5, +9.5]** | 0.59 / 0.39 |
| G full type correction | 435 | 0.280 | 0.324 [0.282, 0.369] | +5.4 [+0.9, +10.9] | 0.59 / 0.41 |
| F drop bench overs | 412 | 0.259 | 0.303 [0.261, 0.349] | +3.4 [+0.8, +5.9] | 0.54 / 0.33 |
| B overs only | 414 | 0.256 | 0.266 [0.225, 0.310] | −0.4 [−5.2, +3.4] | 0.46 / 0.34 |
| I no leg under $1.20 | 430 | 0.255 | 0.258 [0.219, 0.302] | −1.2 [−2.8, +0.2] | 0.43 / 0.33 |
| K book's own price, no two-book mean | 424 | 0.239 | 0.233 [0.196, 0.276] | −3.6 [−10.8, +2.5] | 0.46 / 0.23 |
| D at most 3 legs | — | — | — | identical picks at $2 and $3 | 0.45 / 0.34 |

Cross-game, same variants: H −8.8 [−32.5, +12.5], G −13.8 [−35.0, +6.4], F −2.6 [−15.0, +13.5]
(n = 40 from 10 pools). The direction disagrees with same-game and the intervals are 40 points wide.

### Recommended, in order

1. **Role-aware lean (replaces the flat OVER_SHADE for low-line players).** For a player whose median
   points line is under 12: take about 5 points off his overs (about 8–10 on points) and add about 4
   to his unders (about 9 on points); leave starters and stars at 0.013. Expected: +3 to +6 points of
   win chance on a same-game multi at $2–$3 (replay +6.4 [+3.5, +9.5]; the lower-noise product estimate
   says +2.4). Verify: shadow-log pick A and pick H for every game and target from today, no stake
   change. Primary measure, fixed now: same-game $2 and $3 hit rate, H minus A, paired by game.
   Decide at 600 game-targets (about 3–4 weeks). Leg-level check sooner: bench over rungs ≥50% must
   stay below said by 3+ points over the next 2,000 such legs (about 10 days). Kill it if the gap
   closes — early-season rotations are the obvious alternative explanation.
2. **Re-price at placement.** If a picked leg's price has lengthened more than 3% since the pick, re-run
   the pick instead of placing it. Lengthened legs returned −19% per $ against −9% for held prices.
   Verify: log pick-time and placement-time price for every leg; compare hit − said for re-picked vs
   replaced legs after 1,000 legs. Evidence today is 2 days / 12 games.
3. **Raise the rung margin above $2.20**: 0.063 → about 0.15 at $2.20–3.00, 0.10 → about 0.22 at $3–5,
   0.32 at $5–10, 0.50 above. This changes shown chances and EV, not automatic picks (they stop at
   50%). Verify: gap by price band on the next 5,000 long rungs should sit within ±1 point.
4. **Prefer the leg where the book's price beats the two-book mean** (already implied by using the
   mean as the chance; make it visible and widen the mean with US books as the 7 Nov audit asked).
   +2.7% per $ [−5.2, +9.1] against −8.8% for ordinary rungs. Verify: same cell, next 2,000 legs.

### Do not change

- Do not ban or down-weight unders. They hit as stated and are the cheapest legs: two unders give a
  $3 multi about 32% [29, 35]; five to six $1.22 rungs give about 22% [18, 26].
- Do not ban mixed over/under stacks. 25 bets, fails the multiple-test correction.
- Do not add team/opponent correlation or a blowout term. Measured zero.
- Do not re-tune the flat OVER_SHADE on this log (0.023 [−0.003, +0.049] is consistent with 0.013).
- Do not drop the two-book mean or the ladder smoothing. Removing them cost 3.6 points in replay.
- Do not add a leg cap or a minimum leg price. The search already picks the fewest legs.
- No global haircut on multi chance. Multis are calibrated overall.

## Limits

- 5 days, 37 games, first weeks of a season. Every interval treats games as independent; days are not.
- Role is a line-based proxy. No minutes, starters or final scores in the log, so "minutes" and
  "blowout" are tested only indirectly.
- Did-not-play legs are void and excluded; they do not count against overs here.
- Quote times exist for 7–8 Nov only (12 settled games): staleness and price-move rows rest on that.
- The replay runs today's search on each day's final leg pool. It is not a re-run of history (0 of 39
  logged cross-game picks reproduced; the app ran several times a day, with a 3-leg minimum early on).
- Many cells were looked at. Only rows marked `*` or confirmed across all 5 days should be trusted.
- The bench finding was found and tested on the same 5 days (leave-one-day-out, but one sample). It is
  a hypothesis with good support, not an established edge. The shadow log is the test.

## Files

- `tools/nba/review/common.py` — loader, dedupe, role proxy, cluster bootstrap, false-discovery control
- `tools/nba/review/legs_types.py` — sections 1–2 (pool vs picked, gaps, ROI)
- `tools/nba/review/multis.py` — multi calibration, failure attribution
- `tools/nba/review/structure.py` — correlation, margin table, lean, staleness, smoothing
- `tools/nba/review/extras.py` — bench robustness, mixed stacks, ROI → multi chance
- `tools/nba/review/replay.py` — picker replay with variants (about 3 minutes)
- `tools/nba/review/run_all.sh` — runs all five

## Implemented 2026-11-10

**What is live (PICKER=v2, the default).** `melbcup/nba_legs.py`, used by NBA and NFL legs alike:
1. Role-aware lean: a player whose median points line (highest points rung the market makes >= 50%)
   is under 12 is "bench". His overs lose 9 points (points) or 5 (other stats); his unders gain 9
   (points) or 4 (other); this replaces the flat OVER_SHADE for him. Starters and stars keep 0.013.
2. Drift re-pick: in the challenge stage pick (`melbcup/web/views.py`, `nba_challenge.drifted`), if a
   leg's price has lengthened more than 3% since the pick was frozen, the fresh pick replaces it and
   the page shows "re-picked: <leg> drifted from $a to $b". The event is stored in the challenge
   state under `repicks`. The cross-sport "shown_sug" suggestion is not drift-checked.
3. Rung margin: `RUNG_MARGIN_V2` = 0.067 / 0.076 up to $2.20, then 0.15 (to $3), 0.22 ($3-5), 0.32
   ($5-10), 0.50 above. It changes shown chances and EV, not the automatic picks.
4. The two-book mean is kept in both versions.

**Revert in one line.** Set `PICKER=v1` (the picker exactly as before) and restart. The web app and
the job read it from `azure/webapp/melbcup-web.json` and `azure/jobs/melbcup-nba.json` (env `PICKER`,
value `v2`); on the Function app: `az functionapp config appsettings set --settings PICKER=v1`. The
switch is read at call time (`nba_legs.picker()`); unset means v2.

**Both versions are tracked.** Every slate the Function logs the live version's multis and the other
version's (`azure/function/nba_props.py`): multi rows carry `"picker": "v1"|"v2"` (untagged older rows
are v1); leg rows carry `chance_v1`, `chance_v2` and `bench`. The tag survives settlement into
`forward-v2.jsonl`, and the multi key includes it so the two versions are separate bets.

**Read the A/B.** `python tools/nba/ab_report.py forward-v2.jsonl [--repicks challenges.json]`:
per version said vs got, wins, return per $; v2 minus v1 paired by slate and target with a bootstrap
95% interval; leg-level gap for bench overs and unders under each version's chance; re-pick events and
how the replaced and fresh picks came out.

**Decision rule (unchanged from section 4).** Decide at about 600 same-game game-targets (3-4 weeks):
primary measure is the same-game $2 and $3 hit rate, v2 minus v1, paired by game. Keep v2 if the
interval is above zero; flip to `PICKER=v1` if it sits below zero or the bench-over leg gap (needs to
stay 3+ points below said over about 2,000 legs) closes. Early-season rotation changes are the
obvious alternative explanation.
