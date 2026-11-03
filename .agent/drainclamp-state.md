<!-- drainclamp-build: state; schema=1; generation=160 -->
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
| nba3 | Value multis from likely props (owner 2026-11-03): filter legs that are BOTH highly likely (e.g. 75%+) AND priced at or above fair; stack 3 to 10 into same-game and multi-game multis; show chance, payout on $10 and EV; correlation-adjust same-game legs; show only multis with positive EV, else say none today; void rules for players who do not play; owner 2026-11-03: also unders (role players), alt lines/milestone tails, and same-game linked legs via joint box-score simulation | melbcup/bets/;tests/ | pending | nba2 |
| nba4 | NBA in AsynymBet: Sport tab beside Racing (Games > Game > Bet / Odds / Result), value multis card, shared agencies, pool and P&L | melbcup/web/;tests/ | pending | nba3;ui6 |
| lm1 | Looser markets (owner 2026-11-03, after NBA is live and forward-tested): racing each-way value in small fields (1/4 odds, 3 places, short favourite), tote pools with carryovers/jackpots, Best Tote/top fluc, Betfair place drift; NBA quarter/half markets and first basket (need play-by-play; unders, alt lines and SGM moved into nba3); NBL/NBL1/WNBA/EuroLeague props. Each market backtested and forward-tested before it shows in the app | melbcup/bets/;tools/nba/;research/;tests/ | pending | nba4 |
| arb1 | Sure-thing finder (owner 2026-11-03): scan every agency we read (Odds API 12 AU books + PointsBet/Sportsbet direct + Betfair) for arbitrage (all outcomes covered at a locked profit) and promo lay-offs (agency promo + Betfair lay = locked profit); show stake split per agency and locked $; racing and NBA | melbcup/bets/;melbcup/web/;tests/ | pending | nba1 |
| mkt1 | Market predictability scan (owner 2026-11-03): every market sold in Australia; per market and price band, does the outcome happen more than the margin-free price says, and does it pay at a price we can actually get, stable across halves of history; sources football-data.co.uk (done v1), our racing archive, AusSportsBetting AFL/NRL/NBA/NHL/NFL (needs AU fetch), tennis-data, Odds API forward collection; then multis of the edge bands | tools/markets/;research/markets/ | active |  |
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
- 2026-11-03T10:39:12+00:00 9b7969d2 nba_probe_run deployed (run 41620571627 OK); first probe 11:13Z (10:13pm AEDT). Report unreadable until owner approves Storage Blob Data Reader for the deploy app.
- 2026-11-03T10:42:52+00:00 714161fa Owner approved (2026-11-03 'Grant it'): Storage Blob Data Reader for the deploy app on the Function storage account, via azure-racelens-settings check/probe.
- 2026-11-03T10:45:30+00:00 087efbdf Owner 2026-11-03: push AsynymBet live at bet.asynym.dev. E locked (.grok/product-ui/LOCK-asynymbet.md). Build ui6 now on the current single-meeting board behind ASYNYM=1; multi-meeting board (Home best bets across all meetings) is the next milestone mm1. DNS (Cloudflare) needs owner: CNAME bet + TXT asuid.bet.
- 2026-11-03T10:48:50+00:00 9ecdda4b Grant attempt failed (run 41621566777): deploy app (client 7ab2c182, object 1219dd34-...) lacks Microsoft.Authorization/roleAssignments/write on stpersonalv5ethud2i3cfq, so it is not Owner there. Owner must add Storage Blob Data Reader in the portal.
- 2026-11-03T11:00:29+00:00 83249137 ui6 built (Sonnet) and verified: full pytest + 18 new, ruff clean, golden identical vs origin/main with ASYNYM unset, screenshots OK. Live with ASYNYM=1 in melbcup-web.json (rollback = 0). TAB/Ladbrokes/Neds chips display-only (no per-agency prices yet); /history stays old UI.
- 2026-11-03T11:04:24+00:00 0b36433d AsynymBet live on cup.asynym.dev (/, /meetings, /mine, /race/7 all 200, titles AsynymBet). Pending owner: Cloudflare CNAME bet + TXT asuid.bet; Azure role (A: Owner/UAA on RG for app 7ab2c182, or B: Storage Blob Data Reader).
- 2026-11-03T11:28:09+00:00 003f707b Owner allowed role grants: Storage Blob Data Reader on stpersonalv5ethud2i3cfq granted to deploy app (1219dd34) and owner SP dfe297b5 (8cfbb9d5). Owner SP creds kept only in session scratchpad azure.env (600); owner told to rotate the secret.
- 2026-11-03T11:36:10+00:00 b8c3a91e NBA probe v2 (on demand via admin endpoint): PointsBet mes/v3 featured competition 7176 works with player prop categories (points, rebounds, assists, threes, steals, blocks, turnovers); Sportsbet competition + Events/{id}/Markets work (game markets; player props in another market group, next probe); TAB 403 (WAF), Ladbrokes/Neds 500 (wrong endpoint); NBA CDN OK; stats.nba.com blocked. Backtest plan offered: step 1 free accuracy test on 2 past seasons of box scores.
- 2026-11-03T11:42:53+00:00 9bbc0853 Owner gave The Odds API key (kept only in session scratchpad odds.env, 600; not in repo). 500 free credits/month. AU h2h covers 12 AU books incl. TAB, Ladbrokes, Neds, Sportsbet, PointsBet, Betfair AU, Unibet, Betr (fills our TAB/Entain scrape gap). Player props empty for AU and US 37 h before tip (likely posted near game time; empty calls cost 0). Credits used: 1.
- 2026-11-03T11:50:50+00:00 87532dfb Owner: yes to NBA accuracy backtest. nba_history_run timer (every 15 min, 60 games/run, self-stops 12 Nov) downloads 2024-25 + 2025-26 regular-season box scores from cdn.nba.com into blob nba-history (~10 h). Worst case $24.77 (budget $25). Backtest scoring runs here, token-free.
- 2026-11-03T11:57:03+00:00 8293e3c6 NBA CDN liveData has no past-season box scores (60/60 missing); Azure downloader paused (NBA_HISTORY=0 via ARM app setting). Source switched to ESPN public site API (works from here): tools/nba/espn_history.py pulling 2024-25 + 2025-26 regular seasons (~45 min, token-free); backtest.py reads both formats.
- 2026-11-03T12:15:02+00:00 a922ce75 NBA backtest v1 on check season 2024-25 (6,911 games loaded; 2025-26 sealed): minutes-projected model beats season average and last-10 on all four stats (points log loss 0.347 vs 0.519/0.365; rebounds 0.367; assists 0.324; threes 0.470). Calibration close: 80-89% bucket hit 86/85/85/85%; 90-99% hit 94/94/94/92%. research/nba/backtest_v1_check_2024-25.txt
- 2026-11-03T12:20:24+00:00 49c034b9 NBA v2 (minutes x rate x opponent, missing-teammates, b2b, NB phi, calibration) quick tune (every 40th row): beats v1 on validate 2023-24 and check 2024-25 for all stats; threes biggest gain (check 0.4693 -> 0.4572). Full tune (every 3rd row, half-lives incl. 1.5/2) queued after downloads. Caveat: missing-teammates read from the game box (stand-in for the injury report).
- 2026-11-03T12:28:36+00:00 d6219689 NBA v2 full tune (69k tune rows, 2014-15..2022-23): validate 2023-24 / check 2024-25 log loss v1->v2 points .3336->.3273/.3475->.3409, rebounds .3533->.3484/.3687->.3616, assists .3172->.3106/.3236->.3167, threes .4520->.4428/.4684->.4575. Back-to-back effect ~0. 80-89% bucket hits 84-85%, 90-99% 93-94%. Params tools/nba/model_v2.json. Next levers: starter/role change, usage redistribution, game script (spread), pace, per-player spread, SGM correlation, GBM; rolling validation; 2025-26 sealed.
- 2026-11-03T12:38:55+00:00 5be6da2c Owner: milestone lm1 (looser markets) after NBA live and tested.
- 2026-11-03T12:40:49+00:00 d61ab05f Owner: NBA loose markets now. Unders, alt-line tails, SGM linked legs moved into nba3; quarter/first basket stay lm1. New arb1: arbitrage + promo lay-off (matched betting) finder.
- 2026-11-03T12:50:02+00:00 465b6464 mkt1 v1 football (286 league-seasons, 2012-25): favourites under ~1.50 happen more than margin-free price says (home 1.20-1.35: 78.7% vs 74.1%; away 1.20-1.35: 78.3% vs 73.9%) and paid at the BEST price in both halves (+2 to +6%). Caveats: best price = max across many books (some offshore/exchange), ~40 bands tested so some positives are chance. research/markets/football_scan_v1.txt
- 2026-11-03T12:52:38+00:00 565cd2fd Owner: hold mkt1 except data-pull scripts; finish NBA. nba1: PointsBet prop price collector on Azure (nba_props_run every 20 min 7am-3:40pm AEDT, changed snapshots to blob nba-props); props not posted 37 h before tip, captured when they appear. nba_history timer removed (ESPN replaces it). Worst case $24.27.
- 2026-11-03T12:54:49+00:00 ac4d7204 NBA v3 rolling validation (folds 2021-22, 2022-23, 2023-24; each tuned on earlier seasons): beats v2 in 12/12 fold-stat pairs. Check 2024-25 log loss v1/v2/v3: points .3475/.3409/.3341, rebounds .3687/.3616/.3547, assists .3236/.3167/.3117, threes .4684/.4575/.4538. Role minutes weight g ~0.8, usage share 0.5-1.0, blowout ~0. v3 frozen in tools/nba/model_v3.json. 2025-26 still sealed.
- 2026-11-03T13:00:18+00:00 cbab9663 nba2 live: tools/nba/board.py prices a day's games with v3 through the backtest feature code (build() now takes 'upcoming' fixtures). Dry run 2026-11-04: 14 games, 336 players. Expected line-up = 2 of last 5 games, starters = last game's, ESPN injury Out removed. Current season 00226 pulled (107 games). PointsBet props collector live in Azure (deploy 41639467183). NEXT CHUNK: parse PointsBet prop outcomes (posted game day) -> legs with chance + EV; nba3 multi builder (3-10 legs, likely AND >= fair, cross-game, same-game penalty); nightly ESPN settle + forward log; then Azure board timer + AsynymBet NBA tab.
<!-- /DC:LOG -->
