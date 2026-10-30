# Adversarial review (reviewer 3): holes, the two parallel tests, and the thing we need

**2026-10-30. Outcome statistics on block = train only (2023-01-01 to 2025-06-30). Nothing was read
from tune1, tune2, final, excluded or history-only rows. Scratch: `scratchpad/upsets/adversarial/`
(`a1_timing.py`, `a2_dispersion.py`). Two checks were run; both are reported in section 4.**

The yardstick is the owner's question: per race, confirm the favourite (and how sure) or name a
horse more likely to win. Everything below is judged by whether it moves that decision.

## 1. Holes, ranked

### H1 (high). "The quote at T−30" is a morning price; the eligibility rule hides that

- Quote age of the T−30 quote among train starters: Sportsbet median **76 min**, 75th pct 4.0 h,
  90th pct 6.8 h; 9% are ≤ 2 min old. Ladbrokes: median 50 min. At T−2 the median is 45 s.
- Races where every runner's quote is ≤ 15 min old at T−30: **411 of 69,086** (0.6%); ≤ 4 h: 19%
  (`funnel_quote_age_sensitivity.csv`). The feed-liveness rule (one fluctuation on *any* runner in
  the last 15 min) admits a race whose market is hours old.
- Consequences. (a) Every "staleness vs bias" classification in FACTORS_V2_PROPOSAL.md (V3, V4, V5
  vanish at T−2) is really "morning price vs close"; it says nothing about a decision taken with a
  live market. (b) The claim-B paper edge of M^α alone (+23% at the T−30 quote, 0% at SP) is the
  repricing of a morning market, as the proposal half-admits; it should never have been called an
  edge or a ceiling. (c) The project's benchmark is not "the market", it is the slowest public copy
  of it. Any claim-A gain at T−30 is a gain over a stale snapshot.

### H2 (high). The instrument every v2 plan rests on has recorded nothing

- The `live` branch holds **one file, 3.5 KB, one run on 2026-10-29, `races_watched: 0`** in every
  cycle. There are no live quotes, no quote-survival measurements, no timestamped scratchings,
  no declared weights. REVIEW_NOTES.md's "first sample of the live weight fields" came from a local
  query, not the collector.
- Protocol v2 as drafted (bettability from the live log, T−2 decision rule, weight semantics,
  execution latency, claim B's count) is unfalsifiable until this store has months of data. The
  forward reconstruction from later dumps cannot substitute: "T approximate" is the thing being
  tested.

### H3 (medium-high). "SP" is the corporate close; the "+0.043 ceiling" is self-revision

- racing.com's `startingPrice` equals the Sportsbet or Ladbrokes last price **exactly** for 65% of
  train starters; log-correlation with the Sportsbet final is 0.996. It is the fixed-odds close of
  the same two books whose T−30 price is the benchmark, not an independent market.
- So the T−30 → SP gain (+0.043) measures how much the corporates revise their own morning prices,
  mostly by following the exchange and tote. Calling it "the information available" or "a ceiling"
  is wrong twice: it is not available at T−30 and it is not an upper bound on what a T−30 model
  could know (a genuine bias would exceed it). The only independent close in the dumps is the tote,
  and both reviewers show the tote is better calibrated than SP. Any closing-line claim (claim D)
  referenced to this SP rewards predicting the corporates' own over-shoot (INDEPENDENT_REVIEW.md
  2.1, steamers at −27%).

### H4 (medium). Decision-time arithmetic: T−2 is really T−3, and 20% of the time T−4 or worse

- 9,451 train races matched to Betfair by date, state, race number and time. racing.com's recorded
  start equals Betfair's scheduled time in **92%** of them (so the recorded start is the schedule,
  not a post-hoc off time: the as-of concern in PROTOCOL.md section 3 is smaller than feared).
- Betfair actual off minus schedule: median **53 s**, 75th pct 95 s, 90th pct 170 s; **20% of races
  jump ≥ 2 min late, 4.6% ≥ 5 min**. The fluctuation feed does continue past the schedule (75% of
  Sportsbet final flucs are after it), so `sb_final`/SP are post-off prices, while "T−2" is a
  schedule-relative snapshot. A decision rule framed at T−2 competes with a close that is 2–7 min
  of late money ahead of it, and the T−2 → SP step of the "ceiling" (+0.009) is partly this delay.

### H5 (medium). Train is exhausted; every new test on it is another draw

- Screened on train so far: 16 v1/v2 families, 22 round-2 families, 16 market-only corrections,
  75 favourite-event features, exotics, segment splits, and now two more tests. tune1 was used for
  refinement, tune2 for one look, final is semi-blind (Betfair study). The only clean data is
  forward, and the forward instrument is empty (H2). A positive from either parallel test on train
  is, at best, a reason to collect; it cannot be evidence.
- Specific instances: V1 carried weight (+0.00101) is the maximum of 22 families selected on the
  same out-of-fold results, and its "persists at T−2" check is on the same races; the interval
  reported is for a pre-specified family, which it was not. REVIEW_NOTES.md flags the optimism but
  the shortlist still carries the un-shrunk number.

### H6 (medium). The owner's goal has a ceiling nobody stated, and it is tiny

- With the closing market in hand (an oracle no T−30 model can match), the favourite changes in
  17–22% of races and the new favourite wins 26% against 20% for the old one (reviewer 2's numbers;
  my T−2 favourite strike rate 34.2% vs 33.0% at T−30 agrees). Perfect knowledge of the close
  raises top-pick strike rate by **about 1.3 points**: one extra correct overturn per ~75 races.
- "Overturn the favourite" is therefore the wrong objective even for an insider. The owner's
  documents never say this. What a model can change is the *price* at which the same horse is
  backed, not which horse is most likely (section 3).

### H7 (low-medium). Smaller artefacts

- Scratchings dated by last fluctuation: 22.6% of scratched entries in eligible train races have
  no fluctuation at all and are silently "scratched before T". Harmless for U, but it means the
  late-scratching count (2.6% of scratched entries) is a floor, and no deduction model exists.
- `weightCarried` in post-race dumps is the carried weight after claims and declared overweight;
  the live field sample shows `apprenticeAllowedClaim` is non-zero for a fifth of entries. Whether
  the morning market priced the pre-claim or post-claim weight is exactly the ambiguity that makes
  a weight coefficient uninterpretable until the collector (H2) has run.
- α fitted in-sample per market in both "ceiling" tables: one parameter, negligible, but the
  comparison is then not strictly out of sample.
- HK rows and July-2022 Ladbrokes gaps are handled; no leak found in history windows (earlier
  calendar days only) or in the fold construction.

## 2. The two parallel tests

### Test 1: lay the T−30/T−2 favourite at Betfair SP, drifting-favourite signal, after commission

- **Can it answer the owner's question?** Only the "overturn" half, and only as a lay. Expected
  result from first principles: α > 1 at the corporates means favourites are *under*-bet there; at
  Betfair the favourite's BSP is close to fair, so a blanket lay returns roughly minus commission
  (5–10% of net winnings by state, plus Premium Charge exposure). The drift signal is read from
  the fixed-odds feed at T−2, i.e. a median 3 min (20%: ≥ 4 min) before BSP is struck, and the
  corporates' drift mostly *follows* the exchange. BSP already contains the signal.
- **How it misleads.** A null (the likely outcome) will be read as "the favourite thesis is dead";
  it only shows that a drift visible at the corporates is priced on the exchange, which was
  known. A positive would need checking against: Betfair times are in eastern clock, not track
  local (my match needed per-state offsets and lost the DST half of each state); dead heats and
  removed runners (`WIN_RESULT` other than WINNER/LOSER); BSP reductions after late scratchings;
  liability-based vs stake-based ROI; and the fact that the favourite by racing.com M at T−30 is
  not the Betfair favourite in a sixth of races.
- **What it could usefully produce instead:** BSP log-loss next to the tote and SP (is BSP the
  best close? almost certainly), and the morning-WAP → BSP move as the measured late-money size.
  That is reference data, not a betting result.

### Test 2: margin-based ability rating beyond M^α, six quarterly folds

- **As-of risk is the whole test.** A Benter/Timeform rating is a joint fit (horse effect + race
  standard + track/distance/condition/weight terms). If it is fitted once on the fold's training
  window, every training row's rating contains the horse's *later* runs in that window; the
  conditional-logit coefficient is then fitted on leaked features and applied to validation
  ratings that are not leaked. That does not fake a validation gain, but it makes the fold
  coefficients meaningless and under-states the feature. The honest version re-estimates the
  rating as of each race date (sequential or daily refit) for training and validation rows alike,
  and freezes race standards on earlier days only. Also: racing.com margins are cumulative lengths
  behind the winner, coarse beyond ~10 L, missing for DNF; horses with pre-2022-07 careers have
  truncated histories (they look lightly raced), which correlates with age and class.
- **Can it answer the owner's question?** No. Reviewer 2's power argument is right (176k margins
  detect 1–2 millinats where 17k wins cannot) and irrelevant: the owner needs tens of millinats to
  move a confirm/overturn decision. A rating that reaches 2 millinats out of fold changes P by a
  percent or two; it cannot overturn a favourite. It is worth running once, as the closing of the
  fundamental search, provided it is scored as a price question (section 3) and not sold as a
  model.
- **Multiplicity:** if screened both on the late-move target and on win log-loss, the better of
  the two is reported; declare one.

## 3. The thing we need

An outsider with public data cannot know more than the closing exchange market about *who wins*.
Everything measured in this project (38 families, 75 features, 16 market corrections, the late-money
component, the oracle ceiling in H6) says so, and nothing in the literature outside full-time
syndicates with proprietary sectionals says otherwise. The probability model the owner is asking
for already exists: it is the calibrated closing exchange price. There is nothing to find beyond it
with form fields.

What an outsider can have is a better **price** for the same probability. That layer has never been
measured here, although the dumps hold five closing prices per runner. Check 2 (section 4): the
T−30 favourite returns −12.1% at SP, −7.3% at the best tote, −5.1% at the best of the closing
prices; for favourites at $2 or less, −2% to −4% with intervals that include zero. For every
starter, −27% at SP against −15% at the best closing price. The spread between venues for the same
horse at the same instant is **5–12 points of ROI**, three to five times the sum of every modelling
gain the project has found, and the best price is the tote seven times in ten.

So the missing component is a **decision-time fair-value and price layer**, not another factor:

1. A reference fair probability: the exchange close (BSP) calibrated, or until live data exist the
   best tote; not the two-book T−30 consensus and not the corporates' SP.
2. The best available price across books, totes and exchange **at the moment of decision**, logged
   with its latency and survival. That is the collector in H2, extended to totes and the exchange,
   run for months before any protocol is frozen.
3. The owner's question restated so that public data can answer it: **confirm** = the favourite's
   best available price exceeds its fair price; **overturn** = some other runner's does. "More
   likely to win than the favourite" is replaced by "cheaper than it should be", which is the only
   form in which the market can be wrong for an outsider.

Historically this can be prototyped now (train only, tote and book finals in the dumps, and BSP
from the Betfair files once matched) as a value-at-best-price test; it cannot be proven
profitable until the live price store exists, because the historical best price is a post-hoc
maximum that a bettor only partly reaches (best-tote products, MBL fixed odds, exchange).

If the owner wants a probability model regardless: build it on the late market (exchange WAP, tote
approximates, timestamped condition) at T−2 to T−0, and report its value only as price obtained vs
BSP. If he wants form-based overturns at T−30, the honest answer is that the data cannot do it.

## 4. Checks run (train only)

**Check 1, timing and SP provenance (prices only, no outcomes).** `a1_timing.py`. Betfair ANZ
files 2023-01 to 2025-06 (484k runner rows), matched to 9,451 eligible train races. Results in H3
and H4: recorded start = Betfair schedule in 92%; actual off median +53 s, 20% ≥ 2 min; SP equals
a book's final price in 65% of starters, log-correlation 0.996; T−30 quote age median 76 min (SB)
and 50 min (LB), T−2 median 45 s; fluctuation feed continues past the schedule.

**Check 2, price dispersion at the close (outcomes, train, scored races without late
scratchings).** `a2_dispersion.py`, race-day bootstrap 95%, 2,000 resamples.

| Selection | n | at SP | SB final | LB final | best tote | best of close |
|---|---|---|---|---|---|---|
| T−30 favourite | 16,220 | −12.1% [−14.2, −10.1] | −12.0% | −11.6% | −7.3% [−9.6, −5.0] | −5.1% [−7.3, −2.7] |
| T−2 favourite | 16,148 | −11.0% | | | −6.2% | −3.9% [−6.1, −1.8] |
| every starter | 165,732 | −27.3% | −27.4% | −26.5% | −17.6% | −15.3% |

Favourites by SP band at the best closing price: ≤$1.50 −3.7% [−9.0, +1.9]; $1.51–2 −2.2% [−5.6,
+1.8]; $2.01–2.50 −5.2%; $2.51–3 −3.6% [−9.1, +1.8]; $3.01–4 −4.0% [−9.0, +1.1]; $4.01–6 −9.2%.
Median ln(best/SP) for favourites 0.057, 90th pct 0.17. **Null for an edge** (nothing is positive);
**positive for the thesis of section 3**: venue choice is worth more than every model combined.
Caveat: "best of close" is a post-hoc maximum; the best tote alone is a real product and carries
most of the gain.
