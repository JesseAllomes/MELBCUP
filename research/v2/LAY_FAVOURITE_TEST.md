# Lay-the-favourite test at Betfair SP

**2026-10-30. One pre-declared test of the owner's thesis "favourites usually lose, so bet against them".
All outcome statistics are on block = train only (race dates 2023-01-01 to 2025-06-30). No outcome was
computed on tune1, tune2, final, excluded or history_only rows; the Betfair files were read only for
dates 2022-12-25 to 2025-07-05 and joined only to train races. Scripts and intermediate files:
`scratchpad/upsets/layfav/` (`load_bf.py`, `match.py`, `audit.py`, `analyse.py`, `results.py`;
output tables `results_rules.csv`, `results_desc.csv`, `results_year.csv`).**

## Answer in one paragraph

No. Laying the T-30 favourite at Betfair SP loses money at every commission rate tested, overall
(−5.0% per $1 of backer's stake at 8% commission, 95% CI −7.4% to −2.6%) and in each year
(2023 −5.4%, 2024 −4.3%, 2025H1 −5.9%, every interval below zero). Laying only drifting favourites
does not help (−5.8% to −6.1%). Drifting favourites do win less often (25–28% against 33% for all
favourites) — the signal is real — but the Betfair SP already contains it: drifters win almost
exactly as often as their BSP says (actual/expected 1.01–1.02). Before commission, every rule is
within a couple of points of zero, which is exactly what a lay at a fair closing price earns; the
commission then turns it into a steady loss. "The favourite usually loses" is true but already in
the price you would lay at.

## 1. Method (declared before any outcome was read)

**Data.** racing.com train runners (`out/runners.pkl.gz`, block == "train", via the filtered copy
`independent/train_runners.pkl`; asserted all rows are train) and Betfair's public ANZ thoroughbred
files (`betfair/raw/ANZ_Thoroughbreds_2022..2025.zip`, monthly CSVs, read fresh; the cached
`betfair/runners.pkl` and `blueprint.py` were not reused because they drop the scheduled/actual off
times and do not parse the April-2025 file's `d/mm/yyyy` dates and 12-hour clock).
Betfair columns used: date, scheduled and actual off time, track, state, race number, market id,
selection name, `WIN_RESULT`, `WIN_BSP`.

**Decision information (all available by T−2).**
- T−30 favourite: `fav_M_t30` (highest two-book margin-free probability at T−30). Races with
  co-favourites at T−30 are skipped (155 races).
- Favourite's T−30 price q30 = max(Sportsbet T−30, Ladbrokes T−30); q2 likewise at T−2. Both books
  are required at both times (the T−30 favourite always had them in this universe).
- Drift = ln(q2 / q30). Positive = price lengthened.

**Rules (12, fixed in advance; no thresholds were changed after seeing results).**

| Rule | Lay the T−30 favourite at BSP when… |
|---|---|
| R0 | every race |
| R1–R5 | q30 ≤ 1.50; 1.50–2.00; 2.00–3.00; 3.00–4.00; > 4.00 (partition of R0) |
| R6–R8 | drift > 0; > +5%; > +10% |
| C1–C3 (control, firmers) | drift < 0; < −5%; < −10% |

(10.2% of favourites had drift exactly 0 and fall in neither the drift nor the firm group.)
Descriptive splits by BSP band and by whether the T−30 favourite is still the BSP favourite are
also shown; they use the BSP, which is not known until the off, so they are **not** tradable rules.

**Settlement and P/L.** Per $1 of backer's stake laid at BSP:
favourite loses → +1 × (1 − c); favourite wins → −(BSP − 1). Commission c = 8% primary, 5% and 10%
sensitivity, 0% shown as the "gross" edge against BSP. P/L per $1 of liability = ΣP/L / Σ(BSP − 1).
Settlement uses Betfair's own `WIN_RESULT` (agrees with racing.com `won` on 99.95% of matched
starters; 14 of the 17,047 bets differ, protests/dead heats).
- **Dead heats**: Betfair dead-heat rule — with k winners the backer's stake is split, 1/k wins at
  full odds and the rest loses; gross = (1 − 1/k) − (BSP − 1)/k, commission charged only if gross > 0.
  13 favourites dead-heated for first.
- **Non-runners**: if the T−30 favourite was scratched after T−30 the lay is void (no bet, no P/L;
  100 races). Late scratching of other runners is ignored: the BSP is formed after the removal and
  BSP bets are not reduction-factored (Betfair rule; assumed, not verified in the data).
- Liquidity, BSP price impact of a large lay, and Betfair's Premium Charge are not modelled. All of
  them would only make results worse.

**Intervals.** Race-day-clustered bootstrap (resampling Melbourne race dates, 2,000 draws, seed
20261030), statistic = ratio of sums (ΣP/L / Σstakes or Σliability), percentile 95% interval.

## 2. Match audit

**Meeting match.** Each racing.com meeting (date, venue) was matched to the Betfair track on the
same date with the largest overlap of normalised horse names (lower-case, letters/digits only,
country suffix removed); a match needs ≥ 50% overlap. 5,015 of 5,089 train meetings matched; no
Betfair track was claimed by two meetings and every racing.com venue mapped to a single Betfair
track name (e.g. `aquis-park-gold-coast-poly` → Gold Coast, `ladbrokes-cannon-park` → Cairns).
**Race match** is then (date, Betfair track, race number); runners by normalised name inside the market.

| Year | Train races | Betfair market found | Every starter name-matched |
|---|---|---|---|
| 2023 | 7,614 | 99.0% | 98.0% |
| 2024 | 7,125 | 98.8% | 98.1% |
| 2025H1 | 2,855 | 99.1% | 97.9% |
| **All** | **17,594** | **98.9%** | **98.0%** |

| State | Races | Market found | Every starter matched |
|---|---|---|---|
| NSW | 4,719 | 99.0% | 98.0% |
| VIC | 5,071 | 98.9% | 97.7% |
| QLD | 3,352 | 98.6% | 97.9% |
| WA | 2,097 | 99.1% | 98.9% |
| SA | 1,308 | 99.2% | 97.8% |
| TAS | 579 | 99.7% | 99.3% |
| NT | 361 | 100.0% | 99.7% |
| ACT | 107 | 95.3% | 95.3% |

(17,594 = 17,597 train races less 3 with no starters.) Other checks:
- Within matched markets 99.63% of starters were found by name; Betfair selection count equals the
  racing.com starter count in 99.67% of races. Betfair state code equals racing.com state in 100%.
- Betfair `SCHEDULED_RACE_TIME` is on the Melbourne clock: it is within 5 minutes of racing.com
  `start_utc` (converted to Melbourne time) for 97.0% of matched races (67.5% if read as track-local
  time). 151 races differ by more than 30 minutes (mostly Queensland meetings retimed by 35–40 min).
  To guarantee the T−2 quote is pre-off, races whose Betfair actual off is earlier than the
  racing.com start − 2 min are dropped (8 races).
- **Favourites agree.** Where both are unique, the Betfair-SP favourite is the racing.com SP
  (fixed-odds starting price) favourite in **92.2%** of races (16,945).
- **The off favourite often differs from the T−30 favourite**: the T−30 favourite is **not** the
  BSP favourite in **22.8%** of bet races (and not the racing.com SP favourite in 22.0%), consistent
  with the 17–22% change rate found in INDEPENDENT_REVIEW.md.

**Funnel to bets**

| Step | Races |
|---|---|
| Train races with starters | 17,594 |
| Betfair market matched and ≥ 90% of starters name-matched | 17,321 |
| …and the T−2 quote is before Betfair's actual off | 17,313 |
| …and a single T−30 favourite | 17,158 |
| favourite scratched after T−30 (lay void) | −100 |
| favourite ran but had no BSP/name match | −9 |
| Betfair market with no winner recorded | −2 |
| **Bets (R0)** | **17,047** (901 race days) |

## 3. Results (train, 2023-01 to 2025-06)

P/L per $1 of backer's stake unless marked; [ ] = day-clustered 95% interval. "BSP-implied" is the
mean of 1/BSP; A/E = favourite wins / Σ(1/BSP) (1.00 = the BSP is exactly right).

| Rule | Bets | Fav won | BSP-implied | A/E | Gross (0%) | 5% | 8% (primary) | 10% | 8%, per $1 liability |
|---|---|---|---|---|---|---|---|---|---|
| **R0 all T−30 favourites** | 17,047 | 33.3% | 33.3% | 1.001 | +0.3% [−2.1, +2.8] | −3.0% | **−5.0% [−7.4, −2.6]** | −6.4% | −2.0% [−3.0, −1.1] |
| R1 q30 ≤ 1.50 | 388 | 66.5% | 66.2% | 1.004 | −0.2% [−7.4, +6.9] | −1.9% | −2.9% [−10.0, +4.2] | −3.5% | −5.3% [−18.1, +7.8] |
| R2 q30 1.50–2.00 | 2,474 | 51.3% | 50.3% | 1.019 | −2.2% [−6.5, +1.9] | −4.7% | −6.1% [−10.1, −2.1] | −7.1% | −5.7% [−9.4, −1.9] |
| R3 q30 2.00–3.00 | 7,563 | 34.9% | 34.8% | 1.004 | −0.7% [−4.1, +2.6] | −4.0% | −6.0% [−9.1, −2.8] | −7.3% | −2.9% [−4.4, −1.4] |
| R4 q30 3.00–4.00 | 4,962 | 24.3% | 24.8% | 0.979 | +2.7% [−2.1, +7.6] | −1.1% | −3.4% [−8.1, +1.6] | −4.9% | −1.0% [−2.4, +0.4] |
| R5 q30 > 4.00 | 1,660 | 18.4% | 18.7% | 0.980 | +1.7% [−8.0, +12.0] | −2.3% | −4.8% [−14.7, +5.4] | −6.4% | −1.0% [−3.1, +1.0] |
| **R6 drift > 0** | 8,546 | 28.3% | 28.0% | 1.011 | −0.0% [−3.9, +3.6] | −3.6% | **−5.8% [−9.5, −2.1]** | −7.2% | −1.8% [−3.0, −0.6] |
| **R7 drift > +5%** | 6,928 | 27.3% | 26.7% | 1.022 | −0.1% [−4.3, +4.0] | −3.7% | **−5.9% [−9.9, −1.8]** | −7.4% | −1.8% [−3.0, −0.6] |
| **R8 drift > +10%** | 5,010 | 25.5% | 25.0% | 1.021 | −0.2% [−5.4, +4.9] | −3.9% | **−6.1% [−11.1, −1.4]** | −7.6% | −1.7% [−3.0, −0.3] |
| C1 firm < 0 | 6,764 | 38.9% | 39.5% | 0.984 | +2.0% [−1.1, +5.1] | −1.0% | −2.9% [−5.8, +0.2] | −4.1% | −1.6% [−3.2, +0.1] |
| C2 firm < −5% | 5,247 | 39.7% | 40.0% | 0.993 | +1.5% [−2.1, +4.7] | −1.5% | −3.3% [−6.8, −0.0] | −4.5% | −1.9% [−3.8, −0.0] |
| C3 firm < −10% | 3,318 | 39.7% | 40.5% | 0.980 | +2.7% [−1.9, +7.1] | −0.4% | −2.2% [−6.6, +2.4] | −3.4% | −1.2% [−3.8, +1.2] |

Descriptive only (uses the BSP, not tradable as a selection rule):

| Split | Bets | Fav won | BSP-implied | A/E | Gross (0%) | 8% |
|---|---|---|---|---|---|---|
| BSP < 2.0 | 1,988 | 59.8% | 59.0% | 1.013 | −1.4% [−5.1, +2.3] | −4.6% [−8.0, −1.1] |
| BSP 2–3 | 5,309 | 39.6% | 40.4% | 0.982 | +2.2% [−1.1, +5.6] | −2.7% [−5.8, +0.3] |
| BSP 3–4 | 4,624 | 29.6% | 29.1% | 1.017 | −1.6% [−6.1, +2.9] | −7.2% [−11.7, −2.8] |
| BSP ≥ 4 | 5,126 | 19.8% | 19.7% | 1.004 | +0.7% [−5.1, +6.3] | −5.7% [−11.2, −0.2] |
| T−30 fav no longer BSP fav | 3,887 | 21.0% | 20.8% | 1.010 | +1.2% [−5.2, +7.4] | −5.1% [−11.8, +1.2] |
| T−30 fav still BSP fav | 13,160 | 36.9% | 37.0% | 0.999 | +0.0% [−2.3, +2.4] | −5.0% [−7.2, −2.8] |

### By year (8% commission; gross shown for stability of the underlying edge)

| Rule | 2023: bets / won / gross / 8% [CI] | 2024: bets / won / gross / 8% [CI] | 2025H1: bets / won / gross / 8% [CI] |
|---|---|---|---|
| R0 all | 7,389 / 33.2% / −0.1% / **−5.4% [−9.2, −2.0]** | 6,899 / 33.0% / +1.1% / **−4.3% [−8.1, −0.7]** | 2,759 / 34.5% / −0.7% / **−5.9% [−11.4, −0.3]** |
| R1 ≤ 1.50 | 162 / 66.7% / −0.0% / −2.7% [−14.1, +8.2] | 147 / 66.7% / −1.9% / −4.6% [−15.8, +7.5] | 79 / 65.8% / +2.7% / +0.0% [−14.3, +14.0] |
| R2 1.50–2.00 | 1,070 / 47.9% / +5.6% / +1.4% [−4.2, +7.3] | 956 / 53.7% / −8.1% / −11.8% [−18.4, −5.9] | 448 / 54.5% / −8.4% / −12.0% [−22.5, −2.1] |
| R3 2.00–3.00 | 3,268 / 35.4% / −2.5% / −7.6% [−12.5, −2.6] | 3,066 / 34.6% / +0.4% / −4.8% [−9.8, −0.0] | 1,229 / 34.3% / +0.9% / −4.4% [−12.6, +3.7] |
| R4 3.00–4.00 | 2,173 / 24.8% / +0.6% / −5.4% [−13.2, +1.9] | 2,021 / 23.7% / +5.2% / −0.9% [−8.4, +6.4] | 768 / 24.5% / +2.0% / −4.0% [−15.5, +7.9] |
| R5 > 4.00 | 716 / 18.7% / +0.4% / −6.1% [−20.8, +9.3] | 709 / 17.5% / +5.0% / −1.6% [−18.8, +14.2] | 235 / 20.0% / −3.8% / −10.2% [−39.7, +14.8] |
| R6 drift > 0 | 3,748 / 28.6% / −1.9% / −7.6% [−13.2, −2.2] | 3,423 / 27.8% / +2.6% / −3.1% [−8.9, +2.6] | 1,375 / 28.9% / −1.5% / −7.2% [−16.5, +1.4] |
| R7 drift > +5% | 3,042 / 27.6% / −2.8% / −8.6% [−14.9, −2.7] | 2,791 / 26.5% / +4.5% / −1.4% [−8.1, +5.1] | 1,095 / 28.3% / −4.1% / −9.9% [−20.3, +0.6] |
| R8 drift > +10% | 2,204 / 26.5% / −5.4% / −11.3% [−19.0, −4.0] | 2,015 / 24.4% / +5.6% / −0.5% [−8.7, +7.5] | 791 / 25.8% / −0.1% / −6.1% [−17.0, +4.9] |
| C1 firm < 0 | 2,816 / 38.7% / +2.4% / −2.5% [−7.1, +2.4] | 2,820 / 38.4% / +2.3% / −2.6% [−7.6, +2.3] | 1,128 / 40.4% / +0.3% / −4.4% [−11.7, +2.2] |
| C2 firm < −5% | 2,149 / 39.5% / +1.7% / −3.1% [−8.5, +2.3] | 2,218 / 39.3% / +1.8% / −3.1% [−8.5, +2.0] | 880 / 41.4% / +0.2% / −4.5% [−12.4, +3.2] |
| C3 firm < −10% | 1,352 / 39.9% / +1.7% / −3.1% [−10.3, +3.6] | 1,445 / 39.2% / +2.7% / −2.1% [−8.7, +4.2] | 521 / 40.3% / +4.9% / +0.1% [−11.0, +10.4] |

The one positive cell at 8% (R2 in 2023, +1.4%) reverses to −11.8% and −12.0% in the next two
periods; the drift rules' gross edge flips sign from year to year (R8: −5.4%, +5.6%, −0.1%).

## 4. Why it fails: what the BSP already contains

- **The favourite does lose two times in three, but the BSP says so.** All T−30 favourites won
  33.3%; their BSPs implied 33.3% (A/E 1.001). Laying at a fair price earns zero before commission
  (observed +0.3%) and about −c × (1 − p) after it; at 8% that is −0.08 × 0.667 = −5.3%, against
  −5.0% observed. The loss is the commission, almost to the cent.
- **The drift signal is real but priced.** Strong drifters (R8) win 25.5% versus 33.3% overall —
  the "favourite will lose" signal is there. But by the off their BSP has moved with them: median
  ln(BSP/q30) is +0.37 for R8 (BSP ~45% longer than the T−30 corporate price, versus +0.14 for all
  favourites), and their BSP-implied chance is 25.0%. A/E 1.02: if anything drifters win slightly
  *more* often than their BSP implies, the wrong direction for a layer. The move the owner sees at
  T−2 continues to the close and is fully in the BSP.
- **Short favourites are not underpriced at BSP.** The earlier finding (≤ $1.50 favourites win 65%
  vs 57% implied) was against margin-laden corporate prices. At BSP, ≤ $1.50 (T−30) favourites won
  66.5% against 66.2% implied (A/E 1.00). Betfair's closing price removes that bias, so it is
  neither a reason to lay nor to avoid laying them.
- **Firmers (the control)** win 39–40%, also at their BSP-implied rate (A/E 0.98–0.99). The
  slightly better (less negative) lay result for firmers is not significant and is the opposite of
  what the thesis predicts.
- **The BSP is the closing exchange price** — the best-informed, lowest-margin number in the data
  set, including the late informed money that INDEPENDENT_REVIEW.md identified as the missing
  component. A lay at BSP has to beat that price, not the T−30 corporate price.

## 5. Multiplicity and caveats

- 12 declared rules (5 of them a partition of R0, and the drift/firm rules are nested), on one
  sample. No rule has a positive point estimate at 8% commission; 5 have an interval whose upper
  end reaches above zero (R1, R4, R5, C1, C3), none with a point estimate better than −2.2%. Even gross of commission, no
  rule's interval excludes zero. There is nothing to correct for: with 12 looks, a nominal
  "significant profit" would have needed adjusting, but none appeared.
- Bet counts here differ slightly from earlier train figures (32.9% favourite strike rate) because
  this universe keeps dead-heat and late-scratching races and requires a Betfair match.
- Not modelled: laying at BSP with a liability cap (a limit-on-close would refuse some drifters),
  BSP price impact of the lay itself, thin BSP liquidity at small meetings, Premium Charge. All
  would make results worse or leave them unchanged.
- Settlement by racing.com `won` instead of Betfair `WIN_RESULT` changes 14 bets out of 17,047.
- tune1, tune2 and final were not touched; with no positive train result there is nothing to
  confirm on them.

## 6. Conclusion

Laying the favourite at Betfair SP is a reliable way to lose about the commission: −5.0% of stake
at 8% (−2.0% of liability), negative in all three periods. Restricting to favourites that drift
in the last 30 minutes picks races where the favourite really does lose more often (74–75% of the
time), but the BSP has already lengthened to match, so the lay is still a fair bet before
commission and a loser after it (−5.8% to −6.1%). The thesis "find the races where the favourite
will lose" cannot be expressed profitably by laying at the closing exchange price with the
information tested here; any edge would have to come from information the closing Betfair market
does not already hold, or from acting at a price earlier than the close (e.g. laying at T−30 on
Betfair before the drift happens), which these public files do not record and this test does not
cover.
