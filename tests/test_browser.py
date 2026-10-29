"""The browser build's controller, driven the way the page's JavaScript drives it."""

from datetime import datetime

import httpx
import pytest
from conftest import Router

from melbcup import browser, sources
from melbcup.config import MELBOURNE
from melbcup.sources import http

CUP_MORNING = datetime(2026, 11, 3, 9, 0, tzinfo=MELBOURNE)


def requester_for(router: Router):
    def request(url: str, headers: dict[str, str]) -> http.RawResponse:
        resp = router(httpx.Request("GET", url, headers=headers))
        return http.RawResponse(
            resp.status_code, {k.lower(): v for k, v in resp.headers.items()}, resp.text
        )

    return request


@pytest.fixture(autouse=True)
def restore_globals():
    workers, default = sources.WORKERS, http.DEFAULT_REQUESTER
    yield
    sources.WORKERS, http.DEFAULT_REQUESTER = workers, default


def test_full_flow_and_saved_state_costs_nothing_on_reopen():
    router = Router()
    seen = []
    browser.init(
        "pe", "ff", requester=requester_for(router), progress=seen.append, clock=lambda: CUP_MORNING
    )
    assert sources.WORKERS == 1
    assert "No card loaded yet" in browser.render("/")
    assert "API keys" in browser.render("/")

    nxt = browser.act("/actions/load?next=/")
    assert nxt == "/"
    html = browser.render(nxt)
    assert "Lexus Melbourne Cup" in html and "Each way" in html
    assert router.hits["/v1/racing/acceptances"] == 1
    assert "Grand Tempo" in browser.render("/race/2?budget=100")
    assert "Choose a meeting" in browser.render("/meetings")
    assert "Lexus Melbourne Cup" in browser.render("/race/99")  # unknown pages fall back home

    saved = browser.save()
    before = dict(router.hits)
    browser.init("pe", "ff", saved, requester=requester_for(router), clock=lambda: CUP_MORNING)
    assert "Lexus Melbourne Cup" in browser.render("/")
    after = dict(router.hits)
    assert after.pop("/v1/keys/info") == before.pop("/v1/keys/info") + 1  # the free balance read
    assert after == before  # nothing else: no credits spent on reopening


def test_damaged_or_old_saved_state_starts_clean():
    router = Router()
    browser.init(
        "pe", "ff", "not base64!", requester=requester_for(router), clock=lambda: CUP_MORNING
    )
    assert "No card loaded yet" in browser.render("/")


def test_phone_starts_in_auto_mode():
    browser.init("pe", "ff", requester=requester_for(Router()), clock=lambda: CUP_MORNING)
    assert "Auto on" in browser.render("/")


def test_actions_route_like_the_server():
    router = Router()
    browser.init("pe", "ff", requester=requester_for(router), clock=lambda: CUP_MORNING)
    assert browser.act("/actions/meeting?date=2026-10-31&venue=Flemington") == "/"
    assert "Sat 31 Oct" in browser.render("/")
    assert browser.act("/actions/nonsense") == "/"
    assert browser.act("/actions/auto?on=1&next=/meetings") == "/meetings"
    assert browser.tick() in (True, False)
