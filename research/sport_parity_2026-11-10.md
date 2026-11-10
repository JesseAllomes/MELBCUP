# Sport parity audit, 2026-11-10 (reference: NBA)

Method: code grep (views.py dispatch, sports_hub, discover, nba_legs/nfl_legs, nba_live/nfl_live, settle) plus one Playwright pass at 400x900 over /sports?sport=X&tab=T (chips found live: home, nba, racing, afl, nrl, nfl, nhl, football, tennis, nbl, ncaab, ncaaf, aflw, rugby-league, cricket, mlb, rugby-union, other, all). The browser pass covered home through aflw before it was cut; rugby-league, cricket, mlb, rugby-union and other were NOT sampled live and are inferred from the shared generic code path (same template and `discover` branch as AFL..AFLW). No page errors (pageerror = 0) and HTTP 200 on every page sampled.

Architecture finding: only NBA and NFL run the full NBA page (nba.html via _nba_view). Every other sport runs one generic path: discover.py bands + catalogue rows (sports.html bet_now/next_games/cover). So "other sports" are identical to each other, and differ from NBA in the same ways.

Legend: Y = same as NBA, N = missing, P = partial. Generic = AFL, NRL, NHL, Football, Tennis, NBL, NCAAB, NCAAF, AFLW, Rugby league, Cricket, MLB, Rugby union, Other.

| Function | NBA | NFL | Generic (14 sports) | Home | Note on N/P |
|---|---|---|---|---|---|
| Sub-tabs Multis/Challenge/Games/SGM/All + same bottom bar | Y | Y | Y | Y | bar is 5 tabs everywhere (live) |
| Multis cards: ring, price, legs w/ stat+game, Melbourne time | Y | Y | P | P | generic uses band cards (leg label + game + time, no stat column, no per-leg chance bars "why4") |
| Multis present now | Y | Y | P | Y | live: AFL, NRL, NBL, NCAAF, AFLW "No multi fits right now"; NHL, Football, Tennis, NCAAB show 2 cards (tennis/football are h2h-heavy but h2h is excluded) |
| Honest labels | Y | Y | Y | Y | sgm and no-feed empty states say so |
| Player-prop legs used | Y | Y | P | P | generic takes any catalogue row (props only "where offered"); no per-player stat model |
| Game lines used | Y | Y | P | Y | NFL: line+total via nfl_legs; generic: any non-h2h family from catalogue; NBA: legs.py lines |
| H2H excluded from picks | Y | Y | Y | Y | discover.leg_of drops h2h; nfl_legs GAME_FAMILIES has none |
| Stats model (own player-stat means/blend) | Y | Y | N | N | model only in tools/nba, tools/nfl; AFL/NHL have tools/sports/* builds but not wired to picks. Generic chance = market_prob only |
| Market blend | Y | Y | N | N | generic = devigged market only |
| Same-game correlation model | Y | Y | N | N | SGM tab says "needs a measured correlation model, NBA only" (NFL has pk1 same_game) |
| Picker v1/v2 switch | Y | Y | N | N | nba_legs.picker() used only by NBA/NFL (pk1); discover has no v1/v2 |
| Challenge tab: accordion rows | Y | Y | Y | Y | generic live: 3 details elems, 1 card |
| Live % bar on challenge row | Y | P | N | N | challenges_live() tracks via nba_live.track only; generic live shows no tracker (track=0) |
| Edit / New popups | Y | Y | Y | Y | form present on all |
| Own-sport-only challenge list | Y | Y | N | N | _sport_challenge scopes ("all",) for generic; no per-sport scope exists besides nba/nfl, so New creates an "All Sports" challenge only |
| Best stages preview honours start/goal/legs/mode | Y | Y | P | Y | generic uses _stage_pick(discover.pick_for) which takes x and legs; "mode" and start-kept not verified live |
| Next-stage bet in open row | Y | Y | P | Y | generic ch_sug exists; frozen "shown_sug" shares engine; empty when no multi in the x range |
| Record a bet form present | Y | Y | Y | Y | live: nb-rec on multis and sgm tabs for all; absent on challenge/games/all for generic (and NBA all) |
| Bet's sport saved | Y | Y | N | N | views.py:441 saves sport only when query sport in (nba, nfl); any other sport saves nothing, so bet_sport() falls back to nba |
| Bonus tick | Y | Y | Y | Y | nbbonus input present everywhere the form is |
| Add-to-challenge filtered to the sport | Y | Y | N | N | generic lists every challenge (5 options live) vs NBA 3 / NFL 2 |
| Your bets list filtered to the sport | Y | Y | N | N | no "Your bets" block anywhere on generic pages (live: False); NBA page header shows it only in nba.html (live text check missed it, code shows nba.html:52) |
| Live tracking during games (tracker) | Y | Y | N | N | nba_live routes only NBA/NFL (nfl_live.is_nfl); no tracker for any other sport |
| Live chance | Y | Y | N | N | live_chance has nba + nfl branches only |
| Auto settlement of legs | Y | Y | N | N | tools/nba/settle.py, melbcup/nfl_settle.py only; nothing for AFL/NRL/NHL/football/etc |
| Alerts go to own sport | Y | Y | N | N | push_store default url "/nba?tab=challenge"; views.py:698 only switches NFL; others would deep-link to NBA |
| Page loads without errors | Y | Y | Y | Y | 0 JS errors, HTTP 200 |
| Load time (live, ms, 400x900) | 2.0-3.9 s | 4-21 s | 1.1-2.2 s | 1.4-10.9 s | NFL multis 15 s, challenge 17 s, games 20 s (slow); Home games 10.9 s |

Per-sport live notes (multis cards now): NHL 2, Football 2, Tennis 2, NCAAB 2, NBA 2, NFL 2; AFL, NRL, NBL, NCAAF, AFLW 0 (empty state shown). Games tab lists games for NHL(7), Football(8), Tennis(8), NBL(2), NCAAB(8), NCAAF(8), Home(12); AFL, NRL, AFLW "No games listed" (empty feed). Not sampled live: rugby-league, cricket, mlb, rugby-union, other.

## Ranked gap list

1. Save the bet's sport for every sport (views.py:441 and the record form). Effort S (about 1 h). Unblocks the Your-bets-per-sport list, add-to-challenge filter and alert URLs. Fixes N on all 14 sports.
2. Generic per-sport scope for challenges: allow scope = any hub sport (not just all/nba/nfl) in nba_challenge and _sport_challenge, filter New/Add-to-challenge by it, scope-aware alert URL (push_store default and views.py:698 use `/sports?sport=X&tab=challenge`). Effort M (0.5-1 day). One change for 14 sports.
3. Your-bets list on every hub page (reuse nba.html "Your bets" block with bet_sport filter). Effort S-M. All 14 sports + Home.
4. Generic live tracker + live chance + auto settle through ESPN-style scoreboards: one adapter table (sport -> ESPN league, stat parsing) behind nba_live/live_chance/settle. Effort L (2-4 days); do NBL/NCAAB/NHL/MLB/NCAAF (ESPN has box scores) first; AFL/NRL/football/tennis/cricket/rugby need other feeds (Squiggle/NRL, football-data, etc), Effort L each. Fixes live tracking, live chance, settlement, live % bar.
5. Per-leg stat and chance bars on generic multi cards (use nslip macro layout with generic legs, show leg chance and game). Effort S-M. Fixes the card-parity P.
6. Stats model + market blend for non-NBA/NFL sports: build a means/blend model per sport (NHL and AFL scaffolds exist in tools/sports/*; wire them into discover legs, same as nfl_legs pk1). Effort L per sport; NHL, NCAAB, MLB first (player props exist).
7. Same-game correlation model per sport (tools/*/correlation.py pattern) to enable the SGM tab. Effort L per sport; until then SGM empty state is honest. Group with item 6.
8. Picker v1/v2 for generic sports: only meaningful after item 6 (needs model-vs-market legs). Effort M once item 6 exists.
9. Performance: NFL page 15-21 s and Home games 10.9 s. Cache nfl_legs.current_legs and next_games per refresh. Effort S-M.
10. Sample and confirm the five unsampled sports live (rugby-league, cricket, mlb, rugby-union, other) and make "Record a bet" appear on Challenge/Games tabs as NBA does. Effort S.

Quickest big win: items 1-3 (about 1-2 days) make 14 sports match NBA on bets, challenges and alerts without any new modelling. Items 4-8 are the real depth gap.
