# Melbourne Cup trends, 2000–2025: what the runners' own stats show, and what the market already knows

**Status: descriptive research note, 2026-10-30. Nothing here is a proven edge.** Written for a once-a-year
punter ahead of the 2026 Lexus Melbourne Cup (Tuesday 2026-11-03, Flemington, 3200 m, race 8, 15:00).

## 0. Short answer

- Across the 26 Cups since 2000 (600 runners, 26 winners), **no runner-level factor beats the starting price
  after allowing for the number of things we looked at.** 128 Cup-only comparisons were made; the best p-value
  (0.003, "settled midfield at its last start") is what you expect from 128 tries and does not survive a
  false-discovery correction.
- Because 26 winners cannot support fine-grained tests, every detail was first screened on **1,093 quality
  staying races (2400 m+, Group/Listed/open, 2000–2025, 13,629 runners)** against the SP market. Two details beat
  the price there after correction: **barriers 1–4** (A/E 1.14, p = 0.0001) and **entire males** (A/E 1.34,
  p = 0.0001). On the Cups themselves, barriers 1–4 have *under*-performed the market (3 wins from 104,
  4.7 expected) and entires have done only slightly better than priced (10 wins from 149, 8.5 expected,
  one-sided p = 0.32). Neither passes the check sample.
- Lead-up details (days since last run, last-start margin, number of runs in the preparation, settling
  position, 3000 m experience, course form) were screened on 1,107 runs of Cup horses in other staying
  races (39 tests): nothing survives correction.
- The well-known "Cup trends" are mostly real as *descriptions of winners* and mostly **already in the
  price**: light weights, 4–6-year-olds, Caulfield Cup form, internationals. Several are plain myths on
  this data (barrier 18, "no topweight wins", "ignore 7yo+" as a betting rule).
- Total comparisons in this note: 72 (discovery, within-race) + 39 (discovery, lead-up) + 128 (Cups) = **239**.
  With 239 tests at the 5% level you expect about 12 "significant" results by luck. We got about that many.

## 1. Data

- racing.com's public form service (`graphql.rmdprod.racing.com`, `getMeeting`, `GetMeetingByMonth`,
  `GetRaceEntryItemByHorsePaged`). Raw responses are cached under the session scratchpad `cup/` folder.
- **Cups:** the Flemington meeting on the first Tuesday of November, 2000–2025; the 3200 m race named
  "Melbourne Cup". 600 runners (21–24 a year), every one with a starting price. Fields used: finish, margin,
  SP, opening quote, weight, barrier, foaling date (age at the race = Cup year − foal year), sex, country of
  breeding, trainer and trainer country code, jockey, handicap rating (2005+), gear changes, stewards'
  comments, settling positions, Sportsbet/Ladbrokes fluctuations (2020+), weight at previous start (2019+),
  rail position and track rating.
- **Lead-up form:** each Cup runner's full racing.com history (484 horses, 17,941 runs, trials excluded).
  Overseas runs are present for most pre-2017 raiders (e.g. Enzeli's Prix du Cadran, Far Cry's Goodwood Cup)
  but are **missing for most 2017–2020 raiders** (Rekindling, Cross Counter, Twilight Payment show no lead-up).
  "Days since last run" falls back to the entry's `lastRaceDate` where racing.com holds it; 16 of 600 runners
  still have no lead-up at all. Career starts are "starts known to racing.com", an undercount for raiders.
- **Internationally trained** = trainer country code GB/IRE/FR/GER/JPN/USA/SAF. The code is as of today, not
  as of the race; spot checks (Oxx, Pipe, Weld, Wöhler, the O'Briens, Appleby, de Kock, Mott) look right,
  HK codes (Hall, Hayes) are treated as local. 159 of 600 runners (26.5%) are raiders.
- **Discovery sample D1 (within-race details):** every flat race of 2400 m or more, 2000–2025, at any
  meeting where a Cup runner ran a 2400 m+ race (1,833 meetings fetched) plus the complete local dumps for
  2022-07 to 2025-12, Melbourne Cups removed, kept if Group 1/2/3, Listed or open class (BM84+/open handicap/
  cup/WFA), 6+ runners, a price for every runner and a book between 100% and 160%. 1,093 races, 13,629 runners.
  No race dated 2026 is used anywhere (so the sealed block 2026-05-01..2026-09-28 is untouched).
- **Discovery sample D2 (lead-up details):** the Cup horses' own runs in D1 races. Runs *before* a horse's
  first Cup are excluded: a horse only gets into a Cup by winning or placing in lead-ups, so its pre-Cup runs
  beat the market by construction (310 wins against 164 expected). Post-first-Cup runs: 1,107 runs in 574
  races, 108 wins against 99.6 expected.

## 2. Method

- **A/E** = actual wins ÷ wins expected from the market. Expected = each runner's SP probability, normalised to
  the race, then corrected for the favourite–longshot bias with one exponent α fitted on D1 (α = 1.16; with
  it, favourites' A/E on D1 is 0.99 and $51+ shots' is 0.84). Raw-SP A/E is in the CSVs too and changes no
  conclusion on the Cups (α fitted on Cups alone is 1.04).
- **p-values** are two-sided Monte-Carlo: 20,000 simulated winners per race drawn from the calibrated market,
  p = share of simulations whose win count for the group is at least as far from expected as the observed one.
  "null 95%" in the CSVs is the 2.5–97.5% band of simulated wins.
- **Multiple comparisons:** Benjamini–Hochberg false-discovery rate q = 0.10 within each sample, and Bonferroni
  (0.05/72) reported for D1. A detail "survives discovery" only if it passes BH on D1 or D2; survivors are then
  checked on the Cups one-sided in the discovered direction.
- Everything is **descriptive**. Nothing was pre-registered; the factor list was written before the Cup
  results were seen, but the splits in section 5 were chosen after seeing D1.

## 3. The 26 winners

| Year | Horse | SP | kg | Barrier | Age | Sex | Trained | Days since run | Last start | Fin | Runs in prep |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2000 | Brew | 15 | 49 | 22 | 6 | G | local | 3 | Hotham (Saab) | 1 | 5 |
| 2001 | Ethereal | 10 | 52 | 11 | 4 | M | local | 17 | Caulfield Cup | 1 | 4 |
| 2002 | Media Puzzle | 6.5 | 52.5 | 3 | 5 | G | raider | 13 | Geelong Cup | 1 | 3 |
| 2003 | Makybe Diva | 8 | 51 | 14 | 4 | M | local (GB-bred) | 17 | Caulfield Cup | 4 | 4 |
| 2004 | Makybe Diva | 3.6 | 55.5 | 7 | 5 | M | local (GB-bred) | 17 | Caulfield Cup | 2 | 4 |
| 2005 | Makybe Diva | 4.4 | 58 | 14 | 6 | M | local (GB-bred) | 10 | Cox Plate | 1 | 4 |
| 2006 | Delta Blues | 18 | 56 | 10 | 5 | H | raider (JPN) | 17 | Caulfield Cup | 3 | 1 |
| 2007 | Efficient | 17 | 54.5 | 9 | 4 | G | local | 10 | Cox Plate | 9 | 4 |
| 2008 | Viewed | 41 | 53 | 8 | 5 | H | local | 3 | Mackinnon | 11 | 4 |
| 2009 | Shocking | 10 | 51 | 21 | 4 | H | local | 3 | Hotham (Lexus) | 1 | 6 |
| 2010 | Americain | 13 | 54.5 | 11 | 5 | H | raider | 13 | Geelong Cup | 1 | 3 |
| 2011 | Dunaden | 8.5 | 54.5 | 13 | 5 | H | raider | 13 | Geelong Cup | 1 | 2 |
| 2012 | Green Moon | 20 | 54.5 | 5 | 5 | H | local (IRE-bred) | 10 | Cox Plate | 7 | 4 |
| 2013 | Fiorente | 7 | 55 | 5 | 5 | H | local (IRE-bred) | 10 | Cox Plate | 3 | 4 |
| 2014 | Protectionist | 8 | 56.5 | 10 | 4 | H | raider | 24 | Herbert Power | 4 | 2 |
| 2015 | Prince of Penzance | 101 | 53 | 1 | 6 | G | local | 10 | MV Cup | 2 | 5 |
| 2016 | Almandin | 11 | 52 | 17 | 6 | G | local (GER-bred) | 30 | Bart Cummings | 1 | 4 |
| 2017 | Rekindling | 15 | 51.5 | 4 | 3 | H | raider | n/a | overseas (not in data) | – | – |
| 2018 | Cross Counter | 9 | 51 | 19 | 3 | G | raider | n/a | overseas (not in data) | – | – |
| 2019 | Vow And Declare | 11 | 52 | 21 | 4 | G | local | 17 | Caulfield Cup | 2 | 2 |
| 2020 | Twilight Payment | 26 | 55.5 | 12 | 7 | G | raider | n/a | overseas (not in data) | – | – |
| 2021 | Verry Elleegant | 18 | 57 | 18 | 6 | M | local | 10 | Cox Plate | 3 | 3 |
| 2022 | Gold Trip | 21 | 57.5 | 13 | 5 | H | local (FR-bred) | 10 | Cox Plate | 9 | 5 |
| 2023 | Without A Fight | 8 | 56.5 | 16 | 6 | G | local (IRE-bred) | 17 | Caulfield Cup | 1 | 2 |
| 2024 | Knight's Choice | 91 | 51.5 | 5 | 5 | G | local | 6 | Bendigo Cup | 5 | 4 |
| 2025 | Half Yours | 9 | 53 | 8 | 5 | G | local | 17 | Caulfield Cup | 1 | 4 |

Delta Blues is JPN-trained (raider) but his lead-up was the Caulfield Cup. Market summary: favourites 3 wins
from 28 (5.4 expected); a flat stake on every runner returns −15% at SP; 2nd/3rd favourites and the $11–$20
band have done best (A/E 1.45 and 1.51, p = 0.25 and 0.15), $21–$40 worst (2 wins, 4.8 expected, p = 0.20).
None of that is significant and none of it should be read as a price band to back.

## 4. The famous "Cup trends", checked against the field and the price (Cups only)

A/E uses the calibrated market; "expected" is wins the market implied. n = runners 2000–2025.

| Trend | n | Wins | Expected | A/E | p | Verdict |
|---|---|---|---|---|---|---|
| "Winners carry 53–56 kg" | 300 | 11 | 13.3 | 0.83 | 0.40 | Half the field, 42% of winners: **not even a description**, let alone an edge |
| "Nothing wins with 57 kg+" | 41 | 3 | 3.8 | 0.79 | 0.77 | Makybe Diva 58, Verry Elleegant 57, Gold Trip 57.5. **Myth**; priced about right |
| Top weight | 30 | 2 | 2.9 | 0.70 | 0.76 | Normal, priced |
| ≤52 kg (bottom of the handicap) | 206 | 9 | 6.6 | 1.37 | 0.34 | Light weights win their share and a bit more, within noise |
| "Barrier 18 is cursed" | 26 | 1 | 0.7 | 1.43 | 1.00 | **Myth** (Verry Elleegant 2021) |
| "Draw inside 12" | 312 | 15 | 15.0 | 1.00 | 1.00 | Exactly as priced |
| Barriers 19–24 | 132 | 4 | 4.3 | 0.93 | 1.00 | Wide gates are a mild handicap and the market knows it |
| 4-year-olds | 169 | 6 | 8.4 | 0.72 | 0.37 | Under-performed their price; noise |
| 5-year-olds | 178 | 11 | 8.7 | 1.27 | 0.39 | 42% of winners from 30% of runners; the market gave them 33%. Noise |
| "Ignore 7yo+" | 91 | 1 | 2.3 | 0.43 | 0.50 | 1 win (Twilight Payment, $26). True as a description, **priced in** |
| 3-year-olds | 15 | 2 | 1.1 | 1.88 | 0.60 | Rekindling, Cross Counter: 2 from 15, far too few to say anything |
| Mares | 78 | 5 | 3.0 | 1.65 | 0.33 | Four of the five are Makybe Diva ×3 and Ethereal/Verry Elleegant |
| Geldings | 373 | 11 | 14.5 | 0.76 | 0.20 | 62% of runners, 42% of winners |
| Entires | 149 | 10 | 8.5 | 1.17 | 0.65 | See section 5 |
| Internationally trained raider | 159 | 7 | 9.1 | 0.77 | 0.40 | 20% place rate (best of any group) but **7 wins v 9 expected**: backed to win more than they do |
| Locally trained import (Euro-bred) | 170 | 9 | 6.8 | 1.32 | 0.34 | Best A/E of the three origin groups, within noise |
| Locally trained AUS/NZ-bred | 271 | 10 | 10.1 | 0.99 | 1.00 | As priced |
| Last start Caulfield Cup | 159 | 7 | 8.6 | 0.81 | 0.53 | The classic lead-up; **priced in** |
| Caulfield Cup 1st–3rd then Cup | 46 | 6 | 4.5 | 1.33 | 0.42 | Fine, within noise |
| Caulfield Cup 4th or worse then Cup | 113 | 1 | 4.1 | 0.24 | 0.10 | Only Makybe Diva 2003 (4th). Interesting, not significant |
| Last start Cox Plate | 40 | 6 | 2.3 | 2.65 | 0.02 | 6 wins from 40 (Makybe Diva, Efficient, Green Moon, Fiorente, Verry Elleegant, Gold Trip). Best single Cup number, **does not survive 128 comparisons** (BH-adjusted p ≈ 0.6) and failed to replicate in the discovery sample (racing 6–10 days apart: A/E 0.96) |
| Geelong Cup winner | 19 | 3 | 0.9 | 3.24 | 0.06 | Media Puzzle, Americain, Dunaden, then no Geelong Cup winner has won since 2011. Era effect |
| Hotham/Lexus (Saturday) winner | 23 | 2 | 1.1 | 1.80 | 0.62 | Brew, Shocking; none since 2009 |
| Won last start | 129 | 10 | 9.0 | 1.11 | 0.83 | Priced |
| Ran within 3 days (Derby day) | 109 | 3 | 3.8 | 0.80 | 0.77 | Priced |
| 36+ days since last run | 99 | 1 | 5.0 | 0.20 | 0.07 | Mostly raiders coming straight from quarantine (Protectionist aside, Almandin at 30 days). Suggestive, not significant, and the 2017–2020 raiders' gaps are missing from the data |
| 4–5 runs in the preparation | 249 | 14 | 9.8 | 1.43 | 0.09 | 54% of winners; not significant |
| 6+ runs in the preparation | 88 | 1 | 2.9 | 0.34 | 0.33 | Noise |
| Prior 3000 m+ experience | 319 | 13 | 13.6 | 0.96 | 0.84 | **Irrelevant** once priced: half the winners had never run 3000 m |
| Prior Flemington win | 177 | 11 | 8.8 | 1.25 | 0.37 | Mild, noise |
| Placed in a previous Cup | 37 | 3 | 2.7 | 1.10 | 1.00 | Priced |
| Trainer has already won a Cup (2000+) | 98 | 3 | 5.0 | 0.60 | 0.42 | Big-stable aura is over-bet if anything |
| Trainer's first Cup runner | 219 | 10 | 8.0 | 1.26 | 0.34 | Noise |
| Cup-winning jockey | 105 | 7 | 7.1 | 0.99 | 1.00 | Priced |
| 2 stable runners | 136 | 9 | 7.0 | 1.28 | 0.47 | Noise |
| Well in at the weights (rating −2×kg, ≥ +4 pts, 2005+) | 34 | 4 | 2.7 | 1.48 | 0.48 | Noise |
| Firmed > 15% from opening quote | 49 | 0 | 2.4 | 0.00 | 0.14 | Plunged Cup horses have **never won** since 2000 (0/49); drifters 2/156. Market moves tell you nothing here |
| Any gear change declared | 101 | 3 | 2.9 | 1.05 | 1.00 | Nothing; first-time blinkers in a Cup: 1 runner ever |
| Settled midfield at its last start | 193 | 14 | 7.3 | 1.91 | 0.003 | Best p-value of the 128 but a post-hoc bin; BH-adjusted ≈ 0.4; on the discovery sample A/E 0.99 |

The full Cup table (128 rows, with places, win %, ROI, raw and calibrated A/E and the simulated null band) is
`cup_results.csv` in the scratchpad `cup/` folder, and `cup_runners.csv` has the 600-row runner table.

## 5. The fine-detail search: discovery on 1,093 staying races, then the Cups

The owner's suggestion was that an edge might live in small details. 72 within-race details (D1) and 39
lead-up details (D2) were each measured against the SP market on the staying-race sample before touching the
Cups. Every test is in `d1_results.csv` / `d2_results.csv`.

**D1 (within race, 13,629 runners): 2 survivors of 72.**

| Detail | n | Wins | Expected | A/E | p | BH q=0.10 | Bonferroni |
|---|---|---|---|---|---|---|---|
| Barrier 1–4 | 4,305 | 456 | 399 | 1.14 | 0.0001 | pass | pass |
| Entire male (horse/colt) | 873 | 124 | 93 | 1.34 | 0.0001 | pass | pass |
| Overseas-trained (as-of-now code) | 193 | 36 | 25 | 1.42 | 0.006 | fail | fail |
| Weight ≥ 57.5 kg | 1,980 | 188 | 213 | 0.88 | 0.012 | fail | fail |
| Up 2 kg+ on last start's weight (2019+) | 363 | 25 | 36 | 0.70 | 0.019 | fail | fail |
| Highest-rated horse in the race | 966 | 132 | 155 | 0.85 | 0.027 | fail | fail |
| Field 16+ and barrier 1–4 | 1,062 | 92 | 73 | 1.25 | 0.008 | fail | fail |

Everything else (weight bands, age, price band, open-to-SP firm/drift, Sportsbet flucs, gear changes
including first-time blinkers and tongue ties, breeding country, stable numbers, rating-v-weight, apprentice,
days since last run from `lastRaceDate`, sire staying strike-rate, trainer/jockey staying record, wet-track
imports) sits inside its null band.

Robustness of the two survivors (post-hoc splits, so read loosely):

- *Barrier 1–4* holds in both eras (2000–12 A/E 1.13, 2013–25 1.16), in small and big fields, at 2400–2600 m
  (1.15) but **not at 3000 m+ (1.11, p = 0.44)** and not at Caulfield (1.06). It is really barriers 3–4 (1.21)
  more than 1–2 (1.07). Flat-stake return at SP is still −14%: the market under-rates the inside gate a little,
  not enough to profit at SP.
- *Entires* hold in open-age races (1.29) and in 3-year-old classics (1.43), mainly in the import-bred
  (1.47) and $11+ (2.08) subsets; AUS/NZ-bred entires in open-age races are exactly as priced (1.02). At
  3000 m+ in open-age races: A/E 0.96. So the discovery signal is "the market under-rates imported entires in
  2400–2600 m races", which is close to a Cup-field description, but the 3200 m subset itself shows nothing.

**Check on the Cups (one-sided, direction fixed by discovery):**

| Survivor | Cup n | Wins | Expected | A/E | one-sided p | Places |
|---|---|---|---|---|---|---|
| Barrier 1–4 | 104 | 3 | 4.7 | 0.64 | 0.89 (wrong direction) | 15 |
| Entire | 149 | 10 | 8.5 | 1.17 | 0.32 | 27 |
| Entire and barrier 1–4 | 31 | 1 | 2.0 | 0.50 | 0.89 | 6 |

Barrier 1–4 **fails** the check (it has done worse than the market in the Cup: Media Puzzle, Rekindling,
Prince of Penzance are the only inside-four winners in 26 years). Entires are consistent in direction but a
10-v-8.5 result has no evidential weight; with 26 Cups the test could only have detected an A/E of about 2.
The entire effect is also concentrated in locally trained entires (6 v 4.0) rather than raiders (4 v 4.5).

**D2 (lead-up details on 1,107 post-first-Cup runs of Cup horses): 0 survivors of 39.** Best was "15–21 days
since last run" (33 wins v 21.9, p = 0.009, fails BH at 39 tests); "beaten 6 L+ last start" 1.34 (p = 0.07);
backing up within 7 days 0.75; won during the prep 0.75; settled in the last quarter last start 1.23; prior
course win 0.89. Nothing on 3000 m experience, career starts or step-up in trip. Stewards' comments in the
lead-up were not fetched by the run-history query, so that detail is **untested** here (Cup-day comments are
in the data but are post-race).

**Details the data cannot test**, so they are not claimed either way: jockey changes/late bookings
(the `jockeyChanged` flag is set for one runner in 26 Cups), weight movement between the handicap release
and race day (only weight at the previous start is available; penalties are not recorded), late scratchings
changing the barrier order (scratched acceptors have no barrier in the dumps; none recorded after the draw),
sectionals of the last start (available only 2022+), quarantine dates and travel (only the gap since the last
run, and it is missing for the 2017–2020 raiders), rail position (out 2–4 m on Cup day in most years, "true"
in 2013, 2014, 2016 and 2017; rail-true and barrier ≤ 6 is 2 wins from 24, nothing).

## 6. Checklist for Tuesday's final field (released Saturday night)

Labelled plainly: **descriptive trends from 26 Cups and 1,093 staying races, not proven edges. Nothing below
has beaten the starting price after correction for the number of things tested.** Use it to prune a
sweep or to pick between horses you already like, not as a reason to bet.

1. **Start from the market, not the trend.** Horses at $6.50–$20 have supplied 18 of the 26 winners; the
   favourite has won 3 of 26 (5.4 expected); $21+ shots 5 of 26 from 403 runners (2 of them at $91 and $101).
   None of this is significant, but it is the opposite of "look for a roughie".
2. **Prefer a horse whose last run was 6–17 days ago in a Melbourne feature** (Cox Plate, Caulfield Cup,
   Geelong/Bendigo/MV Cup): 23 of the 23 winners with a known lead-up ran 3–30 days before the Cup; 36+
   days has 1 win from 99 (p = 0.07, not significant, and raiders' gaps are under-recorded).
3. **Lead-up finish matters more than lead-up race.** Caulfield Cup 1st–3rd: 6 wins from 46. Caulfield Cup 4th
   or worse: 1 from 113. A beaten Cox Plate runner is the exception that keeps recurring (3 from 27), but
   that is 27 runners.
4. **Don't rule out weight.** 57 kg+ has won 3 Cups from 41 runners (2005, 2021, 2022), as priced; the
   "ideal" 53–56 kg band has under-performed its price. Topweights are 2 from 30, as priced.
5. **Barrier: treat 19–24 as a mild negative and nothing else.** Inside four has not helped in the Cup (3
   from 104) even though it helps in other staying races. Barrier 18 is not cursed.
6. **Age 4–6 is where the winners are (23 of 26) but the market already prices it**; 7yo+ are 1 from 91 at
   A/E 0.43, so not a bargain either.
7. **Entires (colts/horses) are the only "small detail" that beat the price in the big sample and point the
   same way in the Cup** (10 wins from 149, 8.5 expected). Weak, but if choosing between two otherwise-equal
   horses, the entire has the better record. Locally trained European-bred imports are the origin group with
   the best A/E (1.32), raiders the worst (0.77) despite placing most often.
8. **Ignore:** gear changes, plunges (firmed > 15% from opening: 0 wins from 49), drifts, prior 3000 m
   experience, a trainer's or jockey's past Cup wins, stable numbers, rail position, "handicapper's rating v
   weight", first-time Cup runners. All sit on their price in both samples.
9. **Expected return:** a flat stake on every runner since 2000 lost 15% at SP; the best "trend" subsets
   above show returns from −90% to +130% purely through one or two long-priced winners. Bet for fun, size
   accordingly.

## 7. Reproduction

Scripts (session scratchpad, `cupwork/`): `api.py` (cached GraphQL POST, ≤2.5 req/s), `q.py` (queries),
`collect_meetings.py`, `collect_runs.py`, `collect_months.py`, `collect_discovery*.py`, `scan_local.py`,
`build_cup_table.py`, `build_discovery.py`, `aelib.py` (calibration, Monte-Carlo A/E, BH), `analyze_cup.py`,
`analyze_discovery.py`, `analyze_d2.py`, `tables.py`. Outputs (`cup/`): `cup_runners.csv` (600 × 92),
`cup_results.csv` (128 tests), `discovery_runners.csv` (22,129 rows, 1,953 races before quality filter),
`d1_results.csv` (72), `d2_results.csv` (39), `d1_meta.json` (α = 1.16). Raw API responses: `cup/*.json`
(26 Cup meetings, 484 run histories, 312 month indexes, 1,833 discovery meetings). python3 + numpy + pandas only;
no paid services; nothing in `/home/user/melbcup` was edited except this file.
