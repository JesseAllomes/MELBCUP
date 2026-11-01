<!-- drainclamp-build: state; schema=1; generation=88 -->
# DrainClamp state

<!-- DC:ARCH -->
Greenfield (audit: 0 files, stack unknown). Planned layout, Python 3.13 package `melbcup`:
- melbcup/config.py -> env settings (FORMFAV_API_KEY, PUNTERSEDGE_API_KEY, APP_PASSWORD, POLL_SECONDS) -> load_settings()
- melbcup/sources/ -> FormFav + PuntersEdge HTTP clients, TTL cache, credit-aware backoff -> FormFavClient, PuntersEdgeClient
- melbcup/domain.py -> normalised Meeting/Race/Runner/Price dataclasses (both feeds map into these)
- melbcup/model/ -> runner features (form, class, distance, track/going, jockey, trainer, barrier, weight, bias) -> win probabilities blended with market consensus; place probs via Harville/Henery
- melbcup/bets/ -> value (EV) for Win/Place/Each-way; Trifecta + First Four (Harville enumeration); Early/Main Quaddie; cross-race win multis; fractional-Kelly staking
- melbcup/live.py -> background poller refreshing data and recomputing picks
- melbcup/web/ -> FastAPI app, mobile-first HTML, auto-refresh, HTTP Basic password -> uvicorn melbcup.web.app:app
- render.yaml -> Render free-tier deploy
API specs: .agent/api/formfav-openapi.json, .agent/api/pe-openapi.json (both auth header X-API-Key).
Optimisation vectors: PuntersEdge /v1/racing/consensus, /markets, /tote (exotics), /acceptances, /horses/runs overlap FormFav; prefer one call per race per poll; cache form (static on the day), poll only prices.
<!-- /DC:ARCH -->

<!-- DC:DECISIONS -->
Target -> Flemington, Melbourne Cup day Tue 3 Nov 2026, every race on the card (user)
Purpose -> data-driven value picks; best educated decisions, no guarantees (user)
Bet types -> Win, Place, Each-way, Trifecta, Quad, Multi where possible (user)
"Quad" meaning -> Quaddie (Early Quaddie + Main Quaddie); First Four also shown per race (repo decision)
Inputs -> long-form history, horse, jockey, trainer, owner and other relevant data (user)
Data sources -> FormFav Pro (7-day trial covers Cup day) for form/predictions/jockey/trainer/runner stats/track bias + PuntersEdge free key for bookmaker win/place prices incl Sportsbet, tote, consensus (user accepted recommendation)
No Betfair (user has no account); no scraping of racing.com/TAB/Sportsbet (user + terms of use)
Secrets -> env vars FORMFAV_API_KEY, PUNTERSEDGE_API_KEY, APP_PASSWORD only; never in repo or chat (repo decision)
Owner data -> PuntersEdge acceptances carry owner; shown per runner, not weighted (no owner strike-rate feed) (repo decision)
Hosting -> online free tier (Render), password protected, phone-first, works on mobile data (user)
Live -> app refreshes data and re-ranks picks automatically; polling interval respects API credit limits (user + repo decision)
Stakes -> rank picks; optional budget input gives quarter-Kelly stakes with per-bet cap; never places bets (repo decision; user did not choose)
Missing data -> show "no data" and skip the pick; never fabricate prices or probabilities (repo decision)
Stack -> Python 3.13, FastAPI, uvicorn, httpx, jinja2; dev: pytest, ruff (repo decision)
Deadline -> usable by Mon 2 Nov evening AEDT; Cup day fields final Sat 31 Oct (user)
Responsible gambling footer with Gambling Help Online 1800 858 858 on every page (repo decision)
PuntersEdge is required (field, scratchings, prices); FormFav is optional enrichment and every FormFav failure degrades to a visible warning (repo decision)
Market consensus computed locally from /markets (per-book normalise, median) to save credits; /consensus endpoint not used (repo decision)
Test payloads are synthetic but follow the vendor OpenAPI specs in .agent/api/; vendor examples kept in tests/fixtures for shape checks (repo decision)
Exotics: no pre-race tote dividends exist in either feed, so trifecta/first four/quaddie show hit chance + fair dividend; one structure per type is "recommended" (cheapest with hit chance >= threshold) (repo decision)
Quaddie legs -> Main = last 4 races, Early = 4 before; UI tells user to check bookmaker legs (repo decision)
Multis -> Sportsbet win prices only (multis must be with one bookie); legs >= 15% win chance (repo decision)
Staking -> quarter Kelly capped 5%/bet; exotics 1% of budget each (recommended only); total scaled to budget (repo decision)
App password required: without APP_PASSWORD pages answer 503 with setup text (repo decision)
Prices -> /racing/next-to-go (free plan, 2 credits whole card); /racing/markets needs Plus and is not used (repo decision, real-data test)
Credits -> manual mode default: Load card (~2+3/race) and Refresh prices (2) buttons; Auto optional via toggle or PRICE_MODE=auto; credits left shown on every page (user)
Hosting -> Render, deployed by user from main (user)
Model weights (SUPERSEDED, research only) -> fitted by melbcup/backtest.py on 1,131 races 29 Sep-29 Oct 2026 (pre-race RA acceptances + FormFav point-in-time form vs official SP/results); blend market 1.0 + model 0.3; FormFav rating enters as a factor (repo decision, backtest)
VALUE rule -> edge between required_edge(price) and +40%, win price <= $21 (held-out ROI at SP +9.8% over 1,075 bets; not proven) (repo decision, backtest)
Jockey/trainer factors kept: held-out accuracy identical with or without them (repo decision, backtest)
FormFav key now on free plan and over quota until 2026-10-30 08:05Z after backtest collection; client stops calling refused features per load; Pro re-subscription is the user's call (user pending)
- Azure migration? -> already moved by Codex to the owner's personal Azure; this work verifies it and turns it on (source: user, 2026-10-31)
- Azure auth? -> Azure CLI device-code login by the owner, CLI config in session scratch only; no credentials, tokens or secret values in the repo, chat or logs; secret and setting names only (source: user + repo decision)
- Cutover? -> per service: verify, dry run, owner approves, then turn the Azure schedule on and disable the matching GitHub Actions workflow in the same step so nothing runs twice (source: repo decision)
- MELBCUP timing? -> owner had no preference; Render, live-collector.yml and GCS archive keep running through Cup day (Tue 3 Nov) until the Azure copies are verified (source: repo decision)
- Azure collector before Cup day? -> no: review found 3 blockers and the GitHub collector already works; Azure collector off through Cup week, fixed and committed to git after (source: repo decision, 2026-10-31)
- Times shown to the owner? -> Melbourne time (AEDT/AEST) only, never UTC (source: user, 2026-10-31)
- Where does data live? -> Azure Blob in the existing storage account (pennies a month); git keeps code only; OneDrive (owner's 1 TB) only for backups/archives because unattended jobs would need a rotating Microsoft login token (source: user "move everything possible, cheapest" + repo decision, 2026-10-31)
- Site actions? -> no GitHub issues; on-site buttons via SWA API + owner-only login (source: user, 2026-10-31)
- Look? -> Silks: own identity, not a bookie look; per-race silk colour bands, chunky blocks, bold sans; no TAB/bookie green (source: user, 2026-10-31)
- BET without $? -> never: every BET carries a $ stake; budget defaults to $200, remembered on the phone; a bet that sizes to $0 is HOLD (source: user, 2026-10-31)
- Push to main? -> only after the owner approves each push; main deploys live (source: user, 2026-10-31)
- UI changes? -> owner's product-ui skill (/home/user/jesseallomes/product-ui): 3-4 prototypes per round, wait, iterate; no production UI until owner says BUILD; then write .grok/product-ui/{theme,design,layout}.md (source: user, 2026-10-31)
- Agreed model (supersedes the blend) -> a runner's chance is the margin-free consensus of the fixed-price books (Sportsbet, Ladbrokes, PointsBet, bet365); the form model is off once prices exist (research/RESULTS.md: no factor beats the market). BET = Sportsbet price above that fair chance by the edge rule, best price close to the jump (late market already in the consensus); each-way only at 4 places 1/4 odds; exotics: top-four box only when it lands often enough. 'Most likely' = favourite by design. Do not re-propose tuning (source: owner, research/, tools/cup_signals.py, melbcup/model/probability.py)
- Where the edge is -> not narrower picks (rerun + venues: nothing beats the late price; mining spent data finds luck); bookmaker offers: 1/4 odds 4+ places each-way (place half +EV in big fields), money-back/bonus promos, boosts. Build an offers check (source: owner + research/v2/CUP_TRENDS_2.md, research/VENUES.md, 2026-10-31)
<!-- /DC:DECISIONS -->

<!-- DC:ROADMAP -->
| id | goal | files | status | deps |
|---|---|---|---|---|
| m1 | scaffold package, settings, test + lint harness | pyproject.toml;melbcup/__init__.py;melbcup/config.py;tests/test_config.py | done | |
| m2 | FormFav + PuntersEdge clients normalised into domain models with caching | melbcup/domain.py;melbcup/sources/__init__.py;melbcup/sources/http.py;melbcup/sources/formfav.py;melbcup/sources/puntersedge.py;tests/test_sources.py;tests/fixtures | done | m1 |
| m3 | runner rating + win/place probability model blended with market | melbcup/model/__init__.py;melbcup/model/features.py;melbcup/model/probability.py;tests/test_model.py | done | m2 |
| m4 | bet engine: win/place/each-way value, trifecta, first four, quaddies, multis, staking | melbcup/bets/__init__.py;melbcup/bets/singles.py;melbcup/bets/exotics.py;melbcup/bets/multis.py;melbcup/bets/staking.py;tests/test_bets.py | done | m3 |
| m5 | live web app: poller, mobile pages, password | melbcup/live.py;melbcup/web/__init__.py;melbcup/web/app.py;melbcup/web/templates;melbcup/web/static;tests/test_web.py | done | m4 |
| m6 | Render deploy config and setup guide | render.yaml;README.md | done | m5 |
| m7 | live-key dry run on real Cup day fields; tune weights -> reframed (research/M7_REVIEW.md): card rules replayed on the archive, favourite-long-shot correction 1.14 applied, forward test tool; no other tuning possible (holdouts spent) | melbcup/model/probability.py;melbcup/bets/offers.py;tools/forward_check.py;research/m7/;research/M7_REVIEW.md;research/M7_RESULTS.md | done | m6 |
| az1 | Azure inventory and verification for MELBCUP: web app (replaces Render), live collector, archive storage (replaces GCS) mapped and checked against main for code version, start command, health check, settings and secret names; no changes | .agent/azure-inventory.md | done |  |
| az2 | Azure dry runs for MELBCUP: app /healthz and password check, one collector run writing to Azure storage, archive compared with GCS | .agent/azure-inventory.md | done | az1 |
| az3 | MELBCUP cutover: owner-approved Azure on, Render, live-collector.yml and archive-to-gcs.yml off, after Cup day unless the owner says otherwise | render.yaml;.github/workflows/;.agent/azure-inventory.md | done | az2 |
| az4 | After Cup collection (7 Nov): collector publishes to Blob only (no live branch); validators read blob; Google Cloud archive replaced by Blob cool tier or OneDrive; archive-to-gcs.yml, GCP key, Render and GitHub Pages retired | azure/function/;tools/live_validate.py;.github/workflows/ | pending | az3 |
| ui2 | every BET has a $ (default budget $200, remembered; zero stake -> HOLD; race/summary chips summed $); logic only, no restyle | melbcup/web/;tests/test_verdicts.py;docs/ | done |  |
| ui3 | Race card BUILD (owner BUILD 2026-11-01): product lock in .grok/product-ui; wallet bars + placed ticks (cookie), Sportsbet/Betfair day amounts, allocation by chance with routing, SB/BF price pills, Good/Short price pills, per-race exotics incl quinella/trifecta stakes, last-minute check (T-30 vs last check, graded), day page without quaddie block | melbcup/web/;melbcup/bets/allocate.py;melbcup/live.py;tests/ | done | ui2 |
| ui4 | 'Multi picks for the day': 5 best-chance cross-race multis (Sportsbet win, 2-3 legs) with \$ stake, price, chance; engine + view, layout per ui3 lock | melbcup/bets/multis.py;melbcup/web/;tests/ | pending | ui3 |
| m8 | Full rerun (owner: ALL stats and odds): every factor family + price moves + cross-book spread, fitted jointly with the T consensus, no leakage; every bet type (win, place, each-way, quinella, exacta, trifecta, first four, multis) tuned on dev blocks, rule frozen, tested once on an unseen block at takeable prices; per-type verdict | research/late_money/;research/RERUN.md | done |  |
| m9 | Offers check (owner: as robust as mathematically possible): EV of bookmaker offers (each-way extra places, money back as bonus if 2nd/3rd, odds boost) from finishing-position chances; BET only when EV is positive under every plausible chance model; robust fractional-Kelly stake; JSON endpoint now, page after ui3 lock | melbcup/bets/offers.py;melbcup/web/app.py;tests/test_offers.py | done | m8 |
| bf1 | Betfair read-only prices: login from Key Vault, delayed key fetched/created, win+place back prices each check; singles at better of Sportsbet and Betfair after 8% commission | melbcup/sources/betfair.py;melbcup/live.py;melbcup/bets/singles.py;tests/test_betfair.py | done |  |
| bf2 | Betfair betting: manual Place and Auto (last minute before the jump, app BET win/place/each-way lines rechecked at latest Betfair price, own daily limit); PIN from Key Vault on every betting action; practice mode until the live app key; exotics listed for manual Sportsbet entry (no tote on Betfair) | melbcup/autobet.py;melbcup/sources/betfair.py;melbcup/web/;tests/test_autobet.py | pending | bf1 |
<!-- /DC:ROADMAP -->

<!-- DC:VERIFY -->
```json
[
  {"id": "ruff", "argv": ["ruff", "check", "melbcup", "tests"], "cwd": ".", "tier": "fast"},
  {"id": "pytest", "argv": ["pytest"], "cwd": ".", "tier": "milestone"},
  {"id": "ruff-final", "argv": ["ruff", "check", "."], "cwd": ".", "tier": "final"},
  {"id": "pytest-final", "argv": ["pytest"], "cwd": ".", "tier": "final"}
]
```
<!-- /DC:VERIFY -->

<!-- DC:LOG -->
- 2026-10-31T23:57:11+00:00 f34a851b owner: finish, token budget spent. ui3 design round 2 stopped (pending); trifecta question unanswered, left as is; open: ui3, ui4 multi picks, m7, az4 (after 7 Nov)
- 2026-11-01T04:14:26+00:00 ec15b83b owner: race card hard to follow -> one prototype (artifact RuFZKwqFknJwC5jKEQwZWc: bets first, plain First Four legs, field below, odds-only folded). Trifecta now odds only, never BET (owner 2026-11-01); tests pass; session branch only, main push awaits approval
- 2026-11-01T05:21:26+00:00 ad427a89 owner bets only on Sportsbet: win/place/each-way now judged, ranked and staked at Sportsbet prices (was best price across bookies); no Sportsbet price = no bet. Race card prototype v4 ranks bets + best way per horse. Session branch only; main push awaits approval
- 2026-11-01T05:59:07+00:00 bd4afe2f owner HAS a Betfair account (supersedes 'no Betfair account'); Key Vault: betfair-username, betfair-password (no app key). Built read-only Betfair prices: app logs in, fetches/creates the free delayed key, reads win+place back prices each price check; singles judged at better of Sportsbet and Betfair after 8% commission; page shows Betfair status. Unverified live: login from here is geo-blocked (403). Session branch only; main push awaits approval
- 2026-11-01T06:05:49+00:00 ecc03ecc bf2 backend built (practice mode): melbcup/autobet.py (PIN from Key Vault melbcup-bet-pin, 5 misses = 15 min lock; auto off after restart; own daily limit = max(app record, Betfair record); last 60 s before jump; Betfair-only recheck; $5 Betfair minimum, smaller skipped; each way = two bets), Betfair placeOrders/staked_today, /api/betting endpoints; 8 tests. Auto panel added to prototype (UI awaits BUILD). Owner chose exotics too: impossible on Betfair (tote), listed for manual Sportsbet. Blockers: owner adds melbcup-bet-pin to Key Vault before main push; live key application; app scales to zero so auto runs only while awake
- 2026-11-01T06:07:17+00:00 cd23a376 owner: auto is per race. Switched on per race with that race's own limit (PIN), runs once in the last minute, then done; Betfair tag melbcup-auto<race> so each race's spend counts Betfair's record; no day-wide auto. Tests updated, suite passes
- 2026-11-01T06:21:51+00:00 190fd86c owner: no Betfair live key (A$590 fee). Option 1: free delayed key for prices; auto stays practice and tells the owner what to bet in the last minute; owner places bets by hand. Owner approved push to main of trifecta odds-only, owner-accounts pricing, Betfair prices, practice auto per race. PIN in Key Vault (melbcup-bet-pin)
- 2026-11-01T06:31:46+00:00 20f791e9 live: Betfair login OK, getDeveloperAppKeys refused placeholder app key (INVALID_APP_KEY); fix c2fd2bd1 (no X-Application on key calls) pushed to main with owner approval. Owner: confused by BET vs For fun; wants a $ from the day budget on every card; wants Sportsbet and Betfair prices as different coloured squares on each line (prototype)
- 2026-11-01T06:39:46+00:00 c3e17e4e Betfair live OK after fix (Betfair prices on site). Owner: day budget shared across the whole day by chance each bet pays, value BETs keep model stake, exotics keep outlay, max 20% of budget per race; every race gets win/place/each-way picks with $. Built melbcup/bets/allocate.py + 5 tests (not wired to pages: UI awaits BUILD). Live Cup-day run: $200 used, Cup $18. Prototype v10: SB navy / BF amber price pills (owner asked for pills), Good/Short price pills, stakes
- 2026-11-01T06:41:01+00:00 94aa7deb owner: practice auto/PIN pointless without live key; wants to see if last-minute rechecks would change/improve own bets. Plan: drop Auto card/PIN from UI (autobet backend stays dormant); Last-minute check card: save picks+stakes at T-30, again at last check before jump, show changes, after result show returns of both; running total on History. Prototype v11 has the card (3 example states). Build after BUILD
- 2026-11-01T06:42:13+00:00 ae50d0ec owner: separate day amounts for Sportsbet and Betfair (Betfair holds $50). allocate_accounts: share both together, route to the better-paying account; Betfair only if stake >= $5 (EW >= $10) and Betfair money left, biggest price gain first; exotics Sportsbet; reshare so neither account goes over. 2 tests. Prototype v12 has the two amounts
- 2026-11-01T06:45:33+00:00 0658b905 owner: two sticky bars at the very top (Sportsbet, Betfair: limit, left); each bet has 'Placed on Sportsbet/Betfair' tick that confirms and takes the stake off that account; exotics Sportsbet only. Plan for build: ticks kept in a cookie on the owner's phone (no login), placed stakes lock, remaining money reshared over unplaced bets. Last-minute check moved to bottom. Prototype v14
- 2026-11-01T06:51:21+00:00 53aa297d owner: quinella + trifecta back on each race card with a stake from the day budget (by chance, likeliest structure) and advice 'worth a try only if the tote estimate is over the fair dividend' (combos/prob); still never a value BET; Sportsbet only. Exotics per race (First Four on its race, quaddie on its first race, legs noted on later races); day page loses quaddie/multi block. allocate.py + test; prototype v17
- 2026-11-01T08:21:03+00:00 94b53960 ui3 BUILD built on session branch ccr-63b3240a-qdwy3g (51ab72cc, 0d1c6a3f): wallet bars, SB $150/BF $50 cookies, placed ticks cookie, allocate_accounts(placed), SB/BF pills, Good/Short price, per-race exotics, day list, last-minute check (in memory) + History total; 438 tests pass; main push awaits owner
- 2026-11-01T08:43:56+00:00 0819df81 owner: Deploy. ui3 race card build (51ab72cc..39919ca2, 438 tests) pushed to main with owner approval; verifying live
- 2026-11-01T09:29:32+00:00 859d4892 live check: race card live, Betfair pills on every line; only $163/$200 used (Betfair-better stakes under $5). Owner: yes, raise them to $5 on Betfair while Betfair money lasts. route() lifts; test added; suite passes; awaiting push approval
- 2026-11-01T09:37:37+00:00 6ce3d0f0 c83b388f live (owner approved): day $194/$200 in bets; Cup win/place/EW all on Betfair ($5/$5/$10), returns after commission. ui3 done pending owner feedback
- 2026-11-01T09:48:29+00:00 38a65a70 owner: all good ($6 leftover kept as spare). ui3 done. Open: ui4 multi picks, m7, bf2 (betting backend dormant, no live key), az4 after 7 Nov
- 2026-11-01T10:45:05+00:00 87d1aada m7 review (research/M7_REVIEW.md): 'tune weights' is dead (market model, holdouts spent); honest work = replay the card's fixed rules on the archive, apply the already-proven price^1.14 correction if it helps on blocks it was not fitted on, build a token-free forward test; variants reported, never chosen (overfitting)
- 2026-11-01T10:45:06+00:00 265c5294 m7 done. Replay (research/m7/card_rules.py, 28,721 races): card win pick at alpha 1 loses -17/-21/-22/-21% (dev/tune2/final/fwd), worse than the favourite, because 'closest to fair' lands on 2-21 shots (A/E 0.75); at alpha 1.14 -13/-13/-13.5/-11 (4-10 pts better on every block, 3 of them unseen by the fit). Shipped MARKET_ALPHA 1.14 in probability.py (+offers scenarios, cup_signals), tools/forward_check.py (T-30 v last price from collector obs, graded from racing.com; 31 Oct sample 121 races saved). Rejected: floors, pick rule, stake weighting, value rule (fitted noise/untestable). Owner call: fixed-odds EW at 3 places is the worst pick everywhere (-18..-24%). Tests green; session branch only, main push awaits owner
<!-- /DC:LOG -->
