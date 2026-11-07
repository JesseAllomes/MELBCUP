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
)
BY_CODE = {s.code: s for s in SPORTS}
TABS = (
    (("nba", "NBA"),)
    + tuple((s.code, s.name) for s in SPORTS if s.code != "nba")
    + (("all", "All"),)
)
DEFAULT = "nba"


def pick(code: str | None) -> str:
    """The ?sport= value to show: a known tab, else NBA."""
    return code if code in BY_CODE or code == "all" else DEFAULT
