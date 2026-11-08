"""Staged card load: the field first, prices next, form and stewards' comments in the background."""

import threading
from datetime import timedelta

from conftest import RACE_DATE, Router
from test_live_web import AUTO, START, Clock, board_with

from melbcup import live


def slow_enrich(monkeypatch, gate, started, mark="run_notes"):
    def fake(card, rc, ff):
        started.set()
        gate.wait(5)
        for race in card.races:
            for r in race.runners:
                r.running_style = "enriched"
        card.warnings.append("fake warning")

    monkeypatch.setattr(live, "enrich_card", fake)


def test_card_and_prices_do_not_wait_for_enrichment(monkeypatch):
    gate, started = threading.Event(), threading.Event()
    slow_enrich(monkeypatch, gate, started)
    board = board_with(Router(), Clock(START), AUTO)
    assert board.load_card_now(wait=False)
    # the job itself must finish (field + prices) while enrichment is still blocked
    for _ in range(100):
        s = board.snapshot()
        if s.card is not None and s.priced_at is not None:
            break
        threading.Event().wait(0.05)
    s = board.snapshot()
    assert s.card is not None and s.enriching and s.models
    assert s.priced_at is not None and s.card.race(1).prices
    assert started.wait(2) and not s.card.race(1).runners[0].running_style
    gate.set()
    board._enrich_thread.join(5)
    s = board.snapshot()
    assert not s.enriching and s.card.race(1).runners[0].running_style == "enriched"
    assert "fake warning" in s.card.warnings and s.card.race(1).prices  # prices kept


def test_models_reassessed_after_enrichment(monkeypatch):
    gate, started = threading.Event(), threading.Event()
    slow_enrich(monkeypatch, gate, started)
    calls = []
    real = live.assess
    monkeypatch.setattr(live, "assess", lambda r: calls.append(r.number) or real(r))
    board = board_with(Router(), Clock(START), AUTO)
    board._load_form(START)
    n = len(calls)
    gate.set()
    board._enrich_thread.join(5)
    assert len(calls) > n


def test_meeting_change_discards_stale_enrichment(monkeypatch):
    gate, started = threading.Event(), threading.Event()
    slow_enrich(monkeypatch, gate, started)
    board = board_with(Router(), Clock(START), AUTO)
    board._load_form(START)
    assert started.wait(2)
    assert board.set_meeting(RACE_DATE + timedelta(days=1), "Elsewhere")
    gate.set()
    board._enrich_thread.join(5)
    s = board.snapshot()
    assert s.card is None and not s.enriching
