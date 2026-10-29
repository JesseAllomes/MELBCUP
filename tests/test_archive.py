from datetime import date, datetime, timedelta

import httpx
import pytest
from conftest import RACE_DATE, VENUE, Router

from melbcup import archive
from melbcup.config import MELBOURNE, load_settings
from melbcup.domain import RaceResult
from melbcup.live import LiveBoard
from melbcup.sources import apply_result, load_card
from melbcup.sources.formfav import FormFavClient
from melbcup.sources.puntersedge import PuntersEdgeClient


def test_seal_roundtrip_and_tamper_detection():
    keys = archive.derive("secret", b"salt-salt-salt-s")
    blob = archive.seal(b"the field and the form" * 50, keys)
    assert archive.unseal(blob, keys) == b"the field and the form" * 50
    assert b"field" not in blob
    with pytest.raises(archive.ArchiveError):
        archive.unseal(blob[:-1] + bytes([blob[-1] ^ 1]), keys)
    with pytest.raises(archive.ArchiveError):
        archive.unseal(blob, archive.derive("other", b"salt-salt-salt-s"))


def saved_meeting(tmp_path, day: date):
    """A finished meeting written to an archive on disk, and a reader for it."""
    t = httpx.MockTransport(Router())
    card = load_card(
        PuntersEdgeClient("k", transport=t), FormFavClient("k", transport=t), RACE_DATE, VENUE
    )
    card.race_date = day
    for race in card.races:
        race.race_date = day
        finish = {r.number: i + 1 for i, r in enumerate(race.runners)}
        apply_result(
            race,
            RaceResult(
                "final", finish, {n: 5.0 for n in finish}, {r.number: r.name for r in race.runners}
            ),
        )
    archive.write(str(tmp_path), [card], "pe-key")

    def read(path):
        f = tmp_path / path
        return f.read_text() if f.is_file() else None

    return read


def test_archive_needs_the_right_key(tmp_path):
    day = date(2026, 10, 24)
    read = saved_meeting(tmp_path, day)
    good = archive.Archive(read, "pe-key")
    assert good.open and good.venues(day) == [VENUE] and good.has(day, "flemington")
    card = good.load(day, VENUE)
    assert card.races[1].result.finish and card.races[1].priced_from_sp
    wrong = archive.Archive(read, "someone-else")
    assert not wrong.open and wrong.venues(day) == []
    assert not archive.Archive(lambda p: None, "pe-key").open


def board(tmp_path, day, now, router):
    t = httpx.MockTransport(router)
    b = LiveBoard(
        load_settings({"PUNTERSEDGE_API_KEY": "pe", "PRICE_MODE": "auto"}),
        pe=PuntersEdgeClient("pe", transport=t),
        ff=FormFavClient("ff", transport=t),
        clock=lambda: now,
        archive=archive.Archive(saved_meeting(tmp_path, day), "pe-key"),
    )
    b.set_meeting(day, VENUE)
    return b


def test_saved_past_meeting_opens_with_no_api_calls(tmp_path):
    day = date(2026, 10, 24)
    router = Router()
    now = datetime(2026, 10, 29, 12, 0, tzinfo=MELBOURNE)
    b = board(tmp_path, day, now, router)
    assert b.find_meetings(day) == [VENUE]
    b.tick()
    snap = b.snapshot()
    assert snap.card is not None and all(r.result for r in snap.card.races)
    assert router.hits == {}  # no credits: found, loaded and graded from the saved copy


def test_meeting_still_to_come_is_fetched_live_even_if_saved(tmp_path):
    router = Router()
    now = datetime(2026, 11, 3, 9, 0, tzinfo=MELBOURNE)
    b = board(tmp_path, RACE_DATE, now, router)
    b.tick()
    assert router.hits["/v1/racing/acceptances"] == 1
    assert router.hits["/v1/racing/next-to-go"] == 1  # today: priced


def test_auto_collects_results_after_races_and_not_before(tmp_path):
    router = Router()
    clock = [datetime(2026, 11, 3, 11, 30, tzinfo=MELBOURNE)]  # R1 11:45, Cup 3:00pm
    b = board(tmp_path, date(2026, 10, 24), clock[0], router)
    b.clock = lambda: clock[0]
    b.set_meeting(RACE_DATE, VENUE)
    b.tick()
    assert "/v1/racing/results" not in router.hits  # nothing has run
    clock[0] = datetime(2026, 11, 3, 11, 58, tzinfo=MELBOURNE)  # R1 jumped 13 min ago
    b.tick()
    assert router.hits["/v1/racing/results"] == 1
    clock[0] += timedelta(minutes=5)
    b.tick()
    assert router.hits["/v1/racing/results"] == 1  # all final now, and too soon anyway


def test_far_future_meeting_is_not_priced(tmp_path):
    router = Router()
    now = datetime(2026, 10, 29, 12, 0, tzinfo=MELBOURNE)
    b = board(tmp_path, date(2026, 10, 24), now, router)
    b.set_meeting(RACE_DATE, VENUE)  # five days ahead: no market yet
    b.tick()
    assert router.hits["/v1/racing/acceptances"] == 1
    assert "/v1/racing/next-to-go" not in router.hits


def test_meetings_page_lists_saved_meetings_free(tmp_path, monkeypatch):
    from melbcup.web import views as v

    monkeypatch.setattr(v, "melbourne_today", lambda: date(2026, 10, 29))
    day = date(2026, 10, 24)
    router = Router()
    b = board(tmp_path, day, datetime(2026, 10, 29, 12, 0, tzinfo=MELBOURNE), router)
    html = v.Views(b.settings, b, browser=True).page("/meetings", {"date": day.isoformat()})
    assert "saved with results: they open free" in html and "venue=Flemington" in html
    assert router.hits == {}


def test_fallback_key_derivation_matches_hashlib():
    import hashlib

    want = hashlib.pbkdf2_hmac("sha256", b"pe-key", b"0123456789abcdef", archive.ITERATIONS, 64)
    assert archive._pbkdf2(b"pe-key", b"0123456789abcdef", archive.ITERATIONS, 64) == want
