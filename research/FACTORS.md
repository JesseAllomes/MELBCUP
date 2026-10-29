# Correction families f(X): executable definitions (v1, frozen with `protocol-v1`)

**Common rules** (PROTOCOL.md section 3):

- **History.** "History" means the runner's own **earlier** runs on **earlier calendar days**
  (Australia/Melbourne), Australian non-trial races only, newest first.
- **Previous-run fields.** "Last start" means history[0]; "last 3" means history[0..2]. Only
  whitelisted fields are used.
- **Transformations.**
  - Continuous: the feature is standardised **globally**, as z = (x − μ) / σ, with μ and σ
    fitted on the training runners of the fit in question (each fold; all train for tune and
    final).
  - Flags: stay 0/1.
  - Products: built from standardised parts as written below.
  - There is **no** within-race scaling. The conditional logit ignores race-level constants on
    its own, and per-race scaling would erase magnitudes.
- **Race-level quantities.** A value identical for every runner in a race can enter only inside
  an interaction with a runner-varying feature, never alone.
- **Missing values.** A value that cannot be computed is set to the fold-train mean (z = 0), and
  the family's missing indicator is set to 1.
- **Expected wins.** E for a past runner is its margin-free starting-price probability in that race.
  A/E figures are shrunk as AE_k = (W + k) / (E + k), where W is wins and E is the sum of
  expected wins over the window.
- **Windows.** Counted in days before the current race's date. Only completed earlier-day races
  count.

**Primary families (screened under section 5)**

**F1 Closing sectional**

- For a past race, the runner's last-600 rank among that race's finishers with a last-600 m time
  (1 = fastest), scaled to s = 1 − (rank − 1) / (n − 1). The time is the runner's own last-600 m
  split from racing.com's timing sections (`res_last600_s`). `timeSectional` is a race-level value
  and is not used.
- n ≥ 4 finishers with sectionals is required; otherwise the run is missing.
- Features:
  - `f1_last`: s at last start.
  - `f1_avg3`: mean s over last 3 (at least 1 run with s).
  - `f1_gap`: s at last start minus (1 − (finish − 1)/(field − 1)), i.e. closing speed better
    than its finish.

**F2 Ground made**

- For a past race, g = (position at 800 − finish) / field size, using `positionAt800Abv`.
- Features: `f2_last`, and `f2_avg3` (at least 1 run with g).

**F3 Excuse (last start's stewards' comment)**

Case-insensitive regular expressions on `commentStewards`:

| Flag | Pattern |
|---|---|
| `slow` | `slow(ly)?\s+(to\s+begin\|away)\|began\s+(awkwardly\|slowly\|poorly)\|dwelt\|missed\s+the\s+start` |
| `held` | `held\s+up\|(unable\s+to\|could\s+not\|did\s+not)\s+(obtain\|get)\s+(clear\s+)?(running\|a\s+run)\|denied\s+(clear\s+)?(running\|a\s+run)\|blocked` |
| `checked` | `checked\|crowded\|bumped\|hampered\|tightened\|squeezed\|inconvenienced\|shifted\s+(in\|out)\s+(abruptly\|sharply)` |
| `wide` | `wide\s+(throughout\|without\s+cover\|and\s+without\s+cover)\|caught\s+wide\|(three\|four\|five)\s+wide` |
| `keen` | `over-?rac(ed\|ing)\|raced\s+(keenly\|ungenerously\|fiercely)\|pulled\s+hard\|hung\s+(in\|out)` |

Features:

- `f3_any`: any flag at last start.
- `f3_count3`: number of runs in the last 3 with any flag.
- Missing only if there is no history (an empty comment means no flag).

**F4 Bad sign (last start)**

- Pattern: `bled\|bleed\|blood\|lame\|cardiac\|irregular\s+heart\|arrhythm\|pulled\s+up\|eased\s+(down\|out\|right\s+down)\|vet(erinary)?\s+(examination\|inspection)\|distressed\|respiratory`.
- Feature: `f4_bad`, last start only.

**F5 Distance travelled**

- For a past race, t = `distanceTravelled` − race distance (metres), where present.
- Feature: `f5_avg3`, the mean of t over last 3 (at least 1). Lower means covered less extra ground.

**F6 Top speed**

- For a past race, v = `topSpeed` / median `topSpeed` of that race (at least 4 values).
- Features: `f6_last`, `f6_avg3`.

**F7 Run style vs pace**

- A runner's style S is the mean over its last 5 runs of
  (numeric `positionAtSettledAbv` − 1) / (field − 1). At least 2 runs are required, else missing.
- The race's pace count L is the number of runners in U with S ≤ 0.25 (known style only).
  L is race-level, so it is **not** a feature on its own.
- Features:
  - `f7_style` = z(S), with μ_S and σ_S fitted on training runners;
  - `f7_fit` = z(S) × z_L, where z_L = (L − μ_L) / σ_L, with μ_L and σ_L fitted on the
    training races. The product is not re-standardised, so a pace of 1 and a pace of 3 leaders
    give different values.

**F10 Market move**

- For each bookmaker, open is its first fluctuation for the runner. Move is
  ln(open price / quote at T).
- Feature: `f10_move`, the mean of the available books' moves (at least 1).

**F11 Bookmaker disagreement**

- Features: `f11_sb_lb` = ln(m_sb,i / m_lb,i); `f11_abs` = its absolute value.

**F12 Favourite strength**

- Applies only to favourites (zero for others).
- Let G = M_fav − M of the highest non-favourite (race-level).
- Features:
  - `f12_fav` = fav (0/1), so the gap and move terms are not confounded with favourite identity;
  - `f12_gap` = fav × (G − μ_G) / σ_G, with μ_G and σ_G fitted on training favourites;
  - `f12_move` = fav × (raw f10_move − μ_m) / σ_m, with μ_m and σ_m fitted on training
    favourites.
- Magnitudes are preserved: a gap of 0.01 and a gap of 0.30 give different values.

**F13 Jockey**

- For a jockey code, AE20 over the 365 days before **today's** race (both jockeys are evaluated
  as of today).
- Features: `f13_jockey` = AE20 of today's jockey; `f13_change` = AE20 of today's jockey minus
  AE20 of last start's jockey.
- A jockey with fewer than 10 rides in the window counts as missing.

**F14 Stable form**

- Trainer AE5 over the prior 14 days, and AE20 over the prior 365 days.
- Features: `f14_14d`, `f14_365d`.
- Fewer than 3 runners in the 14-day window makes `f14_14d` missing.

**F15 Jockey × trainer**

- Pair AE10 over the prior 730 days.
- Feature: `f15_pair` (fewer than 5 rides makes it missing).

**F16 Rating change**

- `f16_dr` = today's `handicapRating` minus last start's (missing if either is absent).
- Reported with and without this family (revision risk).

**F17 Unproven conditions**

- Distance band: nearest 200 m. Track: venue name.
- Features:
  - `f17_newdist`: no prior run in today's distance band;
  - `f17_newtrack`: no prior run at this venue.
- Horses whose earlier racing predates the data (before 2022-07) look unraced. Missing and
  "new" rates are reported by fold, as a truncation check.

**F18 Barrier cell**

- Cell = (venue, distance band, barrier group {1–3, 4–6, 7–9, 10+}).
- A/E over the prior 1,095 days, shrunk AE20.
- Feature: `f18_cell` (fewer than 30 runners in the cell makes it missing).

**Exploratory only (never primary in this protocol)**

- Wet-track features: `newwet` (first time on a wet track) and the sire's wet record. No
  timestamped pre-T track condition exists in the data, and today's final condition is not
  allowed.

- `sameday_*`: same-meeting bias, and connections' form earlier the same day.
- Track condition or rail change during the day (needs timestamped observations).
- False favourite and favourite exposed composites.
- Any tree-based model.
