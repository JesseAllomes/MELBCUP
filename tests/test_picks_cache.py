# ruff: noqa: E501
"""The day's picks are worked out once per set of race models and budget (melbcup/live.py)."""

from conftest import Router
from test_live_web import START, Clock, board_with


def test_picks_are_reused_until_the_models_or_budget_change():
    board = board_with(Router(), Clock(START))
    board.load_card_now(wait=True)
    snap = board.snapshot()
    first = snap.picks(200.0)
    assert board.snapshot().picks(200.0) is first  # another page, same models: no new work
    assert snap.picks(100.0) is not first  # another budget: its own stakes
    with board._lock:  # prices refreshed: new model objects
        board._models = {n: m for n, m in board._models.items()} | {
            n: type(m)(**vars(m)) if hasattr(m, "__dict__") else m for n, m in list(board._models.items())[:1]
        }
    if board.snapshot().models[0] is not snap.models[0]:
        assert board.snapshot().picks(200.0) is not first
