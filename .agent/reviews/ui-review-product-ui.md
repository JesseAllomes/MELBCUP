# MELBCUP UI review for Cup day (Tue 3 Nov), phone first

Read-only. Method: `product-ui` SKILL.md plus references `use.md`, `aesthetics.md`, `banned-kits.md`,
`prototypes.md`, `styleguides.md`. Shots are in this folder, phone 390x844 @2x and desktop 1280x800, full page.

## Evidence limits (read first)
- The LIVE site (cup.asynym.dev) has no card loaded: the Cup field is not out until Sun 1 Nov and Auto is off.
  Live shots (`day-*`, `meetings-*`, `history-*`, `race1-*`) show only empty states; `/race/1` is a 404.
- Populated pages were rendered by running the same templates locally on a saved meeting (Warrnambool 29 Oct,
  `local-*` shots). That shows layout, picks, race page and history, but NOT the pre-race live state
  (Sportsbet row, "bet $", `until` countdowns, Refresh buttons). Re-check those on Sun 1 Nov once the card loads.
- No refresh or Load button was pressed on the live site. No repo file was changed.

## What the skill's checklist says
The skill is a build-time gate (prototype loop, product lock), so a redesign now is out of scope: it forbids
production UI rewrites without an explicit "build". Applied as a review lens, `use.md` is the relevant part.
- Banned kits: passes mostly. Paper and ink, rules and saddlecloth numbers are subject artifacts, not a rail or
  tile kit. Mild tells: bordered confidence chips, 11px uppercase labels (`.picks .line`, `.pick dt`).
- Aesthetics: type is `system-ui` only (rule 6 says not the personality). Fine for Cup day, a post-Cup item.
- Navigate: primary job is "which horse, what price, what stake, now". Not on screen without a hunt (issues 1, 3, 4).
- Function: empty/error states exist and say what to do. Same word for same act fails ("Best price for chance"
  vs "Value"). Status lives on the rows (good). Visible focus: yes. Reduced motion: yes.
- Efficient: one fetch plus a 60 s in-place refresh, no framework. Good.
- Product lock: `.grok/product-ui/{theme,design,layout}.md` do not exist in `/home/user/MELBCUP`.

## Per page
- Day `/` (`day.html`): `local-day-saved-phone.png`, `local-day-saved-desktop.png`. 3,600px of scroll on a phone for
  6 races, so about 10 on Cup day. Dense and legible, but no race strip and no "next race" anchor.
- Race `/race/N` (`race.html`): `local-race1-phone.png`. Picks block is good. The Field table is wider than the
  phone (530px in a 370px box), so Best, SB and Edge are off-screen.
- History (`history.html`): `local-history-phone.png`, 28,000px tall, 154 meetings. Fine for a desktop review.
  It is irrelevant on Cup day and does no harm.
- Meetings (`meetings.html`): `meetings-phone.png`. Clear. "2" on "Find meetings" is an unexplained cost badge.
- Empty day (live): `day-phone.png`. Honest, and the next action is the first button. Good.

## Ranked issues
1. HIGH, Race page, `local-race1-phone.png`: money columns hidden. `table.field` columns are
   Win, Place, Market, Fair, Best, SB, Edge. On 390px, SB (the book you bet at) and Edge scroll off, with no cue.
   Fix: in `app.css` add `@media (max-width:520px){table.field th:nth-child(n+4):nth-child(-n+5), table.field td:nth-child(n+4):nth-child(-n+5){display:none}}`
   (hides Market and Fair, keeps Best, SB, Edge), or reorder `<th>`/`<td>` in `race.html` to put SB and Edge before Market.
2. HIGH, Day, `local-day-saved-phone.png`: the actionable bit is in muted 13px grey. `.pick .fig` carries
   "wins 36% . $2.30 . bet $2", the horse is 15px. Fix: wrap price and "bet $N" in `<strong>` in `_picks.html`
   and give `.pick .fig strong{color:var(--ink);font-size:15px}`. Move the stake onto its own line.
3. MED, Day: no way to jump to the next race on a 10-race page. Past races (with results) sit above the upcoming ones.
   Fix: reuse `.racenav` from `race.html` at the top of `day.html` (anchors `#r{{n}}` already exist), and
   put `<details>` around finished races (`rg` set) so they collapse.
4. MED, Day, `local-day-budget-phone.png`: the budget input drives all stakes but sits at the very bottom
   (about 3,800px down). Fix: move the `form.budget` block above the first `article.race` in `day.html`,
   or into `base.html` under `.status`. It is remembered in localStorage anyway.
5. MED, Day, `app.js`: the 60 s refresh replaces `main.innerHTML`, which wipes a half-typed budget and drops
   focus (day page does not set `{% block refresh %}0`). Fix: skip refresh when
   `document.activeElement` is an `input` inside `main` (one line in `refresh()`).
6. MED, all pages: tap targets under 44px. Measured: `.racenav a` 27x30, nav links 21px high,
   `summary` 20px, footer links 15px, buttons about 33px. On a phone in a crowd that causes mis-taps.
   Fix: `.racenav a{min-width:44px;padding:11px 6px}`, `.masthead nav a{padding:12px 4px}`,
   `.runners summary,.race details summary{padding-block:12px}`, `button{padding:11px 14px}`.
7. MED, all: refresh failures are silent (`.catch` keeps the old page). In poor Flemington reception
   the owner sees stale prices as current. Fix: on catch, add a `<p class="alert">Offline, showing
   prices from HH:MM</p>` at the top of `main`; the time is already printed in `.when`.
8. MED, all, `app.css`: `--miss` #8a9094 on paper is 3.0:1 (dark 4.0:1). It styles the cross marks,
   `.conf.low` (11px) and miss rows. Fix: `--miss:#6b7377` (about 4.9:1); dark `--miss:#8b9396`.
9. LOW-MED, base: top status block is 5 lines plus 4 buttons before any race on a pre-race day
   (`day-phone.png`). The source sentence repeats on every page. Fix: in `base.html` shorten to one line
   ("racing.com . prices 2:31pm") and move the "Refreshes limited to one a minute" to a `title` or the History page.
10. LOW, base: "Auto off" reads as state, not action; the button is `class="on"` when on. Fix label to
    "Auto: off" / "Auto: on" or "Turn Auto on". Same-word rule: rename History `h3 Value` (`history.html:67`) to
    "Best price for chance" to match the day page.
11. LOW, `app.py` 404: `/race/N` before the card loads returns raw JSON `{"detail":...}` (`race1-phone.png`).
    A stale bookmark on Cup day looks broken. Fix: render a small HTML page with a link to `/`, or redirect
    `/race/N` to `/` in `views.page` when `rp is None`.
12. LOW, `base.html`: `theme-color` is fixed `#14181a`, a dark browser bar over the light theme. Fix: two metas with
    `media="(prefers-color-scheme: ...)"` (`#f6f7f5`, `#111416`).
13. LOW, `.race h1`: with a 3-line race name the number badge centres on the middle line
    (`local-race1-phone.png`). Fix: `.race h1{align-items:flex-start}`.
14. LOW, saved day: a doubled hairline at the top when `.status` is empty (`local-day-saved-phone.png`).
    Fix: `.status:empty{display:none}`, but check `can_fetch` markup in `base.html`.

## Do first before Cup day (low risk, CSS or one template line)
1. Hide Market and Fair on phones in the field table so Best, SB and Edge are visible (issue 1, CSS only).
2. Make price and "bet $N" ink-coloured and larger in `_picks.html`/`app.css` (issue 2).
3. Put the budget form at the top of `day.html` and skip the 60 s refresh while an input has focus (issues 4, 5).
4. Add the race-number strip to the top of `day.html`, reusing `.racenav` (issue 3).
5. Raise tap targets to 44px: racenav, nav links, summaries, buttons (issue 6, CSS only).
6. Show an "Offline, showing prices from HH:MM" banner when a refresh fails (issue 7, 6 lines of JS).
Also, not UI: turn Auto on and load the card on Sun 1 Nov, then re-run this review on the live pre-race state.
