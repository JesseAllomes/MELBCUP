# VENUES: is Sportsbet the wrong platform? (venue comparison, not a selection test)

**Plain answer (real archive data only; every number below is from the dumps, the tote dividends and Betfair's own files).**
1. **Betfair SP returns the most on the same bets; Sportsbet the least.** On the one set that is not chosen by Sportsbet's price (back every T-2 favourite: 28,721 bets, Betfair priced 95% of them), ROI is Sportsbet -12.6%, Ladbrokes -11.3%, better of the two -10.9%, tote -10.9%, **Betfair SP -2.9% after 5% commission (-4.9% after 8%)**. Over every runner the take is Sportsbet -29.8%, tote -24.6%, Betfair -6.4%.
2. **The gap is proven on the favourite set** (Betfair minus Sportsbet +9.6 points, interval +9.3 to +9.9; tote +1.6, Ladbrokes +1.3). On the three rules (44, 66 and 92 bets) Sportsbet looks better than Betfair by 7 to 10 points, **but that is not proven (most intervals span zero) and is partly built in: those bets are picked because Sportsbet's price is above the consensus**, which flatters Sportsbet by construction.
3. **No venue makes any rule profitable, provably.** The frozen m8 win rule is positive (+15% Sportsbet, +3% Betfair after 5%, interval about -20% to +48% and -29% to +39%); 81 of its 92 bets are in development data the model was fitted on. The current rule and the price^1.14 rule lose everywhere. The favourite loses at every venue (best: Betfair -2.9%, interval -4.6% to -1.2%).
4. Place is the same picture: Betfair place SP +8.6 points over Sportsbet's fixed place on the favourite set (-1.8% v -10.3%), tote +2.7, better of SB/LB +1.2; no place bet set is profitable anywhere.
5. In cost terms Sportsbet is the dearest of the five, so it is "the wrong platform" for price; but moving to the exchange only shrinks losses. Betfair SP is not a price you can lock at T-2, thin races may not fill real stakes, and the owner's recorded decision is no Betfair account.

## Method
- Bets are the frozen ones, no re-tuning: all blocks pooled (dev 2023-01-01 to 2025-12-31, tune2, final, examined 2026-09-29 to 2026-10-29), 28,721 T-2 eligible races (every runner priced by both books). Selection always uses the Sportsbet T-2 price; the same runners are then settled five ways. Rule 1: top 4 by consensus, chance x price - 1 >= 5%. Rule 2: same with chance = price^1.1419 (frozen alpha). Rule 3: frozen m8 win rule (chance from the frozen T-2 model, edge >= 2%, chance >= 10%). Baseline: the T-2 favourite (highest consensus) in every race. Bets per block: rule 1 36/4/4/0, rule 2 56/4/6/0, rule 3 81/3/8/0, favourites 19,986/2,438/5,026/1,271.
- Settlement, 1 unit: Sportsbet and Ladbrokes at the last price at or before T-2 (win) or the stored last place price; better of the two = the larger; tote = final win and place dividend of the Tabcorp V pool (the per-state N and Q pools are only 85% covered; the composite BTOTE pays 12% above SP and is not a single pool, so is left out); Betfair = SP, profit (SP - 1) x (1 - commission) when it wins, commission on net winnings only, no premium charge.
- Place: the same selections backed to place. Sportsbet, Ladbrokes and tote pay on racing.com's places paid; Betfair settles on its own place market result.
- Betfair match: the 28,721 races were matched to Betfair's files by meeting date, race number, distance within 150 m and identical tab numbers (venue names differ: sponsor prefixes), ties broken by price correlation (>= 0.9, clear winner). 26,948 unique, 459 tie-broken, 1,235 no Betfair race (almost all in the examined month: Betfair's files end 2026-09-30), 79 unmatched or ambiguous. Betfair coverage of runners: 99.7% dev, 100% tune2, 99.5% final, 3.9% examined.
- Intervals: 95% bootstrap resampling race days. "Paired difference" = ROI of the venue minus Sportsbet's on the same bets, in points, over bets both priced. Coverage = share of the rule's bets with a price at that venue (100% for SB, LB and better-of; tote 99.9% win, 99.6% place).

## Win: ROI % per unit [95% interval] by venue and bet set
| Venue | Rule 1 current (44 bets) | Rule 2 price^1.14 (66) | Rule 3 frozen m8 (92) | Favourite (28,721) |
|---|---|---|---|---|
| Sportsbet T-2 | -59 [-94, -29] | -18 [-53, +19] | +15 [-20, +48] | -13 [-14, -11] |
| Ladbrokes T-2 | -62 [-96, -32] | -30 [-61, +1] | -1 [-29, +26] | -11 [-13, -10] |
| Better of SB/LB | -59 [-94, -29] | -18 [-53, +19] | +15 [-19, +48] | -11 [-12, -9] |
| Tote final (V) | -74 [-96, -56] | -35 [-63, +1] | -8 [-37, +22] | -11 [-12, -9] |
| Betfair SP -5% | -68 [-95, -46] | -28 [-61, +12] | +3 [-29, +39] | -3 [-5, -1] |
| Betfair SP -8% | -69 [-95, -47] | -29 [-62, +10] | +1 [-31, +36] | -5 [-7, -3] |
Paired difference vs Sportsbet, ROI points [95%] (Betfair coverage of bets 100% / 98.5% / 98.9% / 95.4%):
| Venue | Rule 1 | Rule 2 | Rule 3 | Favourite |
|---|---|---|---|---|
| Ladbrokes | -3.2 [-7.8, 0.0] | -11.9 [-22.9, -4.1] | -15.7 [-26.0, -7.2] | +1.3 [+1.2, +1.4] |
| Better of SB/LB | 0.0 [0.0, 0.0] | +0.2 [0.0, +0.5] | +0.5 [+0.1, +1.0] | +1.7 [+1.6, +1.7] |
| Tote | -15.0 [-27.8, -2.0] | -16.7 [-27.3, -5.9] | -22.7 [-32.1, -12.5] | +1.6 [+1.3, +1.9] |
| Betfair -5% | -9.0 [-19.0, +0.5] | -7.2 [-18.5, +5.9] | -10.2 [-20.3, +1.1] | +9.6 [+9.3, +9.9] |
| Betfair -8% | -9.7 [-20.1, +0.2] | -8.9 [-20.2, +3.8] | -12.6 [-22.6, -1.7] | +7.6 [+7.3, +7.9] |
The rule 1 to 3 rows where the other venue is worse than Sportsbet are the selection effect: a bet is chosen because Sportsbet's price is the generous one.

## Place: ROI % [95%] and paired difference vs Sportsbet (points)
| Venue | Rule 1 | Rule 2 | Rule 3 | Favourite | Favourite: diff vs SB |
|---|---|---|---|---|---|
| Sportsbet fixed place | -43 [-68, -17] | -32 [-50, -12] | -14 [-31, +4] | -10 [-11, -10] | - |
| Ladbrokes fixed place | -40 [-66, -13] | -30 [-49, -10] | -11 [-29, +7] | -11 [-12, -10] | -0.5 [-0.6, -0.3] |
| Better of SB/LB | -40 [-66, -12] | -29 [-48, -8] | -10 [-27, +8] | -9 [-10, -8] | +1.2 [+1.1, +1.3] |
| Tote place (V) | -43 [-69, -15] | -33 [-51, -12] | -12 [-30, +7] | -8 [-9, -7] | +2.7 [+2.5, +3.0] |
| Betfair place SP -5% | -36 [-61, -12] | -22 [-42, -2] | -5 [-23, +14] | -2 [-3, -1] | +8.6 [+8.4, +8.8] |
| Betfair place SP -8% | -37 [-61, -14] | -23 [-42, -3] | -6 [-24, +12] | -3 [-4, -2] | +7.6 [+7.4, +7.8] |
Betfair beats Sportsbet on place by 6 to 11 points on every set (intervals above zero for rules 2 and 3 and the favourite set).

## Effective take: one unit on every runner, runners priced at all venues (win 275,256; place 274,885)
| Venue | Win ROI [95%] | Place ROI [95%] | Coverage of all runners |
|---|---|---|---|
| Sportsbet T-2 | -29.8 [-30.8, -28.8] | -26.1 [-26.5, -25.7] | 100% |
| Ladbrokes T-2 | -28.3 [-29.4, -27.3] | -24.7 [-25.1, -24.3] | 100% |
| Better of SB/LB | -27.4 [-28.5, -26.3] | -23.2 [-23.6, -22.9] | 100% |
| Tote final (V) | -24.6 [-25.7, -23.5] | -20.9 [-21.4, -20.5] | 99.9% |
| Betfair SP -5% | -6.4 [-8.5, -4.1] | -5.3 [-6.0, -4.6] | 95.6% |
| Betfair SP -8% | -9.0 [-11.0, -6.9] | -7.3 [-8.0, -6.6] | 95.6% |
Betting every runner is dominated by long-shots, where bookmaker margins are widest; the exchange's edge is largest there.

## Limits
- Not a selection test: all blocks pooled, the rules were frozen on other data, and rule 3's model was fitted on the development block that holds 81 of its 92 bets.
- Bets overlap heavily across rules; rule 1 to 3 samples are small, so their intervals are wide. The favourite set is the clean venue comparison.
- Betfair SP and the tote dividend are known only after the off. The tote is always bettable but its price is unknown at bet time; Betfair SP can be ordered before the off, but a $1 test unit says nothing about liquidity or partial fills in small races. Commission uses flat 5% and 8%; premium charges and account restrictions are ignored. The examined month has almost no Betfair data, so it adds only Sportsbet and Ladbrokes information.
- Reproduce: `research/late_money/venues.py` with `bf_load.py` and `bf_match.py`; output `venues.json` in the session scratchpad `lm/out/`. No app code changed, nothing committed.
