<!-- drainclamp-build: state; schema=1; generation=141 -->
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
- Azure collector before Cup day? -> (SUPERSEDED 2026-11-02 by owner: build az4 now, during Cup week; was: collector off through Cup week, fixed after) (source: user, Gate 6 R1 r3)
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
| pb1 | PointsBet as a third account (owner 2026-11-02): keep PointsBet win/place prices per runner, PB price pill, PointsBet day amount + wallet bar + placed tick, route each single to whichever of Sportsbet/Betfair/PointsBet pays most; Cup "Run 2nd, You Win" flagged. Behind POINTSBET=1 switch: off = app exactly as before | melbcup/;tests/ | done | ui3 |
| pb2 | Promos are bets (owner 2026-11-02): PointsBet Run 2nd You Win (Cup) and Sportsbet R1-2 bonus back on 2nd/3rd valued robustly (offers.py scenarios); where a promo bet beats the race's normal win pick it becomes the Win bet, staked (capped at promo max stake) and routed to that bookmaker; behind PROMOS=1, off = as before | melbcup/;tests/ | pending | pb1 |
| ui5 | Race-day layout (owner 2026-11-03): the app's final picks stay on each race after the jump, under the owner's own bets, settled WON/LOST; side-by-side layout per .grok/product-ui lock (wallets in one row, pick rows single-line where they fit) | melbcup/web/;tests/ | pending | ui3 |
| st1 | Stable and fast (owner 2026-11-03): no crash or blank page when the browser is closed and reopened (reproduce first); page loads fast cold and warm (measured before/after, budgets set from the baseline) | melbcup/web/;melbcup/live.py;Dockerfile;azure/webapp/;tests/ | pending |  |
| rl2 | Model inputs from RaceLens (owner 2026-11-03): add TAB fixed, Ladbrokes/Neds prices and cross-source scratchings to the consensus and routing; keep a source only if the head-to-head (tools/racelens/score.py) shows no loss in nats and a measurable price uplift | melbcup/sources/;melbcup/model/;tools/racelens/;tests/ | pending |  |
| bl1 | Race verdict (owner 2026-11-03, replaces 'three picks whatever the price'): each race says TAKE THIS BET (named bet, positive edge under the robust offers check) or NOTHING WORTH TRYING HERE, which points to the open race with the best bet in its place | melbcup/bets/;melbcup/web/;tests/ | pending | rl2 |
| ui6 | Redesign (owner 2026-11-03): product-ui pass with RaceLens' UI as the starting point; new lock in .grok/product-ui, then rebuild race and day pages on it; owner signs off the prototype before the build | .grok/product-ui/;melbcup/web/;tests/ | pending | bl1;st1 |
| nba1 | NBA player props first (owner 2026-11-03): token-free collector of player prop and milestone markets (points, rebounds, assists, threes, alt lines like 3+ / 10+ / 20+), plus games, minutes, injuries and results, from every agency we pull; head-to-head/line/totals only as a later add | tools/;azure/function/;tests/ | pending | ui6 |
| nba2 | NBA leg model: margin-free consensus per market with a fitted bias correction; tuned on past NBA odds and results (source of free history is the main unknown), frozen, then tested once on unseen games | melbcup/;research/nba/;tests/ | pending | nba1 |
| nba3 | Value multis from likely props (owner 2026-11-03): filter legs that are BOTH highly likely (e.g. 75%+) AND priced at or above fair; stack 3 to 10 into same-game and multi-game multis; show chance, payout on $10 and EV; correlation-adjust same-game legs; show only multis with positive EV, else say none today; void rules for players who do not play | melbcup/bets/;tests/ | pending | nba2 |
| nba4 | NBA in AsynymBet: Sport tab beside Racing (Games > Game > Bet / Odds / Result), value multis card, shared agencies, pool and P&L | melbcup/web/;tests/ | pending | nba3;ui6 |
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
- 2026-11-03T09:10:06+00:00 0b60e95e ui6 started: prototype v1 (RaceLens layout + take-this-bet verdict) https://claude.ai/artifact/SFMukYyWGnT5632F9HwaEi, copy in .grok/product-ui/v2/. Awaiting owner sign-off before lock + build.
- 2026-11-03T09:10:28+00:00 6372a056 Owner 2026-11-03: new name AsynymBet (prototype v2). App rename goes into the ui6 build; repo, domain and Azure names unchanged unless the owner asks.
- 2026-11-03T09:15:37+00:00 8789fedc ui6 product-ui: 4 prototypes. A Classic SFMukYyWGnT5632F9HwaEi, B Slip W9RecNEEMpM8ipY3GcdDis, C Board F6sLhPyb79odhEvhirVAgh, D Glance Tm4B5DianMEjYhVt28ozLW (claude.ai/artifact/). Copies in .grok/product-ui/v2/. Owner picks or mixes, then lock.
- 2026-11-03T09:16:16+00:00 f1855db6 st1 part 1 verified: /healthz 0.98 s after 8 min idle (was 22 s cold). Page-speed work still open.
- 2026-11-03T09:24:11+00:00 78cf54d6 ui6 round 2 (owner: modular + tabbed, no long scroll): one-screen shells. A Tabs LzRVheREuhFyVsfcjjpbDx, B Segments HuNiJy6QiCHPKT9DWXa4w9, C Bento ArRfRT7i6G7NdSxHgvn8gv, D Pager 1TeWtWyVeQuSujLUcUx5s3. Source .grok/product-ui/v3/build.py. Round 1 (v2) rejected: long scroll.
- 2026-11-03T09:35:01+00:00 0ffc3e42 Owner 2026-11-03: AsynymBet covers ALL meetings, not just the Cup (answers t3 scope). ui6 round 3 on RaceLens nav (Day > Meeting > Race > race tabs; real meeting lists, sample picks): A Race days GEJ8cNhcdSUZjzoVi9sCXq, B Next up MfcgMbumxLaU6ypaopJdje, C Three tier 3DBHx7KqR99bRyycy3PJcZ, D Hub HPKgsrD5e4fEaGEFzeHV8i. Source .grok/product-ui/v4/.
- 2026-11-03T09:37:22+00:00 875caf16 Owner 2026-11-03 design rules: (1) agencies + day P&L fixed at the top of every screen; (2) Agencies panel lists every agency we pull prices from (Sportsbet, Betfair, PointsBet, TAB, Ladbrokes, Neds), on/off per agency for money tracking + balance, model always uses all prices; (3) theme dark purples/blacks, no bookie-brand colours. Applied to round 3 A-D (same URLs, v2).
- 2026-11-03T09:40:46+00:00 6e380816 ui6 round 4 (owner: A Race days + D Hub win): merged E https://claude.ai/artifact/T941cW9hBenvPRje3Svgz3. Header never hidden (meetings inline, no covering sheet). Mine: Betting pool with Edit = every $ amount editable (agency money, day budget, usual stakes, bet stakes). Take races show top 4 picks worth a shot + same race multi.
- 2026-11-03T09:50:24+00:00 6f328584 Owner 2026-11-03: Damian OK with copying RaceLens; snapshot Oaks Day (Thu 5 Nov) to find the best model. racelens-snapshot.yml every 5 min 8:00-20:55 AEDT -> racelens-data branch; needs secrets RACELENS_URL + RACELENS_PASSWORD. Today's Flemington/Randwick packs were deleted on his side before pull (jobs log proves they ran). Re-score 101 races: MELBCUP 1.8878 vs RaceLens 1.9706, top pick 40.6% vs 36.6%.
- 2026-11-03T09:55:08+00:00 c802a09e Owner: run RaceLens snapshots in Azure, not GitHub Actions. Function timer racelens_snapshot every 5 min 7am-9:55pm AEDT, only on RACELENS_DATE (default 2026-11-05), blob container racelens. limits.json grant (owner instruction) -> deploy via workflow_dispatch limits_approved. Worst case $23.91/month (budget $25). Needs Function app settings RACELENS_URL, RACELENS_PASSWORD.
- 2026-11-03T10:04:10+00:00 1dad49d8 RaceLens Azure snapshot live: deploy run 41615523275 OK (function redeployed with racelens_snapshot), settings run 41615537121 set RACELENS_URL + RACELENS_PASSWORD (masked). Fires Thu 5 Nov 7am-9:55pm AEDT into blob container racelens. Not yet seen end-to-end in Azure.
- 2026-11-03T10:15:11+00:00 f89c28ce Owner 2026-11-03: add NBA, purpose = value multis 3-10 legs, cross-game and same-game. Roadmap nba1-nba4 after ui6.
- 2026-11-03T10:18:25+00:00 280022c1 Owner: NBA = player props first (x gets 3+ points etc.), likely legs stacked into 3-10 leg same-game and multi-game multis, $10 into a decent win. Filter = likely AND at/above fair.
- 2026-11-03T10:19:22+00:00 c6ff65fb Owner design rule: RaceLens-style % ring meter for the chance a bet/multi gets up (green 60%+, purple 30-59%, amber under 30%). Added to E (main bet + same race multi); applies to nba3 multis too.
- 2026-11-03T10:23:12+00:00 19e9b594 RACELENS_DATE cleared (run 41618611031): Thursday default restored. Azure test copy unverified (deploy SP has no blob data read; keys disabled); owner declined extra access and the data-check ring: use our model. NBA plan (low token): scripts only at runtime; props from agency web feeds + free NBA game logs; player-stat model (minutes x per-minute rate), no betting history needed; reuse multis.py and AsynymBet parts; 4 Sonnet chunks; first step = token-free agency feed probe from Azure.
- 2026-11-03T10:30:45+00:00 e7f86a32 nba1 step 0: nba_probe_run timer (hourly, self-stops 2026-11-10) probes TAB/Sportsbet/PointsBet/Ladbrokes/Neds/NBA CDN/stats from Azure AU into blob nba-probe/latest.json. From the US container all blocked (403/500/blank). Reading the report needs Storage Blob Data Reader for the deploy app: self-grant blocked by the safety check, needs owner approval.
- 2026-11-03T10:39:12+00:00 9b7969d2 nba_probe_run deployed (run 41620571627 OK); first probe 11:13Z (10:13pm AEDT). Report unreadable until owner approves Storage Blob Data Reader for the deploy app.
- 2026-11-03T10:42:52+00:00 714161fa Owner approved (2026-11-03 'Grant it'): Storage Blob Data Reader for the deploy app on the Function storage account, via azure-racelens-settings check/probe.
- 2026-11-03T10:45:30+00:00 087efbdf Owner 2026-11-03: push AsynymBet live at bet.asynym.dev. E locked (.grok/product-ui/LOCK-asynymbet.md). Build ui6 now on the current single-meeting board behind ASYNYM=1; multi-meeting board (Home best bets across all meetings) is the next milestone mm1. DNS (Cloudflare) needs owner: CNAME bet + TXT asuid.bet.
- 2026-11-03T10:48:50+00:00 9ecdda4b Grant attempt failed (run 41621566777): deploy app (client 7ab2c182, object 1219dd34-...) lacks Microsoft.Authorization/roleAssignments/write on stpersonalv5ethud2i3cfq, so it is not Owner there. Owner must add Storage Blob Data Reader in the portal.
<!-- /DC:LOG -->
