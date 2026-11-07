"""The Sports catalogue view: filters, pagination, union, unmapped, probabilities, policy, time."""

import gzip
import json
import re
from pathlib import Path

import pytest
from test_asynym import ON, make

from melbcup import catalogue_view as cv

FIX = Path(__file__).parent / "fixtures" / "catalogue_ui"


@pytest.fixture(autouse=True)
def folder(monkeypatch):
    monkeypatch.setenv("CATALOGUE_DIR", str(FIX))
    cv.clear_cache()
    yield
    cv.clear_cache()


@pytest.fixture
def c():
    with make(ON) as client:
        yield client


def _big(tmp_path, n=3000):
    ev = {"event_id": "e1", "event_name": "Big v Game", "starts_at": "2026-12-25T02:30:00Z"}
    rows = [
        {
            "event_id": "e1",
            "event_start_utc": ev["starts_at"],
            "participant_id": f"p{i % 200}",
            "participant_name": f"Player {i % 200:03d}",
            "market_name_raw": "Points",
            "market_family": "points",
            "market_subtype": "main",
            "line_numeric": float(i),
            "line_raw": str(i),
            "side": "Over",
            "price_decimal": 1.9,
            "quote_observed_at_utc": "2026-11-07T02:00:00Z",
            "quote_status": "fresh",
            "suspended": False,
            "eligible_for_multis": False,
            "model_status": "market-only",
            "market_prob": None,
            "is_player_prop": True,
            "mapped": True,
            "key": f"k{i}",
            "period": "game",
        }
        for i in range(n)
    ]
    (tmp_path / "nba").mkdir()
    (tmp_path / "nba" / "latest.json.gz").write_bytes(
        gzip.compress(
            json.dumps(
                {"built": "2026-11-07T02:10:00Z", "events": [ev], "selections": rows}
            ).encode()
        )
    )
    (tmp_path / "coverage.json").write_text("[]")
    return tmp_path


def test_pagination_reaches_every_row(tmp_path, monkeypatch):
    monkeypatch.setenv("CATALOGUE_DIR", str(_big(tmp_path)))
    cv.clear_cache()
    q = cv.query("nba", "players", {})
    assert q["total"] == 3000 and q["pages"] == 60 and len(q["rows"]) == 50
    seen = set()
    for p in range(1, q["pages"] + 1):
        seen |= {r["key"] for r in cv.query("nba", "players", {"page": str(p)})["rows"]}
    assert len(seen) == 3000
    last = cv.query("nba", "markets", {"page": "999"})  # clamped to the last page
    assert last["page"] == 60 and last["rows"][-1]["key"] == "k2999"
    assert cv.query("nba", "players", {"q": "player 199"})["total"] >= 15
    assert cv.query("nba", "players", {"q": "Points"})["total"] == 3000  # not hidden by policy


def test_all_is_union_of_every_sport():
    union = cv.query("all", "markets", {})
    per = {s: cv.query(s, "markets", {})["total"] for s in ("nba", "afl", "nfl", "football")}
    # streaming union: every offered row is counted, and reading stops once the page is filled
    assert union["all_total"] == sum(per.values()) and union["sports"] == sorted(per)
    assert union["partial"] and len(union["rows"]) == cv.PAGE_SIZE and union["link_next"]
    assert cv.query("all", "players", {"q": "daicos"})["total"] > 0  # T52: search crosses sports


def test_unmapped_shows_raw_label(c):
    html = c.get("/sports?sport=nba&view=players&mapped=unmapped").text
    assert "Mystery Prop X" in html and "Other / Unmapped" in html and ">unmapped<" in html
    assert "Match Winner" not in html  # players view
    assert "Match Winner" in c.get("/sports?sport=nba&view=markets").text


def test_no_probability_without_market_prob(c):
    html = c.get("/sports?sport=nba&view=players&mapped=unmapped").text
    assert "no-vig" not in html
    assert "no-vig" in c.get("/sports?sport=nba&view=players&q=lebron").text


def test_missing_feed_text_exact(c):
    html = c.get("/sports?sport=nrl").text
    assert "No player-prop feed connected for this sport" in html
    assert (
        "No player-prop feed connected for this sport"
        in c.get("/sports?sport=cricket&view=markets").text
    )


def test_policy_never_hides_rows():
    q = cv.query("nba", "players", {"q": "99.5"})
    r = q["rows"][0]
    assert r["eligible_for_multis"] is False and r["suspended"]
    labels = {lab for _, lab in cv.flags(r)}
    assert {"stale", "suspended", "not-combinable", "model-experimental"} <= labels
    assert {lab for _, lab in cv.flags({"eligible_for_multis": None, "mapped": False})} >= {
        "terms-unknown",
        "unmapped",
    }
    assert (
        cv.query("nba", "markets", {})["total"]
        == cv.query("nba", "markets", {"model": ""})["total"]
    )


def test_filters():
    assert cv.query("nba", "players", {"alt": "1"})["total"] > 0
    assert all(cv.is_alt(r) for r in cv.query("nba", "players", {"alt": "1"})["rows"])
    assert all(r["side"] == "Under" for r in cv.query("nba", "players", {"side": "under"})["rows"])
    assert cv.query("nba", "players", {"fresh": "suspended"})["total"] == 1
    assert cv.query("nba", "players", {"event": "g2"})["total"] > 0


def test_melbourne_time_rendering(tmp_path, monkeypatch, c):
    monkeypatch.setenv("CATALOGUE_DIR", str(_big(tmp_path)))
    cv.clear_cache()
    html = c.get("/sports?sport=nba&view=players").text
    assert "Fri 25 Dec 1:30pm" in html  # 02:30 UTC is 1:30pm AEDT
    assert not re.search(r"\b02:30\b", html)


def test_chips_and_subtabs(c):
    html = c.get("/sports?sport=afl").text
    for label in ("NBL", "Cricket", "MLB", "Rugby union", "Racing"):
        assert f">{label}</a>" in html
    assert 'href="/sports?sport=afl&tab=all"' in html and 'aria-label="AFL tabs"' in html
    assert "Players · all props" in c.get("/sports?sport=afl&tab=all").text
    nba = c.get("/sports?sport=nba").text
    assert 'aria-label="NBA tabs"' in nba
    assert 'href="/sports?sport=racing"' in html


def test_all_tab_matrix_has_catalogue_counts(c):
    html = c.get("/sports?sport=all").text
    assert "Catalogue now" in html and "events," in html and "outcomes" in html
    assert "blocks automated download" in html  # static columns kept
