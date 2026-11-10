<!-- drainclamp-build: state; schema=1; generation=210 -->
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
| nba1 | NBA player props first (owner 2026-11-03): token-free collector of player prop and milestone markets (points, rebounds, assists, threes, alt lines like 3+ / 10+ / 20+), plus games, minutes, injuries and results, from every agency we pull; head-to-head/line/totals only as a later add | tools/;azure/function/;tests/ | done | ui6 |
| nba2 | NBA leg model: margin-free consensus per market with a fitted bias correction; tuned on past NBA odds and results (source of free history is the main unknown), frozen, then tested once on unseen games | melbcup/;research/nba/;tests/ | done | nba1 |
| nba3 | Value multis from likely props (owner 2026-11-03): filter legs that are BOTH highly likely (e.g. 75%+) AND priced at or above fair; stack 3 to 10 into same-game and multi-game multis; show chance, payout on $10 and EV; correlation-adjust same-game legs; show only multis with positive EV, else say none today; void rules for players who do not play; owner 2026-11-03: also unders (role players), alt lines/milestone tails, and same-game linked legs via joint box-score simulation | melbcup/bets/;tests/ | done | nba2 |
| nba4 | NBA in AsynymBet: Sport tab beside Racing (Games > Game > Bet / Odds / Result), value multis card, shared agencies, pool and P&L | melbcup/web/;tests/ | done | nba3;ui6 |
| lm1 | Looser markets (owner 2026-11-03, after NBA is live and forward-tested): racing each-way value in small fields (1/4 odds, 3 places, short favourite), tote pools with carryovers/jackpots, Best Tote/top fluc, Betfair place drift; NBA quarter/half markets and first basket (need play-by-play; unders, alt lines and SGM moved into nba3); NBL/NBL1/WNBA/EuroLeague props. Each market backtested and forward-tested before it shows in the app | melbcup/bets/;tools/nba/;research/;tests/ | pending | nba4 |
| arb1 | Sure-thing finder (owner 2026-11-03): scan every agency we read (Odds API 12 AU books + PointsBet/Sportsbet direct + Betfair) for arbitrage (all outcomes covered at a locked profit) and promo lay-offs (agency promo + Betfair lay = locked profit); show stake split per agency and locked $; racing and NBA | melbcup/bets/;melbcup/web/;tests/ | pending | nba1 |
| mkt1 | Market predictability scan (owner 2026-11-03): every market sold in Australia; per market and price band, does the outcome happen more than the margin-free price says, and does it pay at a price we can actually get, stable across halves of history; sources football-data.co.uk (done v1), our racing archive, AusSportsBetting AFL/NRL/NBA/NHL/NFL (needs AU fetch), tennis-data, Odds API forward collection; then multis of the edge bands | tools/markets/;research/markets/ | done |  |
| rp0 | P0 settlement (independent review): legs settled by ESPN event + athlete id maps, America/New_York dates, pending/unresolved/void, immutable quotes, corrections.jsonl, multi_key/latest; forward.jsonl frozen, forward-v2 + reconcile | tools/nba/settle.py;tools/nba/daily.py;melbcup/nba_live.py;tests/ | done | |
| rp1 | Review-pack rebuild merged: melbcup/markets.py Selection, melbcup/ranker.py, /sports hub + /nba redirect, many challenges + wallet.py + promos.py + recorded wagers, fail-safe challenge store | melbcup/;tests/ | done | rp0 |
| cat1 | All-sport PointsBet catalogue: lossless adapter, shards per competition, carry-over on partial runs, Players/All markets views, Function timer 24/7 (owner approved, guard $26) | melbcup/catalogue.py;melbcup/catalogue_view.py;azure/function/;tests/ | done | rp1 |
| dz1 | Best multis across sports (discover.py): exact search per odds range, one leg per game, review D1/D2 fixes + brute-force tests | melbcup/discover.py;tests/test_discover.py | done | cat1 |
| pk1 | NBA picker rebuild per Fable AUDIT.md + independent review (event-aware keys, native-pair de-vig, PB O/U, equivalence, monotone ladders, 2-leg, promo minimums); branch rb2-picker abcf1e97, needs review + owner push approval | melbcup/nba_legs.py;melbcup/ranker.py;melbcup/promos.py;tests/test_nba_picker_audit.py | pending | rp1 |
| ui7 | Bet-now UI via product-ui (compulsory): 3-4 prototypes, owner picks, BUILD only on owner word: automatic home (best multis by when), per-sport bet-now + next games, challenge tab without manual promo/split forms, bonus auto-suggest, honesty labels (dz2) | .grok/product-ui/;melbcup/web/;melbcup/discover.py;tests/ | done | dz1 |
| sh1 | Prospective shadow scoreboard (owner TEST_PROTOCOL.md): freeze A (current) and B (patched) picks before each slate, settle by ESPN ids, paired CI by date, coverage + skips; no money | tools/;melbcup/;tests/ | pending | pk1 |
| eq1 | Market equivalence + best executable price across PB/SB (Over N.5 = N+1+, same settlement rules) | melbcup/;tests/ | pending | pk1 |
| pf1 | Portfolio planner for parallel challenges: maximise P(at least one finishes), shared-leg overlap | melbcup/;tests/ | pending | pk1 |
| ch2 | Challenge list as accordion rows expanding in place (v9-1 behaviour): collapsed row = name, current leg odds, live % at right, bar fill = chance + game-time-left text; instant expand with saved figures, live fetched lazily; collapsed rows poll a tiny live-% summary endpoint | melbcup/web/;melbcup/nba_challenge.py;tests/ | done | ui7 |
| bn1 | Bonus credits automatic leftovers (owner 2026-11-08): recording a bonus bet deducts its stake from that bookmaker's available credit, the remainder stays available | melbcup/wallet.py;melbcup/nba_challenge.py;tests/ | done |  |
| nfl1 | NFL gets the full NBA treatment (owner 2026-11-08): picker with pk1 rules on NFL props/lines (event-aware keys, native-pair de-vig, monotone ladders, dedupe, min 2 legs), best multis/stage picks, ESPN live tracker + live chance per leg, auto settle by ESPN ids (America/New_York dates), challenges scope nfl, NFL tab same sub-tabs/design as NBA | melbcup/;melbcup/web/;tests/ | done | pk1 |
| nfl2 | NFL fully separate from NBA (owner 2026-11-08): each page lists only its own challenges/bets/record-to options; scope fixed per page; stage preview honours chosen start/goal/legs/mode and auto-selects best stages; alerts link to own page; verified live with Playwright | melbcup/web/;melbcup/nba_challenge.py;tests/ | pending | nfl1 |
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
- 2026-11-07T14:09:38+00:00 d95792cc 2026-11-07 ui7 built (Haiku step 1, then Sonnet low per owner): v7-3 home + sport pages + next games (full-game main line) + status/refresh + progress bar/toast + challenge tab cleaned; merged to branch 4d4c00c1, tests pass; awaiting owner deploy approval. pk1 (rb2-picker) still awaiting review/merge.
- 2026-11-07T14:23:40+00:00 4aa76261 2026-11-07 ui7 deployed (owner approved): live /sports Bet now; first compute after deploy ~3 min, pages ~1 s; status endpoint live. Next: pk1 review, then sh1 shadow scoreboard.
- 2026-11-07T21:28:26+00:00 94b106f8 2026-11-07 pk1 reviewed+merged to branch (tests pass, not deployed). ui8 BUILD (owner): every sport NBA-style tabs, v8-2 bottom bar + 1's layout, NBA Multis on new design with fixed picker; Sonnet low building in rb5-tabs.
- 2026-11-07T22:30:48+00:00 6de5b342 2026-11-08 INCIDENT fixed: Function loaded 0 functions from 7 Nov 07:50 UTC (nba_challenge imported melbcup.wallet, missing from flat package) -> no NBA snapshots, catalogue, alerts for ~14h. Fix: flat fallback + wallet.py packaged + package-import test; deployed (owner approved); 6 functions loaded, NBA view + catalogue rotation running 22:30 UTC. Also deployed: ui8 per-sport bottom bar incl. Best multis, game name on hero legs, chip row stays.
- 2026-11-08T00:19:31+00:00 fcdbf672 2026-11-08 challenges fixes deployed (cents, legs per multi, edit challenge, edit placed bet, planner at setup, All Sports ladder picks, record any bet + bonus-if-win, sticky stage pick, 400-char legs). Owner data: ch3/4/6 removed, 4 placed Sportsbet bets rebuilt as ch7-10 (goal $250, 2 stages), wallet c1 redeemed, c2 $10.72 granted; backup challenges/backup-before-rebuild-20261108T0009.json.
- 2026-11-08T02:15:12+00:00 b0045fd2 2026-11-08 merged, awaiting deploy: challenge screen v9-3 + live chance (live_chance.py), racing staged load (field first), racing likely engine + Likely/Multis tabs (v10-3), NBA leg labels with stat + game. Owner 4 challenges rebuilt (ch7-10, 3 stages).
- 2026-11-08T02:50:45+00:00 423d193a 2026-11-08 PRE-COMPACT. Live: Bet now/sports tabs, challenge screen v9-3 + live chance, racing staged load + Likely/Multis tabs, NBA labels, /sports speed fix. Pushed NOT deployed (needs 'approved: deploy web'): multi-game live tracker (label 'Game A: legs; Game B: legs'), discover first-refresh on fresh container. Owner data: challenges ch7-ch14 (A-H) to $250; backups challenges/backup-*.json. TODO: record-bet form multi-game option; All Sports stage planner; sh1 shadow scoreboard; eq1 equivalence; pf1 portfolio planner; racing best-chance vs value verdict choice.
- 2026-11-08T02:58:17+00:00 05e47901 2026-11-08 NEXT BUILD after compact (owner: lowest token use, Sonnet low or cheaper): challenge list = accordion rows expanding IN PLACE (v9-1 behaviour), no new screen; collapsed row: name, live % chance at right, current leg odds, the row bar = chance fill with % at end AND a game-time-left indicator (bar or text, e.g. 'Q3 4:12 · 18 min left'); expand instantly with saved figures, live numbers fetched after expansion (lazy), collapsed rows poll only a tiny live-% summary endpoint. Also pending owner answers: bonus credits auto-leftover vs one-tap split vs both; review r3 (az4) fix/waive/dismiss; deploy approval for multi-game tracker + discover fresh-container fix (pushed).
- 2026-11-08T03:02:46+00:00 7c66fa41 2026-11-08 deployed (owner approved): multi-game tracker + discover fresh-container fix (multis built ~1 min after deploy). Owner decisions: bonus credits = AUTOMATIC LEFTOVERS (recording a bonus bet deducts its stake from that bookmaker's credit, rest stays); review r3 = FIX (collector publishes to Blob only, not the GitHub live branch). Do after compact, lowest tokens: (1) challenge accordion rows per earlier log, (2) bonus auto-leftovers, (3) r3 fix.
- 2026-11-08T03:16:52+00:00 2c4305e9 2026-11-08 OWNER STANDING APPROVAL: 'All deploy functions from this moment forward are approved. Stop asking' -> deploy web/function/job without asking. Merged: r3 Blob-only collector (bcb62892), bonus auto-leftovers (cc239805). Owner: failed bets must show as failed (added to ch2 accordion agent).
- 2026-11-08T03:24:34+00:00 30f247ad 2026-11-08 DEPLOYED (standing approval): function (r3 Blob-only collector) + web (challenge accordion rows w/ live % bar, game time left, failed=red, lazy expand, live.json poll; bonus auto-leftovers). live.json verified 200. Gap: bonus reversal on edit/delete not wired (unuse_leftover exists).
- 2026-11-08T05:20:10+00:00 bcac523e 2026-11-08 DEPLOYED: live chance player-aware (minutes share, fouls, blowout, DNP/ejected; DNP not detectable from ESPN box), pages update in place (liveSwap, no reload/tap), fresh-prices keeps sport/tab, open challenge row now holds next-stage bet/place/results/edit (chv9-more moved into row). Owner wins A/B/C recorded (backup challenges/backup-before-wins-abc-20261108T0432.json); D failed, owner to tap Lost.
- 2026-11-08T06:54:17+00:00 7f81df00 2026-11-08 catalogue was stuck on soccer since 23:31 UTC 7 Nov (Function 55s kill before state save). Fixed+deployed: cursor saved before each sport, build budget 30s, own timer catalogue_run (owner: 'cost is 0' = approval; limits total 26->27, allowed_functions catalogue_run 144/day). Record-bet form: 'staked with a bonus bet' (nbbonus). Owner York R3 SRM $2 bonus @426 recorded (own bet 3), Jet Boost credit used.
- 2026-11-08T10:39:16+00:00 9fcec3c9 2026-11-08 nfl1 DONE+DEPLOYED (web, job, function): nfl_legs (pk1 via nba_legs), nfl_live (ESPN), live_chance NFL (Poisson counts, normal yards, blowout), nfl_settle, challenge scope nfl, NFL tab = NBA sub-tabs. Verified live: NFL best multis render. Approximations: SGM legs independent, props market-only, absent player -> void. Football catalogue fix (unreached comps keep shard) deployed, unverified (owner: stop watching).
- 2026-11-08T12:21:05+00:00 ec6d5a40 2026-11-08 DEPLOYED (web, job, function): NFL page = NBA templates (page_view, challenge accordion, forms stay on sport); NFL player model (nflverse 2018-26, NB/normal per stat, beats naive baseline on 2025 hold-out, blend w=0.25 prior, NBA real-price test chose 0) + NFL same-game CORR (QB yds~catcher yds +0.32 oos). TODO: run tools/nfl/blend_fit.py on blob catalogue/raw/nfl once settled outcomes accrue; refresh data/nfl/means.json weekly (token-free).
- 2026-11-08T23:27:14+00:00 8785d98d 2026-11-08 nfl2 deployed + verified live (Playwright): NFL tabs no NBA names, NFL challenge list own-sport only, new-challenge fixed to NFL, preview honours start/goal/mode (game: best 2 @1.6%, multi: best 3 @1.9% for $10->$250), Stages pre-set; popups fit screen. Not done: chplan when run exists.
- 2026-11-09T06:45:00+00:00 803732be 2026-11-09 FIX deployed: nba_live._event matches on team nicknames (label 'Los Angeles Clippers' vs ESPN 'LA Clippers' -> C stuck 'in play 38%' all afternoon). C now final: Derik Queen 3 ast (Under 2.5) failed, Hachimura hit.
- 2026-11-09T08:05:05+00:00 bd23b266 2026-11-09 NFL: catalogue 8-day window (14 games); game-line legs (Moneyline 2-way, spread, full-game totals) priced from own pair only, verified chance*price 0.85-1.0 on 1,908 live legs + live page (46% @ $2.00). Incident: first agent version paired lines via prop code (85% on $1.20/$2.20 wins) -> pulled within minutes; a bad git revert briefly undid part of NFL/NBA separation on live (restored, verified).
- 2026-11-09T09:31:05+00:00 4e19afbd 2026-11-09 OWNER POLICY (restated): never use head-to-head in automatic picks, any sport (wins less often than priced). Applied: discover.leg_of all sports, NFL legs = props + spreads + full-game totals. Deployed, live NFL page verified (no 'to win').
- 2026-11-10T02:54:48+00:00 c4d7332d 2026-11-10 Owner asked for Fable review (unders kill multis). Pre-check: unders calibrated (52.0 said/53.5 got, -1.5c vs overs -18.5c) but picked at ~58% vs overs ~72%; mixed multis underperform (thin). Fable 5.1 started (5.2 not available) on forward-v2.jsonl -> research/nba/fable_review_2026-11-10.md + tools/nba/review/.
<!-- /DC:LOG -->

## 2026-11-07 sports models shipped
- Merged sport-{racing,nba,afl,nfl,nhl}; all hold-outs: nothing beats the market (racing alpha 1.13 correction is the only real gain, already live).
- Racing picks persist to blob racing/<date>/<venue>/checks.json; graded races log to racing/log/; NBA job refits racing/tuning.json nightly (learn_racing in tools/nba/daily.py).
- /data lists sports/<sport>/ datasets + models. Remove after the owner's independent review.
- Blocked: nrl + tennis (Cloudflare 403 on aussportsbetting / tennis-data.co.uk; owner can download files manually). football: fetch unfinished, worktree sport-football uncommitted.
- func-sports capped to 1 instance (owner approved).
- Not done: NBA nightly learn.py (needs settled forward log); 2-a-night warning; HAIRCUT auto-tune.

## 2026-11-07 independent review P0: event-matched settlement
- Review confirmed: forward.jsonl settled whole-board day logs by player name against one day's box (1,492 later-game legs won/lost, 511 before tip, 6,397 false voids).
- Fix: settle.Slate/settle_one match ESPN game by US date + teams, final only; pending/unresolved/void(DNP). forward.jsonl frozen; forward-v2.jsonl + forward-v2-reconcile.json rebuilt nightly by the job; `latest` flags repeats. Live: 0 future settled, 0 unresolved.
- Rest of the review pack (unified /sports, multi-challenge wallet, bonus splits, promo optimiser) NOT started: needs the full pack (only the handoff + summary were uploaded) and owner go-ahead.

## 2026-11-07 review-pack rebuild (5 Sonnet agents) merged, NOT deployed
- Merged rb-settle (ESPN event/athlete id maps, NY-tz dates, quotes immutable, corrections.jsonl, multi_key/latest), rb-markets (melbcup/markets.py Selection + all NBA markets, no-vig only complete pairs), rb-ranker (melbcup/ranker.py, not wired to UI yet), rb-sportsui (/sports hub, /nba 307 redirect), rb-challenges (many challenges, wallet.py ledger, promos.py, recorded wagers; store challenges/state.json + daily backup; fail-safe on read errors).
- forward-v2 rebuilt with athlete ids and uploaded (0 future settled, 0 unresolved).
- Deploy of web/job/function blocked by classifier: needs owner approval ("approved: deploy web, job and function").
- Next: wire ranker into Multis tab; Discover/Games/Players/Promos sections; etag concurrency on challenge store; US books in markets.py.
