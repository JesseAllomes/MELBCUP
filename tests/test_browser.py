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
    assert "Lexus Melbourne Cup" in html and "Most likely" in html
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


def test_opening_the_page_spends_nothing():
    router = Router()
    browser.init("pe", "ff", requester=requester_for(router), clock=lambda: CUP_MORNING)
    assert "Auto off" in browser.render("/")
    assert browser.tick() is False  # Auto off: the heartbeat fetches nothing
    assert set(router.hits) <= {"/v1/keys/info"}  # only the free balance read


def test_actions_route_like_the_server():
    router = Router()
    browser.init("pe", "ff", requester=requester_for(router), clock=lambda: CUP_MORNING)
    assert browser.act("/actions/meeting?date=2026-10-31&venue=Flemington") == "/"
    assert "Sat 31 Oct" in browser.render("/")
    assert browser.act("/actions/nonsense") == "/"
    assert browser.act("/actions/auto?on=1&next=/meetings") == "/meetings"
    assert browser.tick() in (True, False)


def test_warm_fetches_the_load_side_by_side_and_the_load_reads_the_cache():
    import asyncio

    router = Router()
    fetched: list[str] = []

    async def fetch_many(urls, headers, label):
        fetched.extend(urls)
        replies = [requester_for(router)(u, headers) for u in urls]
        return [[r.status, r.text] for r in replies]

    browser.init(
        "pe",
        "ff",
        requester=requester_for(router),
        clock=lambda: CUP_MORNING,
        fetch_many=fetch_many,
    )
    assert asyncio.run(browser.warm(False)) == 0  # Auto is off when the page opens
    assert not fetched and "Auto off" in browser.render("/")
    browser.act("/actions/auto?on=1&next=/")
    cached = asyncio.run(browser.warm(False))  # Auto's first load is coming
    assert cached > 10 and any("/v1/stats/jockey/" in u for u in fetched)
    before = dict(router.hits)
    assert browser.tick()  # the load
    after = dict(router.hits)
    assert after["/v1/racing/acceptances"] == before["/v1/racing/acceptances"] == 1
    assert after.get("/v1/racing/form") == before.get("/v1/racing/form")  # no credits twice
    assert after.get("/v1/form") == before.get("/v1/form")
    stats = [k for k in after if k.startswith("/v1/stats/")]
    assert stats and all(after[k] == before.get(k) for k in stats)  # people came from the cache
    assert "Lexus Melbourne Cup" in browser.render("/")
    assert asyncio.run(browser.warm(False)) == 0  # card loaded: Auto will not load again
