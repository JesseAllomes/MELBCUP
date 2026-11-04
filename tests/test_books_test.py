"""tools/nba/books_test.py: US books' over/unders parsed, and the comparison report."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "nba"))

import books_test as B  # noqa: E402


def test_over_unders_become_legs_and_whole_lines_are_skipped():
    book = {
        "markets": [
            {
                "key": "player_points",
                "outcomes": [
                    {"name": "Over", "description": "A B", "point": 24.5, "price": 1.9},
                    {"name": "Under", "description": "A B", "point": 24.5, "price": 1.9},
                    {"name": "Over", "description": "C D", "point": 20.0, "price": 1.9},
                ],
            }
        ]
    }
    out = B.outcomes(book)
    assert [(o["k"], o["under"]) for o in out] == [(25, False), (25, True)]
    assert out[0]["stat"] == "points"


def test_report_compares_the_ways():
    rows = [
        {
            "who": f"p{i}",
            "y": i % 2,
            "model": 0.5,
            "pb": None,
            "us": 0.9 if i % 2 else 0.1,
            "all": 0.9 if i % 2 else 0.1,
        }
        for i in range(10)
    ]
    text = B.report(rows)
    assert "bets settled: 10" in text and "model+all" in text
    assert "best model weight with all books: 0.0" in text  # a perfect market wins
