"""
The local news scrapers, asserted rather than assumed.

This file exists because three of the five outlets were silently returning
nothing. Every request came back HTTP 200, so no error was logged and no health
check failed -- the CSS selectors had simply drifted from the sites' markup, and
a scraper that extracts zero articles from a page it fetched successfully looks
exactly like a quiet news day.

The structural tests run everywhere and need no network. The live one skips
itself when a site is unreachable, following the e2e convention, so
`pytest tests/` stays green offline while still catching selector drift when
run against the internet.
"""

import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# --- 1. the outlets we claim to cover ---------------------------------------

def test_the_named_sri_lankan_outlets_are_configured():
    """
    Ada Derana and Newswire were absent entirely, and Daily Mirror and News
    First were present but matched nothing.
    """
    from src.utils.utils import LOCAL_NEWS_SITES

    names = {s["name"].lower() for s in LOCAL_NEWS_SITES}
    for expected in ("daily mirror", "daily ft", "news first",
                     "ada derana", "newswire"):
        assert expected in names, f"{expected} is not configured"


def test_daily_mirror_selector_uses_the_underscore_the_site_actually_uses():
    """
    REGRESSION. The selector said `.news-block`; the site renders `news_block`.
    One character, zero articles, no error.
    """
    from src.utils.utils import LOCAL_NEWS_SITES

    mirror = next(s for s in LOCAL_NEWS_SITES if s["name"] == "Daily Mirror")
    assert "news_block" in mirror["article_selector"]


# --- 2. headline extraction --------------------------------------------------

def test_h4_is_probed_for_headlines():
    """
    REGRESSION. Daily Mirror renders 177 <h4> and zero <h1>; Newswire titles are
    h4.posts-listunit-title. Probing only h1/h2/h3 found nothing on either even
    once their containers matched.
    """
    from src.utils.utils import _headline_of
    from bs4 import BeautifulSoup

    block = BeautifulSoup(
        '<div><h4><a href="/a/story">A headline long enough to count</a></h4></div>',
        "html.parser",
    )
    assert _headline_of(block) == "A headline long enough to count"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Sri Lanka Probes Prison Unrest07-08-2026 | 5:36 PM",
         "Sri Lanka Probes Prison Unrest"),
        ("1h agoMore details emerge on Magazine Prison clash",
         "More details emerge on Magazine Prison clash"),
        ("3 hours agoInvestigation launched into Kuruwita Prison",
         "Investigation launched into Kuruwita Prison"),
        ("A perfectly ordinary headline", "A perfectly ordinary headline"),
    ],
)
def test_timestamps_glued_to_headlines_are_stripped(raw, expected):
    """
    Several sites put the date in the same element as the title, so the two
    concatenate. Left in, that noise reaches entity extraction and the story
    threader as part of the headline.
    """
    from src.utils.utils import _clean_headline

    assert _clean_headline(raw) == expected


# --- 3. one prolific site must not starve the others ------------------------

def test_no_single_outlet_can_consume_the_whole_quota(monkeypatch):
    """
    REGRESSION, and the subtler of the two bugs.

    The old loop appended into one list and returned as soon as it held
    max_articles. Daily FT alone yields 212 headlines and sits second, so a
    default call of 30 was satisfied entirely by Daily FT -- and every site
    after it was never fetched at all. A healthy News First and a broken one
    produced identical output.
    """
    from src.utils import utils

    class FakeResponse:
        status_code = 200

        def __init__(self, text):
            self.text = text

    def block(selector: str, title: str) -> str:
        first = selector.split(",")[0].strip()
        if first.startswith("."):
            return (f'<div class="{first[1:]}">'
                    f'<h4><a href="/n/{abs(hash(title))}">{title}</a></h4></div>')
        return (f'<{first}><h4><a href="/n/{abs(hash(title))}">{title}</a>'
                f'</h4></{first}>')

    def fake_get(url, *args, **kwargs):
        site = next(s for s in utils.LOCAL_NEWS_SITES if s["url"] == url)
        # The first outlet is made hugely prolific on purpose -- that is the
        # shape that starved the others.
        count = 200 if site is utils.LOCAL_NEWS_SITES[0] else 10
        body = "".join(
            block(site["article_selector"], f"{site['name']} story number {i}")
            for i in range(count)
        )
        return FakeResponse(f"<html><body>{body}</body></html>")

    monkeypatch.setattr(utils, "_safe_get", fake_get)

    rows = utils.scrape_local_news_impl(keywords=None, max_articles=30)

    sources = {r["source"] for r in rows}
    assert sources == {s["name"] for s in utils.LOCAL_NEWS_SITES}, (
        f"only {sources} contributed; a single outlet is monopolising the quota"
    )
    assert len(rows) == 30

    # Round-robin: the first N results should be one per outlet, in order.
    lead = [r["source"] for r in rows[: len(utils.LOCAL_NEWS_SITES)]]
    assert len(set(lead)) == len(utils.LOCAL_NEWS_SITES), (
        f"the first results are not interleaved across outlets: {lead}"
    )


def test_a_site_that_matches_nothing_says_so(monkeypatch, caplog):
    """
    HTTP 200 with zero extracted articles is the signature of selector drift.
    It must not be silent -- being silent is what let this persist.
    """
    import logging

    from src.utils import utils

    class FakeResponse:
        status_code = 200
        text = "<html><body><div class='unrelated'>nothing here</div></body></html>"

    monkeypatch.setattr(utils, "_safe_get", lambda *a, **k: FakeResponse())

    with caplog.at_level(logging.WARNING):
        rows = utils.scrape_local_news_impl(keywords=None, max_articles=5)

    assert rows == []
    assert any("matched no articles" in r.message or "stale" in r.message
               for r in caplog.records), (
        "a page that yielded no articles logged nothing"
    )


# --- 4. against the real sites ----------------------------------------------

def test_every_configured_outlet_returns_articles_live():
    """
    The test that would have caught this. Skips when a site is unreachable so
    the offline suite stays green.
    """
    from src.utils.utils import LOCAL_NEWS_SITES, _headline_of, _safe_get
    from bs4 import BeautifulSoup

    reachable, dead = 0, []
    for site in LOCAL_NEWS_SITES:
        try:
            resp = _safe_get(site["url"])
        except Exception:
            continue
        if not resp:
            continue
        reachable += 1
        soup = BeautifulSoup(resp.text, "html.parser")
        found = [
            h for h in (
                _headline_of(b)
                for b in soup.select(site["article_selector"])
            ) if h
        ]
        if not found:
            dead.append(f"{site['name']} (HTTP {resp.status_code}, "
                        f"{len(resp.text)}B, selector {site['article_selector']!r})")

    if reachable == 0:
        pytest.skip("no news site reachable from here")

    assert not dead, (
        "fetched successfully but extracted no articles:\n  " + "\n  ".join(dead)
    )
