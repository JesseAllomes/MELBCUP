# Melbourne Cup trends, round 2: how the bet pays, exotics, market dynamics, and five more runner details

**Status: descriptive research note, 2026-10-30. Companion to `CUP_TRENDS.md`. Nothing here is a proven edge.**
Same data (racing.com public form service, cached), same market yardstick (SP normalised to the race and
corrected for the favourite–longshot bias with α = 1.16 from the 1,093-race staying sample), same rule: a detail
counts only if it beats the price after correcting for the number of comparisons. No race dated 2026 is used.

## 0. Short answer

- **Round 2 added 72 hypothesis tests (62 runner details, 10 market-move groups). None survives a
  false-discovery correction.** Cumulative across both notes: 311 tests, 2 discovery survivors (barrier 1–4,
  entires), neither confirmed on the Cups. Dam-sire stamina could not be tested (the field is empty in the API).
- The useful new material is **about the bet, not the horse.** With fair place chances calibrated on 13,629
  staying-race runners (they predict Cup placings to within 0.1 of the actual 78 top-3s and 104 top-4s):
  - Each-way at the standard **¼ odds, 3 places is negative at every price** in a 24-runner Cup (place part
    −4% to −22% expected; each-way −8% to −26%).
  - A **¼ odds, 4 places** offer turns the place part positive at every price (+4% to +31% expected; realised
    +4% to +24% in 16+ runner staying races), which lifts each-way to roughly break-even (−6% to +7%). The 4th
    place is the only positive-expectation component found anywhere in two rounds, and it is a bookmaker
    promotion, usually stake-capped.
  - **Tote place pays less than fixed ¼-odds place** for everything but favourites (median 63–91% of the
    fixed-odds payout at $6.50 and up).
- **Exotics lose about 20% to the fair line on average** and **40–55% when the combination is all roughies**.
  In the 11 Cups with trifecta data, 9 paid below fair; the two that paid over were "market top-3 horse plus one
  roughie" combinations. The least-bad structure is a box of the market's top four; the worst is an all-roughie
  box.
- **Market dynamics:** the morning fixed price predicts winners worse than the jump price or the tote
  (log-loss 2.00 v 1.95 v 1.95 on 218 feed-complete staying races). Horses that **drift more than 25% from
  morning to jump win two-thirds of what even their SP implies** (19 v 28, p = 0.057, fails correction, agrees
  with the literature). Tote win odds beat SP by a median 2–5% at $3.60–$50 and lose 5% at $51+; "best of SP or
  tote" adds 3–5 points of return.

## 1. Place model (needed for everything in sections 2–3)

Harville's formula (second place drawn from the remaining win probabilities, and so on) overstates how often
short-priced horses fill the minor placings. Fitted on the observed finishing order (top 4) of the 1,093 staying
races, the stage exponents are **1.00 (win), 0.80 (second), 0.65 (third), 0.60 (fourth)** — a Henery/Stern-style
flattening — improving the order log-likelihood from −8,954 (plain Harville) to −8,819.

Calibration: staying sample top-3 actual 3,287 v model 3,279 (A/E 1.002); top-4 4,369 v 4,372. Melbourne Cups
(out of sample for the fit): top-3 actual 78 v model 78.0; top-4 104 v 104.0. By price band the Cup place A/E runs
0.57–1.25 on 2–34 placings per band, i.e. noise around 1. Cup placings are as well priced as Cup wins.

## 2. How the bet pays

### 2.1 Fixed-odds each-way, 24-runner Cup (600 runners, 2000–2025; "EV" = model expectation, "ROI" = what happened)

| SP band | n | Win EV | Place EV ¼, 3 pl | EW EV ¼, 3 pl | Place EV ¼, 4 pl | EW EV ¼, 4 pl | Place EV ⅕, 4 pl | EW EV ⅕, 4 pl | Actual places (3) | Expected |
|---|---|---|---|---|---|---|---|---|---|---|
| ≤ $3.50 | 2 | +7% | −4% | +2% | +8% | +7% | +1% | +4% | 2 | 1.3 |
| $3.60–$6 | 25 | −2% | −13% | −8% | +4% | +1% | −7% | −4% | 6 | 10.4 |
| $6.50–$10 | 66 | −8% | −18% | −13% | +4% | −2% | −10% | −9% | 18 | 19.2 |
| $11–$15 | 52 | −14% | −21% | −17% | +5% | −5% | −11% | −12% | 13 | 10.4 |
| $16–$25 | 102 | −19% | −22% | −20% | +7% | −6% | −11% | −15% | 18 | 14.4 |
| $26–$50 | 158 | −25% | −21% | −23% | +13% | −6% | −7% | −16% | 14 | 14.4 |
| $51+ | 195 | −36% | −15% | −26% | +31% | −3% | +6% | −15% | 7 | 7.9 |

The same table on the 16+ runner staying races (4,572 runners) gives the same shape with much tighter error:
¼ odds 3 places, place EV −5% to −21%; ¼ odds 4 places, place EV +7% to +46% and **realised** place ROI
+8%, +15%, +4%, +7%, +18%, +24%, +6% across the seven bands; each-way ¼/4 realised +8%, +11%, −14%, −10%, −5%,
−9%, −26% (the win half drags it back). Full table: `eachway_results.csv` (63 rows).

Reading: the place part at ¼ odds is fair-to-slightly-negative with 3 places because a quarter of the win odds
is less than the fair place price in a 24-horse field; adding a 4th place at the same fraction is worth
roughly +10 to +30 points. There is no price band where plain each-way at 3 places is positive, and no band
where the win half is positive. If a bookmaker offers ¼ odds 4 places on Cup day, the value is in the place
half and the each-way bet as a whole is about zero.

### 2.2 Tote place v fixed place (where a tote feed exists: staying races 2017–2025, 3,288 runners; Cups 2020–2025, 125 runners)

| SP band | n | Placed | Expected | Tote place ROI | Fixed ¼-odds 3-place ROI | Median tote dividend ÷ fair | Median tote ÷ ¼-odds payout |
|---|---|---|---|---|---|---|---|
| ≤ $3.50 | 250 | 200 | 184 | +14% | +13% | 1.01 | 0.98 |
| $3.60–$6 | 490 | 248 | 248 | −3% | −2% | 0.94 | 0.97 |
| $6.50–$10 | 568 | 220 | 193 | −2% | +7% | 0.84 | 0.91 |
| $11–$15 | 363 | 80 | 86 | −25% | −14% | 0.79 | 0.86 |
| $16–$25 | 507 | 98 | 86 | −11% | +6% | 0.76 | 0.83 |
| $26–$50 | 500 | 58 | 55 | −25% | −1% | 0.71 | 0.75 |
| $51+ | 610 | 35 | 29 | −26% | +12% | 0.63 | 0.63 |

The place tote carries its own longshot bias on top of the takeout: longshots' place dividends are 63–76% of
the fair price and 63–83% of what ¼ of the fixed win odds would pay. Favourites are the only band where the tote
place matches fixed odds. On the Cups the 125-runner sample says the same thing with huge noise (`tote_place_results.csv`).

### 2.3 Exotics against the fair line

Fair dividend = 1 ÷ model probability of the exact combination (stage exponents above). Ratio = paid ÷ fair; a
ratio of 0.80 is a 20% loss to the fair line.

| Sample | Pool | n | Median ratio | Mean ratio | Share paying over fair |
|---|---|---|---|---|---|
| Staying races 2022–25 | Quinella | 216 | 0.88 | 0.86 | 20% |
| | Exacta | 216 | 0.84 | 0.83 | 14% |
| | Trifecta | 216 | 0.80 | 0.82 | 20% |
| | First Four | 75 | 0.76 | 0.82 | 27% |
| Melbourne Cups 2014–25 | Quinella | 11 | 0.81 | 0.78 | 0% |
| | Exacta | 11 | 0.79 | 0.77 | 0% |
| | Trifecta | 11 | 0.62 | 0.70 | 18% |
| | First Four | 8 | 0.65 | 0.64 | 0% |

By combination type (staying races; "rank" = SP rank in the field):

| Type of winning combination | Quinella | Exacta | Trifecta | First Four |
|---|---|---|---|---|
| All placegetters in the market's top 4 | 0.92 (116) | 0.87 (116) | 0.84 (52) | 0.80 (6) |
| Mixed | 0.85 (63) | 0.83 (63) | 0.77 (118) | 0.82 (48) |
| Exactly one roughie (rank > 8) | 0.83 (27) | 0.79 (27) | 0.84 (42) | 0.64 (20) |
| All outside the market's top 6 | 0.56 (10) | 0.56 (10) | 0.51 (4) | 0.45 (1) |

(median paid ÷ fair, count in brackets). Cups: trifecta ratios by year 0.60, 0.41, 0.83, 0.63, 0.76, 0.60, 0.59,
0.62, **1.40 (2023: Without A Fight / Soulcombe / Sheraz, ranks 3-5-21)**, 0.28 (2024, ranks 19-11-8), **1.04
(2025: Half Yours / Goodie Two Shoes / Furthur, ranks 3-15-10)**. First fours 0.45–0.88, none over fair; the
2015 $307,081 first four (Prince of Penzance) was 75% of fair. Full list: `exotics_results.csv`.

Reading: recreational money piles onto roughie combinations, so when they come in they pay half of fair;
short combinations are the least overbet. Nothing in the exotics pays over the fair line on average, and the
Cups are worse than ordinary staying races (bigger recreational share), so the "least bad" structure is the
boring one: a box or standout of the market's first four, accepting a ~15–20% loss to fair rather than 50%.

## 3. Cup-day market dynamics

Feeds with time-stamps exist from 2020. "Morning" = the Sportsbet quote in force six hours before the race.

| Sample | Races | Log-loss: morning | SP | Tote (V) | SB close | Winner shorter on tote than SP | Winner firmed morning→SP | drifted |
|---|---|---|---|---|---|---|---|---|
| Staying races 2022–25 (D1) | 218 | 2.001 | 1.949 | 1.949 | 1.947 | 99 | 112 | 86 |
| Melbourne Cups 2021–25 | 5 | 3.05 | 3.11 | 3.01 | 3.15 | 4 | 1 | 3 |

Movement groups, staying races (SP-implied expectation; 5 tests, none passes BH):

| Morning → SP move | n | Wins | Expected at SP | A/E v SP | p | Expected at morning price | A/E v morning | ROI at SP | ROI at morning price |
|---|---|---|---|---|---|---|---|---|---|
| Firmed > 20% | 394 | 34 | 31.6 | 1.08 | 0.67 | 21.9 | 1.55 | +10% | +74% |
| Firmed 5–20% | 555 | 62 | 61.2 | 1.01 | 0.93 | 53.2 | 1.17 | −26% | −17% |
| Steady | 410 | 43 | 42.3 | 1.02 | 0.92 | 41.3 | 1.04 | −35% | −35% |
| Drifted 5–25% | 617 | 60 | 54.7 | 1.10 | 0.40 | 61.0 | 0.98 | −3% | −15% |
| Drifted > 25% | 560 | 19 | 28.2 | 0.67 | 0.057 | 40.7 | 0.47 | −58% | −71% |

The firmers' +74% at the morning price is closing-line value: real, but only available to someone who knows in
the morning which horses will firm. The actionable half is the drifters: a horse 25%+ longer at the jump than
it was in the morning has won two-thirds of its SP expectation (fails correction at 10 tests, matches the
published literature on late drift). Cup winners' prices 2021–25 (morning → SP → tote): Verry Elleegant 18 → 18
→ 16.5; Gold Trip 18 → 21 → 19.4; Without A Fight 7 → 8 → 9.0; Knight's Choice 101 → 91 → 63.5; Half Yours
7.5 → 9 → 8.6. The tote paid less than SP on four of the five. From round 1: horses that firmed more than 15% from
the opening Cup quote are 0 wins from 49 since 2000.

Tote v SP for winners (staying races): median tote ÷ SP 1.00 (≤ $3.50), 1.02–1.04 ($3.60–$25), 1.05 ($26–$50),
0.95 ($51+). Taking the better of SP and tote improves return by 3–5 points in every band but the very long one.

## 4. Five more runner details (discovery first, Cups second; 62 tests, 0 survivors)

Test counts: staying-race discovery D1 23, Cup-horse history sample D2 8, Cups 31. All in `details2_results.csv`.

**4.1 Lead-up speed** (last-600 m sectional of the most recent start; timing exists for 1,248 D1 runners, mostly
2022+, and 75 Cup runners 2022–25). Fastest last-600 of its last start: D1 36 wins v 29.5 (A/E 1.22, p = 0.13);
Cups 2 of 9. Closed fast (z ≤ −1 within its last-start field): D1 1.15 (p = 0.27); Cups 3 wins from 11 (1.2
expected, p = 0.08: Verry Elleegant, Without A Fight, Half Yours all closed in the fastest quarter of their lead-up
field). Closed slowly (z ≥ +1): D1 0.63, Cups 0 of 5. Consistent in direction, far from significant, and sample is
small. Worth a column in 2027 when more years have sectionals.

**4.2 Handicap rating against weight** (rating − 2 × weight, centred on the race; handicaps with ratings,
2005+). D1: every band between A/E 0.92 and 1.12 — the handicapper's line is priced. Cups: "well in by 6+
points" 3 wins from 13 (1.3 expected, p = 0.12); best-in in the race 4 from 21 (1.9, p = 0.10); worst-in 0 from
31 (0.5). Suggestive on the Cups, no support in the big sample.

**4.3 Pedigree stamina.** Sire's progeny place rate at 2,800 m+ (6,246 such runs in the cached meetings, horse
itself excluded, sires with 30+ progeny runs). D1: top-third sires A/E 0.99, bottom third 1.08, unproven sires
1.04 (p = 0.03, fails correction) — pedigree is priced. Cups: top-third sires 8 wins from 109 (5.3 expected, 1.50,
p = 0.19); bottom third 1 from 59. **Dam-sire: not testable** — `sireOfDamHorseCode` is empty in every record.

**4.4 Run style and race shape.** Habitual settling position over prior 2,000 m+ runs (3+ runs). Cups:
habitual midfield 14 wins from 213 (7.9 expected, p = 0.008); habitual on-pace 0 from 41 (1.4); habitual
backmarkers 4 from 133 (5.5). The same horses in other staying races (D2): midfield 1.08, on-pace 0.83,
backmarkers 1.07 — no support, so the Cup number is the round-1 "settled midfield last start" finding again
(p = 0.003 then, BH-adjusted ≈ 0.4). Race shape of the 26 Cups: 15 winners settled in the middle third, 6 in
the back third, 4 in the front third (Delta Blues, Vow And Declare, Twilight Payment all-the-way, Ethereal);
the field splits 184/194/198. Leaders do win Cups, about once in six; the market does not misprice it.

**4.5 Going.** Wet Cups (track Soft/Heavy): 2001, 2004, 2005, 2010, 2018, 2019, 2022, 2025. Runners with a
prior wet-track win: 6 wins from 122 (5.4 expected, 1.10); never raced on wet 1 from 25; wet record better than
dry 5 from 65 (2.9 expected, p = 0.12); on good Cups, proven mudlarks 6 from 196 (8.7 expected, 0.69). D2: all
between 0.58 and 1.13. Going form is priced.

## 5. Counting

| Round | Tests | Passed FDR q = 0.10 in discovery | Confirmed on Cups |
|---|---|---|---|
| 1: runner factors (CUP_TRENDS.md) | 239 | 2 (barrier 1–4, entires) | 0 |
| 2: runner details (this note §4) | 62 | 0 | 0 |
| 2: market-move groups (§3) | 10 | 0 | — |
| **Total** | **311** | **2** | **0** |

The each-way, tote-place and exotics sections are economic evaluations against a calibrated model, not
hypothesis tests; their uncertainty is in the model (checked: place A/E 1.00 on 13,629 runners, 1.00 on the Cups).

## 6. Checklist (unchanged from round 1)

Nothing in round 2 beats the price after correction, so the horse-selection checklist in `CUP_TRENDS.md` §6
stands as written, with one footnote: if two horses are otherwise equal, the one that closed in the fastest
quarter of its lead-up field and settles midfield by habit has the better Cup record (p ≈ 0.01–0.08 on the Cups,
no support in the big samples; treat as a tie-breaker, not a reason).

## 7. How to bet it (bet types and terms — descriptive, model-based, not advice to bet)

1. **Win only at the jump price, or better, best-of SP and tote.** The morning price is a worse forecast
   than the jump; "best of" adds 3–5 points. A flat win stake across the Cup field has lost 15% since 2000;
   no price band is positive.
2. **Each-way only if the terms are ¼ odds and 4 (or more) places.** At 3 places each-way is −8% to −26%
   expected at every price; at ¼ odds 4 places it is about zero (−6% to +7%) because the place half is +4% to
   +31%. If the bookmaker lets you bet place-only on those terms (rare; usually a capped promotion), that is
   the one positive-expectation bet found in either round.
3. **Prefer fixed-odds place to tote place** for anything longer than $6: the tote place pays 63–91% of
   the fixed ¼-odds payout. For favourites they are equal.
4. **Don't take ⅕ odds for 4 places thinking it is the same offer**: it is worth 10–15 points less than ¼
   odds 4 places and is negative each-way at every price above $3.50.
5. **If you are told the price moved:** a horse 25%+ longer than its morning price has won about two-thirds
   of what even its jump price implies; a horse that firmed sharply from its opening Cup quote has never won
   (0 of 49). Neither is significant after correction; both agree with what is known about late money.
6. **Exotics:** expect to lose about 20% to the fair line on a quinella, exacta or trifecta and more on a
   first four. Roughie-only combinations pay half of fair when they land; a box or standout of the market's
   first four is the least bad structure. The two Cup trifectas that paid over fair (2023, 2025) were a
   market top-3 winner with one $26+ horse in the placings — "favourite to win, roughie for third", not "all
   roughies".
7. **Size it as entertainment.** The best realised subset return in either note comes from one or two $90+
   winners; the model-fair expectation of every structure except the 4-place promotion is negative.

## 8. Files

Scripts (scratchpad `cupwork/`): `placemodel.py` (stage-exponent fit), `analyze_eachway.py`, `analyze_tote_exotics.py`,
`analyze_market.py`, `analyze_details2.py`, `scan_local2.py` and `extract_api_meetings.py` (run index with
sectionals, tote odds, exotics), `collect_exotics.py` (26 Cup meetings, exotics and timing). Outputs
(scratchpad `cup/`): `eachway_results.csv`, `tote_place_results.csv`, `exotics_results.csv`, `market_results.csv`,
`market_moves.csv`, `market_tote_vs_sp.csv`, `details2_results.csv`, `cup_runners_round2.csv`, `place_meta.json`,
`run_index.csv` (662,874 runs, 2022-07..2025-12), `run_index_api.csv` (100,386 runs at the fetched meetings).
Nothing committed; no paid services; only this file added to the repository.
