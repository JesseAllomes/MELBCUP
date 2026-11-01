# m7 review: what "tune weights" can still mean (Sun 1 Nov 2026)

**Where we are.** The agreed model is the market: a runner's chance is the margin-free consensus of the
fixed-price books, the form model is off, and the blend is not to be re-tuned. m8 spent every holdout:
tune2, the sealed block and the forward month (RERUN.md). Nothing beats the late price; no bet rule is
proven; trifecta loses. The only data nobody has looked at is the live collector's record from 29 Oct
(3 days so far) and Cup day itself.

**So m7's old wording ("tune weights") is dead.** There are no weights to tune and no clean block to tune
them on. What is left, honestly:

1. **The race card's own rules were never tested.** The 4% chance floor, "closest to fair", the $5
   each-way floor, chance-weighted stakes and the 20% race cap were set by judgment on 1 Nov. They can be
   replayed on the archive as *fixed* rules: nothing was fitted, so every block gives a fair read of how
   they do. **Picking the best variant on those blocks would be fitting with no holdout left (overfitting),
   so variants are reported, not chosen.** A rule changes only if the cause of a loss is known and the fix
   was already proven on data it was not fitted on.
2. **The favourite-long-shot correction (price^1.14).** Fitted on 2023-25, proven for calibration on tune2,
   the sealed block and the forward month (RERUN.md). RERUN left switching it on as the owner's call; the
   app still used alpha 1. Applying a frozen, already-proven value is not new tuning. The test is whether it
   helps the card's picks on the blocks it was not fitted on.
3. **T-30 against the last minute** is the one real forward test left, and the owner asked for it. The app's
   check lives in memory on an app that scales to zero, so it needs a token-free worker that replays the
   collector's observations and grades them from racing.com.
4. **Leave alone:** the value BET rule (fires about once per 1,000 races; untestable); the DISCOUNT
   exponents for minor places (no clean outcome data beyond the CUP_TRENDS fit; the offers check already
   brackets them); race cap and stake weighting (risk controls, not edges); the blend (decision stands).
5. **Collector data since 29 Oct:** three days, about 120 races a day, prices only (results fetched from
   racing.com). Enough to prove the tool works, not enough to prove anything about a rule.

**Recommendations (done in Step 2):** replay the fixed card rules on every block (`research/m7/card_rules.py`);
switch alpha to 1.14 only if the replay shows a consistent gain on tune2, final and the forward month;
build `tools/forward_check.py` as the forward test; do not change floors or pick rules on replay evidence;
tell the owner plainly that fixed-odds each-way at 3 places is the worst of the three picks everywhere
(their product choice, not a model knob). Results and what shipped: `research/M7_RESULTS.md`.
