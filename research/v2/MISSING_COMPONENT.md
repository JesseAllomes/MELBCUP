# What is being missed? A diagnosis of the frame, not the factor list

**2026-10-30. Train-only outcomes (2023-01-01 to 2025-06-30). tune1/tune2 are reused development
periods and were not read for outcomes; final stays sealed. Scratch: `scratchpad/upsets/round2/r2_ceiling.py`,
`r2_lateinfo.py`.**

## 1. The measurement that was never made

The project benchmarks every model against M at T−30 and asks whether form data beat it. It never
asked how good that benchmark is relative to the market that actually settles the race. On the same
17,473 eligible train races, each market with its own fitted α (one parameter, descriptive):

| Market | Log-loss (α) | Gain over M_T−30, nats/race, 95% race-day interval |
|---|---|---|
| Two-book consensus at T−30 | 1.8537 | — |
| Two-book consensus at T−10 | 1.8392 | +0.0145 [+0.0125, +0.0164] |
| Two-book consensus at T−2 | 1.8200 | +0.0337 [+0.0302, +0.0371] |
| Starting price (fixed-odds close) | 1.8038 | +0.0428 [+0.0387, +0.0468] |
| Tote closing dividend (V/N/Q) | 1.8121 | +0.0415 [+0.0372, +0.0457] |

Every form family screened in v1 and round 2 (38 families) adds +0.002 nats at most, optimistically,
on train. The market itself improves by **+0.043** between T−30 and the off. **The form pipeline
recovers about 5% of the information that arrives after the decision time.** Per runner the median
absolute repricing from T−30 to SP is 19% of probability; 44% of runners move by more than 25%.
Three quarters of the gain is already in by T−2; a third by T−10.

That is the missing component: **the information carried by late money.** It dwarfs everything in
the factor list, and it is, by construction, invisible to a pipeline that freezes the world at T−30
and reads only static form fields.

## 2. Assumptions in the frame, and which ones can hide it

| Assumption | Could it hide the component? | Evidence |
|---|---|---|
| **Benchmark = two-book price at T−30** | **Yes, this is it.** The T−30 quote is a morning price (race's oldest quote typically 4–12 h old). Beating it with form data is possible (+0.002) but almost nothing of what beats it is bettable at the close, because the close already knows 20× more. | Table above; claim-B audit in FACTORS_V2_PROPOSAL.md section 3 (T−30 paper ROI +23–31% → ≈0% at SP). |
| **Decision time T−30** | Yes. A T−2 decision faces a market 0.034 nats better; the only things that survive there are genuine biases (weight −0.060/SD, ground-made −0.023/SD). Staleness effects (preparation, market memory, course) vanish at T−2. | T−2 persistence check (proposal, section 0.3). |
| Eligible population excludes feed-not-live races (half of all races) | **No.** Tested: on 25,064 excluded train races with a full two-book market, the SP-over-M_T−30 gain is +0.040 [+0.036, +0.043], not larger; M_T−30 log-loss is lower there (smaller fields); the weight effect is smaller (−0.046 vs −0.082/SD). The thin feeds are not where the errors are biggest. | `r2_ceiling.py` |
| Target = win; tote/place/exotics ignored | Win tote close ≈ SP (−0.001 [−0.003, +0.001] eligible; −0.004 excluded). No win-tote inefficiency at the close. Place and exotic pools are not in the dumps pre-off; untested. | `r2_ceiling.py` |
| Unit = one runner; race composition only through F7 | Partly. Late money reprices pace (leaders +1.6%, backmarkers −1.0% within race), but all observable runner types together explain **1.1%** of the variance of the late move. Race-level repricing magnitude is weakly predictable from descriptors (R² 0.08 in-sample, 0.11 out-of-time; top predicted decile mean |move| 0.29 vs bottom 0.20). | `r2_lateinfo.py` |
| Loss = mean log-loss over all races | Partly. The net T−30→SP gain is concentrated: 3% of races carry half the net gain, 59% of races gain at all. A race-selection stage is a different problem from a better f(X). | `r2_ceiling.py` |
| Day-of information not time-stamped (track condition, rail, weather, scratchings) | Could not be shown with the dumps: within-meeting condition changes occur at 7% of meetings and races after a change show the same gain (+0.044 vs +0.043); late scratchings after T−30 the same (+0.045 vs +0.043). The dumps cannot separate morning condition from the race-time condition for the other 93% of meetings. | `r2_lateinfo.py` |
| Data never collected: trials, jump-outs, trackwork | Untestable. The largest observable type effect in the late move is **first-uppers drift by 4.1%** (others +1.0%) and 7+-year-olds drift by 2.5%; the market learns something after the morning about resuming and older horses. Trials and trackwork are the only public sources for that, and collection skipped trial/jump-out meetings. | `r2_lateinfo.py` |
| Linear f; trees exploratory | Unlikely to matter: with runner types explaining 1% of the late move, no interaction of those types can recover much. Not the missing component. | — |
| Margin-free two-book mean is "the market" | Two books co-move within seconds (median lag 8 s); no information in weighting them. The sharp money is on the exchange, which was looked at once (Betfair study, 2025-01 to 2026-09) and is not in the dumps. | lead-lag audit |

## 3. Ranked candidates

### 1. Late information flow (money after T−30) — the benchmark/decision-time assumption

- **Mechanism.** Prices are set in the morning from ratings and form; the information that moves them
  afterwards is private, or public but unstructured (trackwork, trials, stable intent, on-course
  observation, sharper models). It reaches the price as money, mostly in the last 10 minutes.
- **Why the pipeline cannot see it.** The dumps hold change-event fluctuations, and at T−30 most runners
  have no change since the morning (median runner quote 50–80 min old; race's oldest 4–12 h). There is
  no flow to read. The static form fields explain 1% of the late move. The pipeline's microstructure
  families (velocity, recency, tilt) were null because the signal has not started when T−30 arrives.
- **Expected size.** 0.043 nats/race, 20× the best model. Not all of it is capturable by anyone, but it
  bounds the problem and it says that any T−30 "edge" must be checked against the close before it is
  called an edge.
- **Cheapest decisive test (done, above).** The gap exists at every segment: non-metro +0.045 vs
  metro +0.036, VIC smallest (+0.028), WA largest (+0.056); fields of 5–7 smallest (+0.029). Nulls:
  excluded feed-not-live population, within-meeting condition changes, late scratchings, tote.
- **What remains testable with existing data.** Whether the morning→T−30 flow, where it exists,
  predicts the T−30→close move at the runner level (sign and size), using the raw fluctuation series
  rather than four snapshots. This is a price-move target, not a race outcome, so it can be studied on
  train and development data freely. v1's F10 (+0.00007 on win log-loss) suggests it is small, but the
  win log-loss is the wrong instrument for it.

### 2. Race selection — where the T−30 market is most provisional (loss-function assumption)

- **Mechanism.** The market's T−30 error is not uniform: it is concentrated in a minority of races
  (3% of races carry half of the net repricing gain). A model that forecasts *how much* a race will be
  repriced can confine betting to races where a T−30 price is cheap, and can tell claim B where its
  bets have a chance of surviving to execution.
- **Why the pipeline cannot see it.** One global f(X) and a mean log-loss treat every race alike; the
  conditional logit removes every race-level quantity by construction.
- **Expected size.** Moderate. Race descriptors alone give R² ≈ 0.1 and a 1.5× spread in mean
  |move| between top and bottom predicted deciles. Adding the morning flow and the race's quote age
  structure would raise it; the ceiling is unknown.
- **Cheapest decisive test.** On train out-of-fold bets (`r2_oof.pkl.gz`), split the claim-B rule's
  bets by predicted repricing decile and compare settled ROI at T−10 and SP: if the surviving edge sits
  in low-repricing races, selection helps execution; if it sits in high-repricing races, it is the
  stale-price effect again. Under 10 minutes of compute; not yet run.

### 3. Content of the late information for resuming horses: trials, jump-outs, day-of track state (data never collected)

- **Mechanism.** First-uppers are the type late money repudiates most (−4.1% within race). What the
  market learns about them between the morning and the off is fitness: barrier trials, jump-outs,
  trackwork reports, and on the day the track condition and rail. The morning price cannot encode a
  trial the bookmaker's framer did not watch; the money that did arrives late.
- **Why the pipeline cannot see it.** Collection deliberately skipped trial and jump-out meetings;
  condition, rail and weather are stored as final values; no trackwork source exists.
- **Expected size.** Unknown; bounded above by the first-up share of the late move (first-uppers are
  19% of runners and the single largest observable type effect). Testability with existing data: none.
- **Cheapest decisive test.** Requires collection (section 4). The first in-sample check, once trial
  dumps exist, is whether a trial in the prior 21 days and its finishing position predict the late move
  of first-uppers (price-move target, no outcomes needed).

## 4. Collection changes

1. **Live collector (tools/live_collector.py on main):** keep the four fixed-odds books, add the
   exchange (Betfair back/lay and matched volume) and the tote approximates where the API exposes
   them; poll at ≤ 60 s from T−30 to the off so the flow itself becomes the feature; log scratchings,
   jockey changes, track condition, rail and weather at every poll with their timestamps. This is the
   only way to observe candidate 1 directly and to run a T−2 decision rule.
2. **Trials and jump-outs:** collect the `isTrial`/`isJumpOut` meetings the archive skipped (same
   `getMeeting` endpoint), with per-runner finish, margin and time where published.
3. **Day-of track state:** the meeting-level `comments` ("Interim 9/3 - 7:30am"), `trackConditions`
   per race and `previousRailPositions` show racing.com publishes timed updates; the live collector
   should capture the morning value and each revision.
4. **Place and exotic pools:** not in the dumps pre-off; only the live collector can test the
   alternative-target assumption.

## 5. Recommended next step

Reframe round 2 in two parts.

- **Forecasting claim at T−30 (claim A, D):** keep it, with the understanding that its ceiling is
  roughly 5% of the available repricing; report every claim-A gain next to the T−30→SP gain so the
  proportion is visible.
- **Betting claims:** move discovery to the closing market. A factor is a candidate for a bet only if
  it survives against the T−2 market (today: carried weight, ground made). Everything else is a
  stale-price effect and must be evaluated as a *price-move* claim at T−2 with live quotes, not as a
  win-probability claim at T−30. The live collector, extended as above, is the instrument; the
  confirmatory window starts only after protocol v2 and `model-v2` are pinned.
- **Run candidate 2's ten-minute test** on train out-of-fold data before writing protocol v2, because
  its answer decides whether claim B needs a race-selection stage.
