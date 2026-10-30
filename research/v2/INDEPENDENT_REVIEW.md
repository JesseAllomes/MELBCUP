# Independent review: what component is being missed?

**2026-10-30. Written without prior involvement; sections 1–3 were formed and tested before reading
RESULTS.md, FACTORS.md, FACTORS_V2_PROPOSAL.md or MISSING_COMPONENT.md. Every outcome statistic
below is on block = train (2023-01-01 to 2025-06-30), eligible table, scored races with one
winner and full price coverage at every market compared: 16,816 races, 176k starters. No outcome
was read from tune1, tune2, final, excluded or history-only rows (the excluded races table was used
only for a non-outcome field: the first race's track condition at each meeting). Scripts and raw
output: `scratchpad/upsets/independent/` (`t1_markets.py`, `t2_screen.py`, `t3_followup.py`,
`t4_misc.py`, `t5_exotics.py`).**

The owner's sharpened goal, used as the yardstick throughout: per race, either **confirm** that the
favourite is the most likely winner (and how sure), or **overturn** by naming a non-favourite that is
more likely to win. An idea is judged by how well it separates favourite-wins from favourite-loses
races, and how often a named alternative actually beats the favourite, *beyond what the prices
already say*.

## 0. Summary

1. **Nothing in the collected pre-decision data separates favourite-wins from favourite-loses
   beyond the T-30 price.** Across 75 candidate features (form, sectionals, stewards, pace, jockey,
   trainer, barrier, weight, class, timing, market microstructure, same-day), the best adds 0.35
   millinats to the favourite-event log-loss; the price alone is 609 millinats. The one thing that
   does separate them is the market move *after* T-30 (7.7 millinats; favourite strike rate 23.7%
   for strong drifters vs 40.0% for strong firmers). The same holds for naming the alternative
   (ranks 2–4: post-decision move 5.6 millinats; the best form feature 0.5).
2. **The missing component is late informed money**, which lives in markets the dataset does not
   hold (exchange, tote pools) and arrives after the chosen decision time. The project's own
   MISSING_COMPONENT.md reached the same conclusion independently; my numbers agree (+0.045 nats per
   race from T-30 to the close, 17–22% of races change favourite, the late favourite wins 26% vs the
   T-30 favourite's 20% when they differ).
3. **The owner's premise about outsiders is inverted at corporate prices.** Runners at $20–40 win
   84% as often as their margin-free T-30 price says, $40–100 75%, $100+ 55%; backing them at SP
   returns −35%, −43%, −63%. Favourites win 8–18% *more* often than their normalised price says, yet
   still lose 7–15% at the best of the two books because of the overround. "An outsider has a
   better chance than its price implies" is on average false; it can only be true conditionally,
   and no condition in the data finds it.
4. **What none of the project documents considered**: (a) a margin- and finishing-order-based
   latent ability rating fitted on all runs (the standard fundamental model, screened with a far
   more powerful instrument than win log-loss); (b) the bet type that actually expresses the thesis:
   laying the favourite on the exchange, evaluated against Betfair SP (free historical files exist;
   blocked from this environment); (c) minimum-bet-limit rules, which make a race-day fixed-odds
   decision near the off *legally executable at scale* and change the bettability conclusion;
   (d) that exotic-pool returns are testable from the dumps (they are realised dividends), which I
   did: null, and favourite-out combinations are the worst-paying of all.
5. **Recommended next step**: stop looking for a static form factor that overturns favourites;
   move the decision to the close and build the model on the late market itself (exchange and
   tote flow, timestamped day-of state), test the owner's thesis as a lay-the-favourite claim
   against Betfair SP, and, as the one untried fundamental approach, fit a margin-based rating.

## 1. How the market works, and where information could be missing

Prices at Sportsbet and Ladbrokes are set in the morning from ratings, form and a framing model,
then moved by money. Corporate bookmakers restrict winning accounts, so informed money goes to the
exchange and the tote, and the corporates *follow* those markets, shading longshots heavily. The
T-30 two-book price is therefore a lagging, overround-laden copy of a market elsewhere. At T-30 the
race's oldest quote is hours old. Whatever the public form data lack, the people who have it
(trackwork watchers, trial watchers, stable connections, syndicates with sectional databases)
express it as money in the last 30 minutes, concentrated in the last 10.

Candidate missing components, listed broadly before testing and then ranked:

| # | Component (type) | Mechanism | Cheap test | Result |
|---|---|---|---|---|
| 1 | **Late informed money; decision time and reference market** (timing / market) | Information reaches the price as money after T-30; the sharp markets (exchange, tote) are not in the data | Race log-loss by market snapshot; who wins when the late favourite differs | **Confirmed**, section 2.1 |
| 2 | **Latent ability rating from margins and finishing order** (modelling approach) | Last-start and last-3 snapshots waste most of the information in 176k margins; a jointly fitted rating with track standards is the Benter/Timeform backbone | Proxy: standard-time difference at last start | Inconclusive (coverage 15%); full model not built, section 2.5 |
| 3 | **Bet type matching the thesis** (bet type) | "Favourite loses" is a lay on the exchange or an exotic without the favourite; the corporates' win market shades exactly the horses the thesis wants | Realised quinella/exacta/trifecta dividends vs win-implied, favourite in/out | **Null / negative** for favourite-out, section 2.4; lay untestable here |
| 4 | **Race-level "confirm" calibration** (target) | The owner's decision is binary per race; how often can the favourite be called >50%? | Calibrated P(fav) by band | Price alone: >50% in 9.6% of races; nothing adds, section 2.2 |
| 5 | **Within-meeting track deterioration** (day-of data) | Morning price set on the morning track; a downgrade after race 1 hurts the favourite's framing | Favourite A/E in races after a downgrade | Weak lead: A/E 0.78 on 289 favourites, section 2.3 |
| 6 | Early vs late pre-decision move (microstructure) | Overnight money is sharp, late-morning money is public | A/E by open→T-60 and T-60→T-30 move | Null (0.03 millinats each) |
| 7 | Trials, jump-outs, trackwork, nominations/acceptances (data never collected) | Fitness of resuming horses and stable intent are the content of late money | None possible | Untested |
| 8 | Exchange and tote pre-off flow (data never collected) | The direct observation of component 1 | None possible | Untested |
| 9 | Minimum bet limits, best-of-book, promotions (market structure) | Determine whether a near-the-off edge is executable | Favourite ROI at best of two books | −12% overall; MBL not in any document |

## 2. Tests

### 2.1 Information arrives after T-30; it is the only thing that overturns favourites

Race-level multinomial log-loss of the win, margin-free probabilities renormalised over starters,
same 16,816 races at every snapshot:

| Market | Log-loss | Gain vs T-30 |
|---|---|---|
| Sportsbet T-60 | 1.8525 | −0.0018 |
| Two-book mean T-30 (protocol M) | 1.8507 | — |
| Sportsbet T-10 | 1.8370 | +0.0137 |
| Two-book mean T-2 | 1.8173 | +0.0334 |
| Starting price (fixed-odds close) | 1.8076 | +0.0431 |
| Home-tote closing dividend (V/N/Q) | 1.8062 | +0.0445 |
| Best tote | 1.8010 | +0.0497 |

A third of the gain is in by T-10, three quarters by T-2. The gain is present in every segment
(non-metro +0.045, metro +0.036; VIC +0.029, WA +0.055; Saturday +0.042, weekday +0.044).

In the owner's terms: the later market names a different favourite in 17.1% of races (T-2), 20.6%
(SP), 22.4% (tote). When it does, the T-30 favourite wins 20.1% and the late favourite 26.4%
(T-2); when the two agree the favourite wins 36.3%. Among T-30 favourites, split by the T-30→T-2
move: strong drifters (price lengthens >15%) win 23.7% against a T-30 probability of 28.7%; strong
firmers (shortens >10%) win 40.0% against 30.2%. Beyond the calibrated T-30 price this move is worth
7.7 millinats on the favourite event; the next best of 75 features is 0.35 (table in
`t2_screen.py` output).

The signal is not bettable at the corporates once it is visible: backing the T-2 favourite when it
differs from the T-30 favourite returns −13.2% at the T-2 price (n = 2,875); runners that shortened
by more than 30% between T-30 and T-2 return −27% at the T-2 price (SR 8.3%) although they would
have returned +15% at the T-30 price. The late market over-shoots on strong steamers. Nothing
observable before T-30 predicts the post-T-30 move (open→T-60 and T-60→T-30 moves: 0.03 millinats
each on the favourite event).

### 2.2 Nothing pre-decision separates favourite-wins from favourite-loses beyond price

Baseline: logistic calibration of the favourite's win on logit(M_T-30), log-loss 0.6089 (raw price
0.6116). For each of 75 candidate features I report A/E by quintile against the calibrated baseline
and the log-loss gain from adding the feature. Everything static is at noise level:

| Feature (favourite) | Gain, millinats | Quintile A/E range |
|---|---|---|
| T-30→T-2 move (post-decision) | 7.73 | 0.76 – 1.21 |
| F6 top speed last start (n 4,955) | 0.35 | 0.88 – 1.06 |
| F5 distance travelled (n 3,586) | 0.28 | 0.91 – 1.04 |
| F1 closing sectional (n 2,410) | 0.26 | 0.92 – 1.07 |
| metro venue | 0.23 | 0.94 – 1.01 |
| relative carried weight | 0.20 | 0.96 – 1.03 |
| F18 barrier cell | 0.19 | 0.97 – 1.05 |
| field size | 0.17 | 0.97 – 1.07 |
| favourite gap to 2nd (F12 G) | 0.04 | 0.98 – 1.02 |
| last-start winner, was favourite last start, days since run, jockey/trainer A/E, class, distance, gear, stewards' flags, pace style and count, book disagreement, quote age, open→T move, same-day meeting results | ≤ 0.13 each | within 0.93 – 1.07 |

For naming the alternative (ranks 2–4 at T-30, n = 50,448): the post-decision move 5.59 millinats;
F1 closing sectional 0.47; everything else ≤ 0.21.

The favourite's gap to the second favourite is already fully priced: by gap quintile the favourite
wins 22.8 / 26.6 / 31.4 / 36.5 / 50.4% against prices of 22.0 / 24.6 / 28.4 / 33.6 / 44.1%, and the
second favourite wins 22.2 / 21.0 / 20.5 / 19.2 / 14.9% against 20.6 / 20.1 / 19.7 / 18.9 / 16.2%.
When the favourite loses, the second favourite wins 29.4% of those races, the third 21%; the winner's
T-30 rank distribution is 33.5 / 19.6 / 14.0 / 9.8 / 7.6 / 5.1%.

"Confirm" capacity by price alone: the calibrated P(favourite) is ≥ 0.5 in 9.6% of races (realised
57.5%), ≥ 0.45 in 16.7% (54.4%), ≥ 0.4 in 25.8% (49.5%). In three quarters of races the favourite
is below 40% and nothing in the data raises it.

### 2.3 Within-meeting track deterioration (weak lead)

Using each race's recorded condition against the meeting's first race (a non-outcome field, built
from eligible and excluded train races): favourites in races run after a one-step downgrade
(Good→Soft, Soft→Heavy) won 70 against 90.1 expected, A/E 0.78 (n = 289, z ≈ 2.6); after an upgrade
A/E 1.02 (n = 912); unchanged 1.00 (n = 14,936). One bucket, small, and the recorded race condition
is an end-of-day value, so this is a lead for the timestamped live data, not a finding.

### 2.4 Exotic pools: the favourite-out thesis pays worst of all

The project says exotics are "untested" because pre-off pools are not in the dumps. That is the
wrong framing for tote bets: the historical return of a tote bet is the realised dividend, which is
in the dumps for every race (`exotics`), and the decision can be made from the win market. On 16,714
train races with Quinella and Exacta dividends and 16,634 with Trifecta, decided from T-30 ranks:

| Strategy (T-30 ranks) | Hits | ROI |
|---|---|---|
| Quinella box 2-3-4 (favourite out) | 2,565 | −16.7% |
| Quinella favourite with each of 2,3,4 | 5,864 | −16.2% |
| Quinella box 1-2-3 | 5,632 | −17.0% |
| Exacta 2,3,4 over favourite | 2,305 | −19.0% |
| Exacta favourite over 2,3,4 | 3,559 | −17.0% |
| Trifecta box 2-3-4 | 515 | −28.6% |
| Trifecta box 1-2-3 | 1,753 | −25.5% |

Dividend × Harville probability from SP (1 = fair before takeout): quinella 0.89 when the favourite
is in the combination, 0.81 when it is out; trifecta 0.88 vs 0.69; the favourite-out figure falls to
0.38 for trifectas when the favourite is ≤ $2. Part of that is Harville's own bias, but the
model-free strategy returns say the same thing: the crowd over-bets combinations that leave the
favourite out. There is no exotic-pool edge on the "favourite loses" side.

### 2.5 Speed-figure proxy, favourite ROI, other checks

- Last-start standard-time difference (the only speed-figure-like field): favourites coefficient
  −0.050 per SD, 1.09 millinats, but n = 2,018 (15% coverage, sectional races only). Ranks 2–4:
  +0.016 per SD, 0.12 millinats. Inconclusive; the field is too sparse in the dumps to carry a
  rating.
- Backing the T-30 favourite at the best of the two books: −7% (≤ $2), −13% ($2–2.5), −12%
  ($2.5–3), −15% ($3–4), −15% ($4–6); −12.3% overall; −11.7% at SP; −12.3% at the tote. The
  favourite-longshot bias does not cover the overround.
- Tote vs fixed-odds SP at the close: runners whose tote dividend is shorter than SP win 9% more
  than SP says; longer, 18% less. The tote is better calibrated than the corporates' SP across the
  whole range (A/E 0.90–1.07 vs 0.82–1.09). Conditional on the tote, the fixed-odds close adds
  little.
- Free Betfair historical SP files (`promo.betfair.com/betfairsp/prices/dwbfpricesauswin*.csv`)
  returned HTTP 403 through this environment's proxy; the feasibility of a Betfair-SP evaluation
  could not be checked here.

## 3. Against the project's documents

**Already covered (and by my numbers, correctly).** MISSING_COMPONENT.md identifies the late-money
component with the same magnitude (+0.043 vs my +0.045), the T-2 persistence split (bias vs
staleness), the first-upper drift, the race-selection idea, the collection list (exchange, tote
approximates, trials, timestamped track state). FACTORS_V2_PROPOSAL.md's 16 market-only
corrections and 22 families being null matches my screen: no static feature reaches 0.5 millinats
on the favourite event. The bettability audit (quote survival, eight-second co-movement, T-30 paper
edge vanishing at SP) is consistent with my steamer result. RESULTS.md's claim C being dead is
consistent with section 2.2: there is no overturn rule to be had from form.

**Framed badly or wrong.**

1. *The owner-facing translation is missing.* The documents report millinats. They never say
   plainly that (a) the premise "outsider better than its price" is inverted on average at
   corporate prices (A/E 0.55–0.84, ROI −35% to −63%), (b) nothing pre-decision separates
   favourite-wins from favourite-loses, and (c) "confirm" with better than even confidence exists in
   under 10% of races, by price alone. Those three facts answer the owner's question.
2. *"Exotics untested, need pre-off pools."* Wrong for tote bets; the realised dividends are the
   returns. Tested: null, and worse for the thesis than the win market.
3. *Claim D (closing-line) as the confirmatory companion.* Closing-line value at the corporates'
   SP is contaminated by the corporates' own late shading: strong steamers are over-shot at T-2
   (−27% at the T-2 price, below the average runner). A positive slope of ln(SP/M) on the model's
   deviation can reward predicting over-reactions. If closing-line value is to be the target, the
   reference close must be the exchange's (BSP), not the fixed-odds OP feed.
4. *Carried weight as the lead family.* For the favourite decision it is nil (0.20 millinats,
   quintile A/E 0.96–1.03). The −0.06/SD runner-level effect may be real, but it does not move the
   confirm/overturn decision, which is what the owner asked for.
5. *The screening instrument.* Win log-loss on 17k races cannot detect a family worth 1 millinat
   with any reliability (the shortlist's intervals show it). Screening weak fundamentals on a
   binary win target is why 38 families came out as noise around zero; it does not show that the
   information is absent, only that the instrument is blunt (RESULTS.md says as much, but the
   remedy, a continuous target, was not taken).

**Considered by none of them.**

- **A latent ability rating from margins and finishing order.** Every feature in FACTORS.md and
  the v2 proposal is a last-start or last-3 snapshot of one quantity. No document fits a horse-level
  rating on all runs jointly (beaten lengths, standard times by track/distance/condition, class,
  weight), which is how the only documented market-beating fundamental models were built (Benter,
  Hong Kong), and which is estimated from 176k continuous margin observations rather than 17k binary
  wins. racing.com exposes `GetRaceStandardTimes` and per-run `standardTimeDifference`,
  `winningTime`, margins and the `timing` sections; the dumps hold the margins for every race. The
  honest prior is that in a market with professional syndicates such a rating recovers little, but
  it is the one standard approach not tried, and the one most likely to have the precision to show a
  small effect if any exists.
- **The bet that expresses the thesis: lay the favourite on the exchange**, evaluated against
  Betfair SP. The Betfair study used BSP as history variables; nobody asked whether P(favourite
  loses) from any model beats the lay price. Betfair publishes free daily BSP files for Australian
  racing with morning WAP, pre-play WAP, traded volume and pre-play max/min, which would also give
  the morning→close exchange move for every runner since 2010, cheaply.
- **Minimum bet limits.** In NSW, VIC, QLD, SA, WA and TAS licensed bookmakers must accept
  race-day fixed-odds win bets up to a stated loss (of the order of $2,000 metropolitan, $1,000
  elsewhere; confirm the current state rules) from a stated time on race day. The bettability
  audit discusses quote survival but never this: a decision taken near the off at a corporate's price
  is executable at scale on race day, which is exactly what a 1,000-bet claim B needs, and it
  removes the "account restriction" objection to a fixed-odds forward test.
- **Exotic dividends as a realised-return test** (done above; null).
- **Nominations and acceptances as intent** (`GetHorseUpcomingRacesGrouped`,
  `GetParticipantCalendar`): a horse nominated for several races and the one chosen, late jockey
  bookings, multiple runners from one stable. Not collected; untested; low expected size.

## 4. Next steps

1. **Move the decision to the close and make the late market the model input.** Extend
   `tools/live_collector.py` to poll at ≤ 30 s from T-15 to the jump, add Betfair back/lay/volume
   and TAB approximates, and log timestamped track condition, rail, weather, scratchings and jockey
   changes at each poll. The forward test should compare a T-2 decision against the T-30 one on the
   same races; everything in section 2.1 says the T-30 frame is the problem, not the factor list.
2. **Test the thesis as a lay.** Download Betfair's free historical BSP files for 2023–2025 (from a
   machine that can reach `promo.betfair.com`), match to racing.com races by date, venue, race
   number and horse name, and evaluate (a) BSP log-loss against the tote and OP close, (b) whether
   any model of P(favourite loses) beats the favourite's lay price after commission, (c) the
   morning WAP → BSP move as the measurable late-money signal. This answers the owner's question in
   its own currency.
3. **Fit a margin-based rating once**, as the single untried fundamental approach: a per-run
   performance figure (beaten lengths adjusted by distance, track, condition, class and weight,
   calibrated against racing.com standard times), a horse rating as a shrunk recency-weighted mean,
   screened on train by its correlation with the late move and with the win beyond M^α. If it does
   not reach 2 millinats out of fold, close the fundamental search for good.
4. **Collect trial and jump-out meetings** (`GetMeetingByVenueDateTrial`, `isTrial`/`isJumpOut`)
   and test, on a price-move target, whether a trial in the prior 21 days predicts the late move of
   first-uppers (MISSING_COMPONENT.md candidate 3; agreed).
5. **Report to the owner in decision terms, not nats**: the base rates by favourite price band,
   the 9.6% of races where the favourite can be called better than even, the −35% to −63% return of
   outsiders at corporate prices, and that no static data in hand overturns a favourite. Then ask
   whether the project's goal is (a) a better T-30 forecast, which is possible and worth ~5% of the
   late information, or (b) money, which needs the close, the exchange and the minimum-bet-limit
   structure, and a different dataset.
6. One targeted check when timestamped conditions exist: favourites after a within-meeting
   downgrade (section 2.3, A/E 0.78 on 289), with the morning condition as the reference.
