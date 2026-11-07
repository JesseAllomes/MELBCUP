# ruff: noqa: E501
"""The Sports hub's coverage matrix (/sports): what the app has for each sport, stated honestly.

A static table, edited by hand when a source or a result changes. Nothing here is a price or a
probability: sports with no live prices say so, and the research verdicts are copied in words from
research/sports/<sport>.md ("nothing beats the market" means the de-margined closing price was
the best model on the sealed hold-out).

Fields per sport:
  code        the ?sport= value
  name        tab label
  live        True only if the app lists live bookmaker prices for it today
  provider    where live prices come from ("" if none)
  markets     markets the app lists live (empty if none)
  modelled    markets the app models (empty if none)
  history     a /data/ link to the historical dataset ("" if none published)
  history_note  what that dataset holds
  result      the hold-out result in plain words ("" if never tested)
  missing     why something is absent (blocked source, unfinished dataset), "" if nothing
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Sport:
    code: str
    name: str
    live: bool
    provider: str
    markets: tuple[str, ...]
    modelled: tuple[str, ...]
    history: str
    history_note: str
    result: str
    missing: str


SPORTS: tuple[Sport, ...] = (
    Sport(
        "nba",
        "NBA",
        True,
        "PointsBet and Sportsbet; US books if switched on",
        ("player props", "multis"),
        ("player props", "multis"),
        "/data/sports/nba/",
        "games 2007-23 with closing odds; 2024-25 player prop prices and results",
        "Nothing beats the market on moneyline, spread, total or props (2021-22 and 2024-25 tests).",
        "",
    ),
    Sport(
        "racing",
        "Racing",
        True,
        "Sportsbet, Betfair, PointsBet, TAB, Ladbrokes, Neds",
        ("win", "place"),
        ("win chance", "value vs price"),
        "/data/sports/racing/",
        "every starter 2022-27 with prices and results; Betfair BSP",
        "Nothing beats the market by a margin we could bank; Betfair's starting price is already calibrated.",
        "",
    ),
    Sport(
        "afl",
        "AFL",
        False,
        "",
        (),
        (),
        "/data/sports/afl/",
        "games 2009-26: results, Elo, rest days (odds left out: source licence)",
        "Nothing beats the market on the 2025 hold-out (head to head, line, total).",
        "No live prices yet. No free player-prop source exists.",
    ),
    Sport(
        "nrl",
        "NRL",
        False,
        "",
        (),
        (),
        "",
        "",
        "",
        "Not tested: the free results-and-odds source blocks automated download (we do not get round it), so there is no dataset.",
    ),
    Sport(
        "nfl",
        "NFL",
        False,
        "",
        (),
        (),
        "/data/sports/nfl/",
        "games 1999-2026 with closing moneyline, spread and total",
        "Nothing beats the market on the 2025 hold-out; the published model is the no-vig market.",
        "No live prices yet. No free player-prop history exists.",
    ),
    Sport(
        "nhl",
        "NHL",
        False,
        "",
        (),
        (),
        "/data/sports/nhl/",
        "games 2007-23 with moneyline, puck line and total",
        "Nothing beats the market across 16 seasons (moneyline, puck line, totals).",
        "No live prices yet. Seasons 2023-24 and 2024-25 are missing: no free odds source reachable.",
    ),
    Sport(
        "football",
        "Football",
        False,
        "",
        (),
        (),
        "",
        "",
        "",
        "Not tested: the dataset is not finished.",
    ),
    Sport(
        "tennis",
        "Tennis",
        False,
        "",
        (),
        (),
        "",
        "",
        "",
        "Not tested: the free results-and-odds source blocks automated download (we do not get round it), so there is no dataset.",
    ),
    Sport(
        "nbl",
        "NBL",
        False,
        "",
        (),
        (),
        "",
        "",
        "",
        "Not tested: no dataset yet.",
    ),
    Sport(
        "ncaab",
        "NCAAB",
        False,
        "",
        (),
        (),
        "",
        "",
        "",
        "Not tested: no dataset yet.",
    ),
    Sport(
        "ncaaf",
        "NCAAF",
        False,
        "",
        (),
        (),
        "",
        "",
        "",
        "Not tested: no dataset yet.",
    ),
    Sport(
        "aflw",
        "AFLW",
        False,
        "",
        (),
        (),
        "",
        "",
        "",
        "Not tested: no dataset yet.",
    ),
    Sport(
        "rugby-league",
        "Rugby league",
        False,
        "",
        (),
        (),
        "",
        "",
        "",
        "Not tested: no dataset yet.",
    ),
    Sport(
        "cricket",
        "Cricket",
        False,
        "",
        (),
        (),
        "",
        "",
        "",
        "Not tested: no dataset yet.",
    ),
    Sport(
        "mlb",
        "MLB",
        False,
        "",
        (),
        (),
        "",
        "",
        "",
        "Not tested: no dataset yet.",
    ),
    Sport(
        "rugby-union",
        "Rugby union",
        False,
        "",
        (),
        (),
        "",
        "",
        "",
        "Not tested: no dataset yet.",
    ),
)
SPORTS += (
    Sport(
        "other",
        "Other",
        True,
        "PointsBet",
        ("player props where offered",),
        (),
        "",
        "",
        "",
        "Other basketball, American football, ice hockey and baseball leagues, grouped by competition.",
    ),
)
BY_CODE = {s.code: s for s in SPORTS}
TABS = (
    (("home", "Best multis"), ("nba", "NBA"))
    + tuple((s.code, s.name) for s in SPORTS if s.code != "nba")
    + (("all", "All"),)
)
DEFAULT = "home"  # the Sports home: best multis across every sport (owner, 2026-11-07)


VIEWS = ("players", "markets")


def pick_view(sport: str, code: str | None) -> str:
    """The sub-tab: "" is the page's own default (NBA's multis tabs, the All matrix); the rest are
    the catalogue views. Every other sport lands on its Bet now page."""
    if sport in ("racing", "home"):
        return ""
    if code in VIEWS:
        return code
    return ""


def pick(code: str | None) -> str:
    """The ?sport= value to show: a known tab, else NBA."""
    return code if code in BY_CODE or code in ("all", "home") else DEFAULT


SPORT_TABS = (
    ("multis", "Multis"),
    ("challenge", "Challenge"),
    ("games", "Games"),
    ("sgm", "SGM"),
    ("all", "All"),
)
_LEGACY_TAB = {"stacks": "multis", "same": "sgm", "legs": "all"}


def pick_tab(sport: str, tab: str | None, view: str | None = None) -> str:
    """The per-sport tab (the bottom bar): multis|challenge|games|sgm|all. "" on Best multis, Racing
    and the All coverage page, which have no bar. Old links keep working: NBA's stacks and same
    tabs, and ?view=players|markets (the All tab)."""
    if sport in ("racing", "all"):
        return ""  # Best multis (home) has the bar too (owner 2026-11-08: its tabs were missing)
    if view in VIEWS:
        return "all"
    tab = _LEGACY_TAB.get(tab or "", tab)
    return tab if tab in dict(SPORT_TABS) else "multis"
