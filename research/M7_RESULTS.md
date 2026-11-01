# m7 results: the race card's rules on the archive, and what changed (Sun 1 Nov 2026)

Replay: `research/m7/card_rules.py` -> `research/m7/card_rules.json`. The card's picks as fixed rules, one unit
a bet, Sportsbet's price at T-2 (place: the stored last place price), SB+LB consensus (the app uses four
books). Blocks: dev 2023-25 (19,986 races), tune2 (2,438), final (5,026), fwd = Sep 29-Oct 29 (1,271).
**The rules were never fitted on any block, so every block is a fair read; but the three later blocks are
spent for new claims, and the variant grid was run on dev only.** ROI %, 95% day-bootstrap in brackets.

## 1. The card's win pick ("closest to fair", 4% floor): alpha 1 v alpha 1.14

| Block | alpha 1 (was live) | alpha 1.14 (now live) | favourite, for scale |
|---|---|---|---|
| dev | -16.8 [-19.6, -13.8] | -13.2 [-15.0, -11.2] | -11.9 |
| tune2 | -20.6 [-28.6, -12.6] | -13.0 [-17.8, -8.1] | -12.1 |
| final | -21.9 [-28.6, -15.3] | -13.5 [-16.9, -10.1] | -15.1 |
| fwd | -20.6 [-32.7, -7.1] | -10.8 [-17.0, -5.1] | -13.6 |

Why: at alpha 1 the pick lands on $12-21 runners (median 7 to 9 runners in, strike 14-17%) whose true
chance is 25% below the market's (A/E 0.75 on dev); "closest to fair" was choosing the biased long shots.
At 1.14 the pick is $2-5 (strike 33-35%) and A/E is 0.97-1.00 in every price band holding picks. The gain
is 4 to 10 points on all four blocks, three of which alpha was never fitted on. Each way moves the same
way (-25.8/-26.9/-24.5/-31.9 -> -23.1/-17.9/-20.4/-24.1). Place is unchanged (the likeliest placer is the
favourite either way). Fields of 14+ (Cup-like): win -16.7/-23.8/-38.2/-20.3 -> -17.5/-23.4/-18.4/+2.1.
**Still a loss everywhere: this is losing less, not winning.** Nothing here beats the price.

## 2. Shipped (session branch, owner to approve for main)
- `melbcup/model/probability.py`: `MARKET_ALPHA = 1.14`; priced chances are consensus^1.14, renormalised
  (`corrected_market`). `Assessment.market_win` keeps the raw consensus.
- `melbcup/bets/offers.py`: scenario "consensus" is the raw market, "flb_1_14" is the app's chance (no
  double correction); saved cards and tests without a raw market still get corrected once.
- `tools/cup_signals.py`: ALPHA 1.14 to match. Tests updated (`tests/test_model.py`), pages rebuilt.
- `tools/forward_check.py` + `tests/test_forward_check.py`: the forward test (section 4).

**What changes on the live cards:** every chance moves toward the favourite (a 33% favourite reads about
37%; a $21 shot reads about 3.5% not 4.8%). Win and each-way picks shift to shorter runners (the $12-21
"closest to fair" picks mostly disappear); the likeliest placer is unchanged; fewer "Good price" pills on
long shots; chance-shared stakes lean a little more to favourites; exotic hit chances for top-4 boxes rise
slightly, so their needed dividends fall slightly; the offers check's worst-case logic is unchanged.

## 3. Rejected (fitted noise, or not a model knob)
- **Win chance floor** (dev: 2% -19.6, 4% -16.8, 8% -14.7, 15% -11.4 at alpha 1): higher floors just
  converge on the favourite; the cause was the long-shot bias, fixed by alpha. Not re-tuned.
- **Each-way price floor** ($4 -25.1, $5 -25.8, $8 -29.1, $10 -29.7, $15 -27.4, dev): noise-level
  differences; $5 stays.
- **Pick rule** "favourite" v "closest to fair" v "best edge": favourite is best on dev/tune2, closest to
  fair (alpha 1.14) is best on final/fwd. Inconsistent; nothing changes.
- **Chance-weighted stakes** (the app's way) v level: 1-3 points better at alpha 1, equal at 1.14. Kept.
- **The value BET rule**: 21 dev bets -61%, 1 + 0 + 0 on the spent blocks; at alpha 1.14 35 dev bets -29%,
  2 + 5 bets all lost. Fires about once per 1,000 races; unprovable; left as is.
- **T-30 v T-2 picks** (same races): win -18.7 -> -16.8 dev, -10.2 -> -20.6 tune2 (T-30 better!),
  -21.3 -> -21.9 final, -19.2 -> -20.6 fwd. No consistent gain from waiting for the win pick; each way
  looks much better late only because the archive's place price is always the jump price. The live
  forward test stays open.

## 4. For the owner to decide (product, not model)
- **Fixed-odds each way at 3 places is the worst of the three picks on every block** (-18 to -24% at
  alpha 1.14, against place -9 to -11% and win -11 to -13.5%). OFFERS.md says the same from the formula.
  Moving the each-way share to the place pick, unless a book pays 4 places at 1/4 odds (the Cup), would
  lose about 10 points less on that third of the money. Not applied: the three-picks-a-race layout is yours.
- **Forward test.** `python3 tools/forward_check.py --git . --branch origin/live --dates 2026-11-03 2026-11-03`
  (add `--meet 5195782` for Flemington only) after the last race; it writes `research/m7/forward/forward_check.json`
  (merged across runs) and prints T-30 v last-price picks with returns, Melbourne time. First real sample
  (31 Oct, 121 races, after the alpha change, before any look): early win +6%, place -9%, each way -38%;
  late win +10%, place -3%, each way -42%; 80 of 121 races changed a pick. One day: luck, not evidence.
  Hundreds of races are needed; run it weekly while the collector runs.
- **Betfair** was not in the replay (not observed at T); VENUES.md puts it 7-10 points better than Sportsbet on
  the same bets, so the live "better of the two" is already the right call.
