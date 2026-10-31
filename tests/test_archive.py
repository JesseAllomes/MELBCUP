import json
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
from melbcup.sources.racingcom import RacingComClient


def test_saved_files_are_plain_and_need_no_key(tmp_path):
    day = date(2026, 10, 24)
    read = saved_meeting(tmp_path, day)
    assert set(json.loads(read("index.json"))) == {"meetings"}  # no locks, no salts
    assert not (tmp_path / "history-open.bin").exists()
    assert archive.Archive(read).open


def saved_meeting(tmp_path, day: date):
    """A finished meeting written to an archive on disk, and a reader for it."""
    t = httpx.MockTransport(Router())
    card = load_card(
        RacingComClient(transport=t), FormFavClient("k", transport=t), RACE_DATE, VENUE
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
    archive.write(str(tmp_path), [card])

    def read(path):
        f = tmp_path / path
        return f.read_text() if f.is_file() else None

    return read


def test_archive_opens_directly(tmp_path):
    day = date(2026, 10, 24)
    read = saved_meeting(tmp_path, day)
    good = archive.Archive(read)
    assert good.open and good.venues(day) == [VENUE] and good.has(day, "flemington")
    card = good.load(day, VENUE)
    assert card.races[1].result.finish and card.races[1].priced_from_sp
    assert not archive.Archive(lambda p: None).open  # nothing there: closed, not locked
    assert archive.Archive(lambda p: "not json" if p == "index.json" else None).open is False
    with pytest.raises(archive.ArchiveError):
        good.load(day, "Nowhere")
    assert good.history() == []  # none written for this one


def test_a_damaged_file_is_an_archive_error_not_a_crash(tmp_path):
    day = date(2026, 10, 24)
    read = saved_meeting(tmp_path, day)

    def damaged(path):
        return "!!not base64 or zlib!!" if path.endswith(".bin") else read(path)

    good = archive.Archive(damaged)
    with pytest.raises(archive.ArchiveError):
        good.load(day, VENUE)
    assert good.history() == []


def board(tmp_path, day, now, router):
    t = httpx.MockTransport(router)
    b = LiveBoard(
        load_settings({"PRICE_MODE": "auto"}),
        rc=RacingComClient(transport=t),
        ff=FormFavClient("ff", transport=t),
        clock=lambda: now,
        archive=archive.Archive(saved_meeting(tmp_path, day)),
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
    assert router.hits == {}  # nothing fetched: found, loaded and graded from the saved copy


def test_meeting_still_to_come_is_fetched_live_even_if_saved(tmp_path):
    router = Router()
    now = datetime(2026, 11, 3, 9, 0, tzinfo=MELBOURNE)
    b = board(tmp_path, RACE_DATE, now, router)
    b.tick()
    assert router.hits["rc/card_races"] == 1
    assert router.hits["rc/races"] == 1  # today: priced


def test_auto_collects_results_after_races_and_not_before(tmp_path):
    router = Router()
    clock = [datetime(2026, 11, 3, 11, 30, tzinfo=MELBOURNE)]  # R1 11:45, Cup 3:00pm
    b = board(tmp_path, date(2026, 10, 24), clock[0], router)
    b.clock = lambda: clock[0]
    b.set_meeting(RACE_DATE, VENUE)
    b.tick()
    assert "rc/results" not in router.hits  # nothing has run
    clock[0] = datetime(2026, 11, 3, 11, 58, tzinfo=MELBOURNE)  # R1 jumped 13 min ago
    b.tick()
    assert router.hits["rc/results"] == 2  # one results call per race, the whole card at once
    clock[0] += timedelta(minutes=5)
    b.tick()
    assert router.hits["rc/results"] == 2  # all final now, and too soon anyway


def test_field_not_published_yet_fetches_nothing(tmp_path):
    router = Router()
    now = datetime(2026, 10, 29, 12, 0, tzinfo=MELBOURNE)
    b = board(tmp_path, date(2026, 10, 24), now, router)
    b.set_meeting(RACE_DATE, VENUE)  # five days ahead: Racing Australia has not published it
    b.tick()
    assert router.hits == {} and b.snapshot().errors == []
    assert b.snapshot().field_due == date(2026, 11, 1)
    b.load_card_now(wait=True)  # the button says when, without calling
    assert router.hits == {} and "should be out on Sunday 1 November" in b.snapshot().errors[0]


def test_two_days_out_is_loaded_and_priced_because_racingcom_is_free(tmp_path):
    router = Router()
    now = datetime(2026, 11, 1, 12, 0, tzinfo=MELBOURNE)
    b = board(tmp_path, date(2026, 10, 24), now, router)
    b.set_meeting(RACE_DATE, VENUE)
    b.tick()
    assert router.hits["rc/card_races"] == 1
    assert router.hits["rc/races"] == 1  # bookmakers frame the Cup days ahead


def test_meetings_page_lists_saved_meetings_without_fetching(tmp_path, monkeypatch):
    from melbcup.web import views as v

    monkeypatch.setattr(v, "melbourne_today", lambda: date(2026, 10, 29))
    day = date(2026, 10, 24)
    router = Router()
    b = board(tmp_path, day, datetime(2026, 10, 29, 12, 0, tzinfo=MELBOURNE), router)
    html = v.Views(b.settings, b, browser=True).page("/meetings", {"date": day.isoformat()})
    assert "saved with results" not in html and "venue=Flemington" in html
    assert router.hits == {}


def test_history_page_tallies_saved_and_new_races(tmp_path, monkeypatch):
    from melbcup import history
    from melbcup.bets import build_picks
    from melbcup.model.probability import assess
    from melbcup.web import views as v

    monkeypatch.setattr(v, "melbourne_today", lambda: RACE_DATE)
    day = date(2026, 10, 24)
    read = saved_meeting(tmp_path, day)
    saved_card = archive.Archive(read).load(day, VENUE)
    record = history.entries(build_picks([assess(r) for r in saved_card.races]))
    assert len(record) == 2 and {"top_win", "top_place", "trifecta"} <= set(record[0]["picks"])
    archive.write(str(tmp_path), [saved_card], history=record)

    router = Router()
    t = httpx.MockTransport(router)
    b = LiveBoard(
        load_settings({"PRICE_MODE": "auto"}),
        rc=RacingComClient(transport=t),
        ff=FormFavClient("ff", transport=t),
        clock=lambda: datetime(2026, 11, 3, 16, 0, tzinfo=MELBOURNE),  # after the Cup
        archive=archive.Archive(read),
    )
    b.tick()  # loads the card, prices and the day's results
    assert router.hits["rc/results"] == 2
    assert len(b.history()) == 2

    html = v.Views(b.settings, b, browser=True).page("/history", {})
    assert "4 races, 2 meetings" in html
    assert "Tue 3 Nov" in html and "Sat 24 Oct" in html
    assert "Lexus Melbourne Cup" in html and "✓" in html
    assert "Most likely" in html
    tallies = {t.label: t for t in history.tally(history.merge(record, b.history()))}
    top = tallies["Most likely win"]
    assert top.picks == 4 and 0 <= top.correct <= 4 and top.failed == 4 - top.correct


def test_history_opens_with_no_prompt_and_no_locked_notice(tmp_path, monkeypatch):
    from melbcup.web import views as v

    monkeypatch.setattr(v, "melbourne_today", lambda: RACE_DATE)
    b = LiveBoard(
        load_settings({}), archive=archive.Archive(saved_meeting(tmp_path, date(2026, 10, 24)))
    )
    html = v.Views(b.settings, b, browser=True).page("/history", {})
    assert "locked" not in html and "password" not in html.lower()
