# Round 2: proposed factor families, market-only baseline, thresholds and protocol skeleton

**Status: proposal, 2026-10-29. Not a protocol. Nothing here is frozen.**

Scope of the evidence in this document: every outcome statistic was computed on **block = train**
(2023-01-01 to 2025-06-30) only, out of fold over the six quarterly folds of PROTOCOL.md section 5
(validation quarters 2024Q1 to 2025Q2: 9,912 scored races, 17,479 train races in total), with
race-day-clustered 95% bootstrap intervals (4,000 resamples). No outcome from tune1, tune2, final,
excluded or history-only rows was read. Counts and coverage were taken on every block.

Scratch code and raw outputs: `scratchpad/upsets/round2/` (`r2_prep.py`, `r2lib.py`, `r2_market.py`,
`r2_horse.py`, `r2_audit.py`, `r2_thresholds.py`; results `r2_*.csv`, `r2_segment_alpha.json`).

## 0. Summary

1. **Market-only step.** Sixteen segment-specific or microstructure corrections to M^α (α by field
   size, class, state, metro, distance, quote age, meetings per day, hour, overround; curvature in
   log M; book tilt; recency-weighted consensus; 60→30 min velocity; open→T move; favourite gap;
   top-two flag) were each tested out of fold against a single α. **None generalises.** The best
   (open→T move, +0.00007 nats per race) has an interval spanning 0. Descriptive segment αs vary from
   1.06 (fields of 14+) to 1.24 (TAS), and that variation is fold noise. **The recommended round-2
   market-only baseline is the single-α model, exactly as v1.**
2. **Horse families beyond M^α.** Of 22 families screened, four were selected by forward selection:
   carried weight (+0.00101 [+0.00044, +0.00158]), last-start market memory interacted with
   non-metro (+0.00059 marginal), the v1 retained block (+0.00025 marginal, interval spanning 0) and
   log days since last run (+0.00028 marginal). Total +0.00213 [+0.00126, +0.00295] nats per race,
   roughly 1.6 times what v1 showed on tune1. Every other family is a null (section 4).
3. **Two kinds of signal.** Against the **T−2** market the weight effect is unchanged (−0.060 vs
   −0.069 per SD) and the ground-made effect is unchanged (−0.023 vs −0.025); the days-since-run,
   market-memory and course-experience effects go to zero. Weight and "eye-catcher" are biases the
   whole market carries; the others are information the T−30 price has not yet absorbed and late money
   does absorb. The two kinds need different claims: the first can support a betting claim at any
   time, the second only if the T−30 quote is actually taken.
4. **Bettability audit.** At T−30 the race's oldest quote is typically 4–12 hours old; a runner's
   quote at T−30 is changed again before the off for 78% of runners; the quote survives 60 s after T
   for 59% (SB) / 63% (LB) of runners and 5 min for 41% / 47%. The two books move together (median
   lag 8 s, 71% within 60 s, 87% same direction), so there is no stale-book window to bet into.
   The claim-B style bets that look profitable at the T−30 quote (+23% to +31% ROI on train) return
   about 0% at starting price: the edge is the T−30 price itself, not a mispricing that survives to
   the off.
5. **Claims.** Claim A (log-loss) is powered: at the train effect size, ~2,300 races exclude zero at
   98.33%. Claim B cannot reach 1,000 bets in a six-month forward window at any threshold that shows
   an edge (29 bets per 1,000 races); it should be reported, not confirmatory, unless the eligible
   population is enlarged by the live collector. Claim C as defined in v1 is dead: at every ratio
   threshold that fires often enough to score, the nominee loses to the best non-favourite. A
   closing-line information claim (does ln(P/M^α) predict the T−30 → SP move?) is strongly powered
   (slope +0.51 [+0.46, +0.56] on train) and is proposed as the confirmatory companion to claim A.

## 1. Market-only calibration (step required before any horse factor)

**Method.** Conditional logit, α·log M plus the listed terms, fitted inside each of the six folds
(ridge λ = 0.3 on the extra terms, α unpenalised), validated on the fold's quarter, differences pooled
over the 9,912 validation races and bootstrapped by race-day.

| Model (added to α·log M) | Gain vs α-only, nats/race | 95% interval | Folds better |
|---|---|---|---|
| curvature (log M)², (log M)³ | −0.00019 | [−0.00061, +0.00021] | 3/6 |
| α by field size (5–7, 8–10, 11–13, 14+) | −0.00032 | [−0.00092, +0.00026] | 1/6 |
| α by class (maiden, BM, open, stakes) | −0.00004 | [−0.00044, +0.00034] | 3/6 |
| α by state | −0.00021 | [−0.00083, +0.00041] | 2/6 |
| α by metro venue | −0.00010 | [−0.00025, +0.00004] | 2/6 |
| α by distance band | −0.00005 | [−0.00054, +0.00044] | 2/6 |
| book tilt ln(m_sb/m_lb), |tilt| | −0.00015 | [−0.00031, +0.00002] | 1/6 |
| recency-weighted consensus, recent-update flag | −0.00006 | [−0.00015, +0.00002] | 1/6 |
| velocity ln(q_T60/q_T30), |velocity| | −0.00005 | [−0.00017, +0.00007] | 2/6 |
| α by race quote age (≤1 h, 1–4 h, 4–12 h, >12 h) | −0.00003 | [−0.00032, +0.00026] | 3/6 |
| favourite flag and favourite gap (v1 F12 as market-only) | −0.00001 | [−0.00003, +0.00002] | 3/6 |
| α by meetings that day (≤4, 5–7, 8+) | −0.00027 | [−0.00059, +0.00005] | 2/6 |
| α × race overround | −0.00004 | [−0.00013, +0.00005] | 2/6 |
| open→T move (v1 F10) | +0.00007 | [−0.00007, +0.00021] | 4/6 |
| α by start hour | −0.00049 | [−0.00116, +0.00015] | 2/6 |
| top-two-by-M flag | +0.00002 | [−0.00002, +0.00006] | 5/6 |

Forward selection (add only if marginal gain ≥ 0.0002 and interval above 0) selects nothing.

**Descriptive segment αs on all of train** (fitted separately; they do not generalise): field 5–7
1.154, 8–10 1.127, 11–13 1.164, 14+ 1.061; maiden 1.161, BM 1.129, open 1.071, stakes 1.124; NSW
1.174, VIC 1.141, QLD 1.110, SA 1.112, WA 1.076, TAS 1.236, NT 1.136; metro 1.116, non-metro 1.142;
race quote age ≤1 h 1.061, 1–4 h 1.147, 4–12 h 1.121, >12 h 1.165. Fold α ranged 1.114–1.135; all
train 1.135.

**Recommendation.** Round 2's market-only model is P_mkt ∝ M^α with one α, fitted by maximum
likelihood on the fit's training data. All horse-factor evidence below is measured beyond this model.
Every segment table (α by field, class, state, price band) is to be reported as a calibration
diagnostic, never used as a model component, unless a future out-of-fold test shows otherwise.

## 2. Shortlist (five families)

Format follows FACTORS.md: inputs, window, transform, missing rule. Common rules (history on earlier
Melbourne calendar days, global standardisation on the fit's training runners, one missing indicator
per family, no within-race scaling) are as FACTORS.md.

### V1. Carried weight (W)

**Mechanism.** The handicapper's weight is the one piece of form that is designed to neutralise
ability, and the market treats it that way: it prices the rated ability and discounts the kilos. If
weight costs more than the market allows, the top-weighted, highest-rated runners in handicaps are
systematically over-bet and the light-weighted runners under-bet. This is a bias of the whole market,
not of the morning price: the effect is the same against the T−2 market. It should show in handicaps
more than in set-weight races (it does: −0.074 vs −0.036 per SD), should not depend on meeting tier
(metro −0.070, non-metro −0.069) and should be stable across years (2023 −0.062, 2024 −0.075, 2025H1
−0.075). Who leaves it: everyone, including late money.

**Availability audit.** `weight_kg` from `formRaceEntries.weightCarried`, a declared pre-race field;
coverage 100% of train starters, every state, every year (mean 57.0 kg, SD 2.3 kg, stable by year).
Risk: racing.com may update the field after the race for declared overweights (rare, ≤ 1 kg); the
live collector records the pre-race value, so the forward test is clean on semantics. There is no
apprentice-claim field anywhere in the dumps (no "(a)" marker in jockey names; no claim field), so
weight already nets off claims. `handicap_rating` coverage fell from 100% (2023) to 71% (2025) and is
flagged as possibly revised; it is a control, not a feature.

**Formula.**
- `v1_wt` = z(weight_kg), μ and σ on the fit's training runners.
- `v1_wt_chg` = z(weight_kg − last start's weight_kg); missing → 0, indicator `v1_missing` = 1.
- No rating term. Reported with and without `handicap_rating` as a control.

**Rejection condition.** Any of: the `v1_wt` coefficient's fold-wise sign is not negative in ≥ 5 of
6 train folds (it is 5/6 now); the coefficient against the T−2 market on tune1 is less than half of the
T−30 coefficient (would show it is a staleness effect); the live-collected pre-race weights in the
forward window give a coefficient within [−0.01, +0.01] per SD; adding an apprentice-claim field, if
one becomes available, removes the effect.

**Train evidence beyond M^α.** +0.00101 [+0.00044, +0.00158], 5/6 folds; coefficient −0.042 per SD
(fold 6, λ = 0.3), −0.069 unpenalised on all train. Unchanged when `handicap_rating`, `age_at_race_est`,
jockey AE (F13), metro, class group or a set-weights interaction is added. The top-weight flag alone
is worth +0.00006: the effect is linear in kilos, not a top-weight artefact.

### V2. Eye-catcher (ground made at the last start, v1 F2 re-proposed with a mechanism)

**Mechanism.** A runner that came from last to run on at the previous start is visible in the replay
and the comments, and it attracts money ("eye-catcher", "unlucky"). Ground made is partly a tempo
artefact (a fast pace flatters closers) and does not transfer to a differently run race. If the market
over-reacts to it, horses with a large positive `f2_last` are over-bet. The v1 fit found a negative
coefficient, and the effect persists against the T−2 market (−0.023 vs −0.025 per SD): it is a bias,
not staleness. It should be strongest after races with a strong pace (exploratory: interaction with
last-start leader count) and absent for horses whose style is habitually to come from behind (their
ground made is expected and priced).

**Availability audit.** `positionAt800Abv` and finish: 90–91% of entries every year, every state.
F2 inputs exist in the built table (`f2_last`, `f2_avg3`). Missing when no history: ~6%.

**Formula.** As FACTORS.md F2: g = (position at 800 − finish) / field; `v2_last` = z(g at last
start), `v2_avg3` = z(mean over last 3, at least 1); missing → 0 with `v2_missing`. Exploratory add-on
(not primary): `v2_last × z(S)` where S is the runner's own style (F7).

**Rejection condition.** `v2_last` coefficient not negative in ≥ 4 of 6 train folds; or no effect
against the T−2 market on tune1 (|coef| < 0.01); or the effect disappears when `f7_style` is added
(it would then be a style proxy, already visible to the market).

**Train evidence beyond M^α.** Inside the v1 retained block (F2, F3, F13, F18): +0.00025
[−0.00007, +0.00057], 5/6 folds, with `f2_last` carrying the largest weight (−0.022). Alone on all
train: −0.025 per SD, in-sample +0.00019. Weak, but it is the only v1 family whose effect survives the
late market.

### V3. Preparation stage (time since the last run)

**Mechanism.** Morning prices are framed by ratings and bare form, which do not show fitness. Doubts
about a horse resuming or coming off a long gap between runs are expressed by late money (trackwork,
stable confidence), and the T−30 price has not yet absorbed them. This predicts that the effect is
present against the T−30 market, shrinks against T−10 and is absent against T−2. That is exactly the
pattern found (−0.031, −0.020, +0.003 per SD). It is therefore **not a market bias**; it is
information that the T−30 price lacks. It can support claim A (a better T−30 forecast) and a betting
claim only if the T−30 quote is actually taken.

**Availability audit.** `days_since_last_run` from the horse's earlier runs in the dumps: known for
93–95% of entries in 2023–2026 (84% in 2022, truncation). First-up share 19% in every block;
second-up 13%. Runs before 2022-07 are invisible, so a horse first seen in the data looks first-up;
the `debut_ds` flag separates it.

**Formula.**
- `v3_logdsl` = z(ln(max(days_since_last_run, 1))).
- `v3_first_up` = 1 if days_since_last_run ≥ 84 or unknown; `v3_second_up` = 1 if the previous run
  was itself first-up and the gap is < 84 days (`prep_run_no` = 2 from the run-sequence table);
  `v3_debut_ds` = 1 if no earlier run exists in the data.
- Missing rule: `v3_logdsl` → 0 and `v3_missing` = 1 when days_since_last_run is unknown; the flags
  stay 0/1.

**Rejection condition.** Coefficient on `v3_logdsl` not negative in ≥ 4 of 6 folds; or the T−30
effect on tune1 is below 0.01 per SD. A non-zero coefficient against T−2 would not kill the family but
would change its classification to a bias.

**Train evidence beyond M^α.** `log_dsl` alone +0.00029 [+0.00001, +0.00055], 4/6 folds; the six
flags alone +0.00006 [−0.00002, +0.00014]; spell length among first-uppers +0.00011 [−0.00006,
+0.00029]. Marginal in forward selection, after weight, market memory and the v1 block: +0.00028
[+0.00001, +0.00053].

### V4. Market memory at low-attention meetings

**Mechanism.** Where the horse's price today sits relative to its own price last start is the market's
summary of what changed since (class, barrier, rider, the run itself). At metropolitan meetings
enough informed money arrives by T−30 to set that level. At provincial and country meetings the morning
price is set by a framing model and corrected by thin late money, so at T−30 the move away from the
horse's last price is incomplete: horses whose price has shortened relative to last start are still
under-bet (positive coefficient on ln(M_today / SP_last)), and this should be larger off-metro and
should vanish against T−2 (it does: +0.037 → +0.015 per SD). This is a staleness effect, like V3.

**Availability audit.** `ls_sp_p` (margin-free starting-price probability at the last start) is known
for 92–93% of entries from 2023. Starting price is racing.com's "OP" provider price and is unreliable at
some Queensland bush meetings (PROTOCOL.md section 8); for this family that is a reason to also compute
the feature from the last start's `sb_final`/`lb_final` where available and report both. Metro flag:
a fixed venue list (18 slugs; 24–27% of eligible runners per block).

**Formula.**
- `v4_drift` = z(ln M_T30 − ln ls_sp_p); `v4_drift3` = z(ln M_T30 − ln last3_avg_sp_p).
- `v4_drift_nm` = raw(v4_drift) × (1 − metro), formed from the standardised part (a race-level
  quantity enters only inside this interaction, as FACTORS.md requires).
- Missing (no last start with a price) → 0 with `v4_missing` = 1.

**Rejection condition.** The main effect `v4_drift` not positive in ≥ 4 of 6 folds; or the
interaction's marginal gain on tune1 (fit on train) is ≤ 0; or the effect is confined to QLD (SP
artefact). The interaction was one of two segment interactions tried, so its selection carries a
multiple-comparison risk: it must reproduce on tune1 before it is kept.

**Train evidence beyond M^α.** Drift alone +0.00024 [−0.00012, +0.00060], 4/6; drift plus
non-metro interaction +0.00050 [+0.00008, +0.00092], 4/6 (non-metro coefficient +0.026 per SD on
top of +0.011). Marginal after weight: +0.00059 [+0.00014, +0.00102].

### V5. Course experience

**Mechanism.** A prior run at today's venue is known to the market, but at T−30 it is under-used:
course knowledge is one of the factors that late, local money prices ("horses for courses"), and
first-timers at a track are over-bet in the morning market. Prediction: present at T−30, absent at
T−2 (found: +0.036 → +0.007 per SD). This overlaps v1 F17 (`f17_newtrack`), which was retained in v1.

**Availability audit.** `f17_prior_runs_venue` from the dumps; truncation before 2022-07 makes some
experienced horses look new (rate reported by fold, as in v1).

**Formula.** `v5_course` = 1 if prior runs at the venue ≥ 1 (earlier calendar days); `v5_course_won`
= 1 if any of them was a win; both 0/1, no missing (no history = 0, `v5_missing` = 1 if `hist_ok` is
false).

**Rejection condition.** Coefficient on `v5_course` not positive in ≥ 4 of 6 folds; or no gain on
tune1 once V3 is in the model (collinear with experience).

**Train evidence beyond M^α.** +0.00021 [+0.00003, +0.00040], 6/6 folds. Not selected by the
forward rule (marginal +0.00019 after the four selected families, just under the 0.0002 bar).

### Not shortlisted but retained as v1 carry-overs to re-screen

F3 excuse, F13 jockey, F18 barrier cell: in the v1 block they add little beyond F2; re-screened under
round 2's rules, not shortlisted. F7 pace fit, F17 unproven conditions: screened again as controls.

## 3. The market-only "edge" and what the price data can and cannot show

- **Quote age.** Over train races, the oldest quote in U at T−30 is ≤ 15 min in 1.3% of races,
  ≤ 1 h in 4%, 1–4 h in 18%, 4–12 h in 49%, > 12 h in 28%. The T−30 market is a morning market with
  a few updates.
- **Change before the off.** 78% of runners' T−30 quotes change before the scheduled start (both
  books). Only 1.2% are unchanged to the off.
- **Survival.** Measured from raw fluctuations on 9,074 runners of eligible 2023–2025 races: the SB
  quote at T−30 survives ≥ 60 s for 59%, ≥ 5 min for 41%, ≥ 15 min for 24% of runners (LB: 63%,
  47%, 27%). Fresh quotes (≤ 5 min old) survive less (33–38% to 5 min) than stale ones (48–55%).
- **Lead-lag.** 87% of SB changes within 6 h before T have an LB change in the same direction within
  30 min; the median lag is 8 s and 71% are within 60 s. The two series are near-copies, so a
  recency-weighted consensus adds nothing (section 1) and a stale-book strategy has no window.
- **Train claim-B audit** (out of fold). Rule "back if P × max(q_sb, q_lb) − 1 ≥ e, P ≥ 0.04,
  q ≤ 21":

| P | e | Bets | Per 1,000 races | ROI at T−30 quote | at the other book | at the same book's T−10 quote | at SP |
|---|---|---|---|---|---|---|---|
| M^α only | 0.05 | 346 | 35 | +0.23 [+0.07, +0.41] | +0.19 | +0.13 [−0.02, +0.29] | +0.01 [−0.13, +0.16] |
| M^α + selected | 0.08 | 288 | 29 | +0.31 [+0.11, +0.49] | +0.26 | +0.19 [+0.02, +0.36] | +0.04 [−0.13, +0.21] |
| M^α + selected | 0.05 | 351 | 35 | +0.17 [+0.00, +0.33] | +0.13 | +0.07 [−0.08, +0.22] | −0.07 [−0.20, +0.07] |

  Book disagreement is not the driver (median ln(q_max/q_min) 0.027 among bets). The T−30 price is:
  the same bets return nothing at SP. For these bets the longer book's quote was still at or above the
  T−30 level at T−10 in 51% of cases. M^α alone generates a T−30 paper edge because the corrected
  consensus anticipates where late money goes; that is useful for a T−30 forecast and it is exactly the
  part of any claim-B result that is least executable.

## 4. Killed ideas

- Segment α (field size, class, state, metro, distance, quote age, meetings per day, hour, overround), curvature in log M: all null or negative out of fold (section 1).
- Book tilt and separate book weights: null; the books co-move within seconds.
- Recency-weighted consensus and "recently updated" flag: null; no stale-book window exists (median lag 8 s).
- 60→30 min velocity (steam/drift up to T): null (−0.00005); open→T move (F10): +0.00007, interval spans 0, dropped in v1 on tune1.
- Lead-lag stale-quote strategy: not bettable; 71% of cross-book updates arrive within 60 s.
- Gear changes (blinkers first/off/again, tongue tie, gelded, any): −0.00001; and the field's coverage drifts from 8% (2023) to 22% (2025), so "no gear change" and "not recorded" cannot be separated historically.
- Apprentice claims: no field in the dumps; weight already nets off the claim.
- Age: +0.00004 (age_at_race_est only; `horse.age`/`sex` are as-of-collection and unusable).
- Class change (level, drop, rise): +0.00004; distance change: −0.00003.
- Trainer first-up and second-up record × stage: −0.00002 (coefficient +0.014, unstable); the market prices stable reputation.
- Sire first-up record × first-up: +0.00006; sire progeny record at ≥ 1,800 m × first try at ≥ 1,800 m: +0.00003.
- Pedigree on wet tracks: no timestamped pre-T condition exists; final condition is not allowed.
- Horse's own A/E and experience: +0.00014, interval spans 0.
- Trainer at venue (1,095 d): +0.00006; trainer overall (730 d, F14-like): 0.
- Wider stewards' keywords (disappointing, eased, vet): +0.00002.
- Beaten favourite / close loss last start: +0.00005.
- Travel (interstate, venue change): +0.00013 [−0.00001, +0.00027], negative coefficients (travellers over-bet); near miss, not shortlisted; re-screen only.
- First-up × non-metro: +0.00004.
- racing.com `bettingFluctuationsPriceOpen/MoveOne/MoveTwo`: undocumented timing, unverified.
- Same-day form and meeting bias: exploratory by rule (no timestamp proves the result was known at T).
- Top-two flag, hour-of-day α: null.
- Claim C upset rule (v1 form): at every ratio threshold that fires (≥ 1.03 to ≥ 1.10, P ≥ 0.08–0.15) the nominee's paired difference against the best non-favourite is negative (−0.02 to −0.05 with intervals below 0); at ≥ 1.15 it fires 4–12 times per 1,000 races.

## 5. Claims B and C: objectives, minimum counts, selection procedure

**Claim A (log-loss) stays primary.** Train effect +0.00213 with race-day SE 0.00043 over 9,912
races: ~2,300 races exclude zero at 98.33% if the effect holds; v1's effect shrank by half from
train to tune2, so the final block (5,308 races) and a six-month forward window (~3,700 eligible
races at tune1's rate) are adequate only if at least ~0.0014 survives.

**Claim B (betting), proposed as reported, not confirmatory, in round 2.**
- Rule family: back runner i at the recorded bookmaker if P_i × q_i − 1 ≥ e, P_i ≥ 0.04, q_i ≤ 21,
  q_i = max usable quote at T among the books live at T.
- Declared objective for threshold selection on development data: expected log growth at a fixed
  fraction f = 1% of bankroll per bet, G(e) = Σ ln(1 + f·r_i), over tune1 with the model fitted on
  train, e chosen from {0.05, 0.08, 0.12}. Ties and small differences (< 0.1 in G) go to the larger
  e. One look on tune2 (fit train + tune1) checks sign and count projection; e is then frozen.
- Settlement for development and the semi-blind holdout: primary at q(T−30) as recorded; robustness
  at min(q(T−30), q(T−20)) at the same book (T−20 to be added to the dataset build) and at SP.
  Forward: paper bets settled at the live-logged quote of the recorded book at the first observation
  ≥ 60 s after the decision; a quote withdrawn before that is a no-bet, counted.
- Minimum count: 1,000 bets. Power: return SD ≈ 3.3 per bet at these prices, so 1,000 bets give SE
  ≈ 0.10 and detect ROI ≥ +25% at 98.33%. Projected rate 29–35 bets per 1,000 eligible races gives
  ~110 bets in six months. **Therefore claim B is inconclusive by construction in a six-month window.**
  It becomes testable only if the eligible population grows (live quotes remove the feed-liveness
  filter that drops half of all races) and the window is a year or more. Firing more often by lowering
  e is not evidence; it is reported with G, not ROI, as the development objective.

**Claim C (upset), replaced.**
- The v1 rule is withdrawn (section 4). A well-powered replacement is proposed as **claim D, closing
  line**: within each race, regress ln(SP_p / M) on ln(P / P_mkt); statistic = pooled within-race
  slope, race-day bootstrap. Pass if the 98.33% interval lies above 0.2 (half of the train slope);
  fail if it lies below 0. Train: +0.51 [+0.46, +0.56] over 98,767 runners. This tests whether the
  model's deviation from M^α is information the market later agrees with. It is not profit. The
  Betfair study saw outcomes and prices on the final dates, so on the holdout it is semi-blind like
  everything else.
- Secondary, descriptive: paired difference nominee − benchmark in the races where the model's top
  pick differs from the market's (3.7% of races; train +0.065 [−0.003, +0.136]) and where the second
  picks differ (4.7%; +0.028 [−0.022, +0.080]). Minimum 500 differing races to report an interval;
  neither reaches it in a six-month window, so neither is confirmatory.

## 6. Protocol-v2 skeleton

**Dataset and eligibility.**
- Rebuilt from the same dumps with the round-2 fields (`prep_run_no`, `first_in_ds`, quote at T−20,
  venue metro list, last-start bookmaker final prices). Manifest sha256 recorded.
- Pre-decision filters as v1 (Australian, not trial, |U| ≥ 5, two-book market complete, feed live,
  timing trusted, not examined); plus `weight_kg` present for every runner in U.
- Hard rule retained: starting price never fills a missing quote; history on earlier calendar days only.
- Field-availability table by year and state for every round-2 input, with any input whose coverage
  moves by more than 10 points between development years marked "coverage-unstable" and excluded
  from primary families (gear changes are excluded on this rule).

**Folds and development.**
- Screening: the six quarterly folds inside train (2024Q1–2025Q2), α fitted per fold, kept if better
  in ≥ 4 of 6 and the pooled interval excludes 0.
- **tune1 and tune2 are reused development periods**, not held-back or blind data: both have already
  influenced the project (v1 refinement on tune1; the one v1 look at tune2) and cannot regain
  blindness. Round 2 uses them as later development folds: fit on train, evaluate on tune1 (repeated
  looks allowed) for family dropping, λ and threshold selection; then fit on train + tune1 and take
  one look at tune2 as a sign-and-count check of the fixed candidate. Train-only outcome discipline
  (as in this proposal) is kept for the screening stage.
- Model: P ∝ M^α · exp(f(X)), f linear in the shortlisted families, λ from {0.3, 1, 3, 10, 30}, missing
  indicators per family, standardisers on the fit's training runners. Trees exploratory.

**Model fingerprint and pin.**
- `model-v2.json`: α, every coefficient, every standardiser, the frozen e for claim B and the pass
  bands for claims A and D; sha256 of that file, the dataset manifest sha256 and the code commit are
  the fingerprint, recorded in the protocol before the holdout is opened. The commit that adds them
  is tagged `model-v2`; its timestamp starts the forward window.

**Holdout (semi-blind).**
- The final block 2026-05-01 to 2026-09-28 (5,308 eligible races) less examined races is opened once,
  with the pinned model, for claims A and D (and the reported claim B). The Betfair study has seen
  outcomes on those dates: a fail is decisive; a pass is provisional and confirms nothing on its own.
- The excluded month (2026-09-29 to 2026-10-29) and `research/examined.csv` stay out of every test.

**Forward start and the live collector.**
- `tools/live_collector.py` (on `main`) now logs timestamped schedules, four fixed-price books
  (Sportsbet, Ladbrokes, PointsBet, bet365) and scratchings; observations are on the `live` branch.
- Live observations collected **before** protocol v2 and `model-v2` are pinned may be used in
  development (for example to check quote survival and the T−20 proxy against observed quotes). They
  do not count toward the forward test.
- The confirmatory forward window starts at the first race whose decision time is after the
  `model-v2` commit timestamp and runs for a fixed length (proposed: six months for claims A and D;
  claim B reported with the count and declared inconclusive if under 1,000 bets). The forward market
  M is the two-book (SB, LB) margin-free consensus from the live log at the decision time, for
  comparability with history; PointsBet and bet365 are secondary. The decision is logged live; the
  reconstruction from later dumps is run as well and the two are compared as an audit.
- Forward data is the decisive confirmation for every claim. A forward fail is a fail; the window is
  evaluated once, after it closes, with no extension.

**Reporting.** Full inclusion funnel; field availability; the bettability table (quote age, survival,
change-before-off) for every block; claim A by class, state, field size, price band and meeting tier
as diagnostics; the T−2 persistence check for every retained family on tune1 (bias vs staleness).
