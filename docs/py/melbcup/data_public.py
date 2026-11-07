"""What /data publishes (owner, 2026-11-07): the blob names it serves and what each one is.
Shared by the web app and tools/export_data.py. Phone alert records (push/) stay private."""

import re

DATA_OK = re.compile(
    r"^(board-latest\.json|view-latest\.json\.gz|forward(-v2)?\.jsonl|forward-v2-reconcile\.json|schedule\.json|"
    r"us-latest\.json|legs-latest\.json|(history|bookstest|racing|sports|export)/[\w./-]+|"
    r"\d{8}/[\w.-]+)$"
)
DATA_ABOUT = (
    ("export/", "everything below in one zip, with a README describing each file"),
    (
        "sports/racing/",
        "horse racing: every starter 2022-27 with prices and results; Betfair BSP",
    ),
    (
        "sports/nba/",
        "NBA games 2007-23 with closing odds; 2024-25 player prop prices + results",
    ),
    ("sports/afl/", "AFL games 2009-26: results, Elo, rest (odds left out: source licence)"),
    ("sports/nfl/", "NFL games 1999-2026 with closing moneyline, spread, total"),
    ("sports/nhl/", "NHL games 2007-23 with moneyline, puck line, total"),
    ("history/", "NBA box-score history the model is fitted on"),
    ("bookstest/", "NBA: US and Australian bookmaker snapshots for the books test"),
    ("forward-v2-reconcile", "NBA: what changed between the original and corrected forward logs"),
    (
        "forward-v2",
        "NBA forward log, corrected: each leg settled against its own game by ESPN event",
    ),
    (
        "forward.jsonl",
        "NBA forward log v1, frozen: later games' legs settled against the wrong game",
    ),
    ("racing/", "racing: saved picks, graded-race log, tuning"),
    ("", "NBA: the live board, view, legs and daily files"),
)
