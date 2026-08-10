"""
Do the scrapers' selectors still extract anything?

The existing scraper tests cover registration, wiring and the status
vocabulary. Not one of them would fail if X renamed
``data-testid='tweetText'`` tomorrow -- and until ``containers_seen`` landed in
base.py, that rename would have shown up as status "ok" with zero posts, exactly
like a quiet news day.

These run the REAL extraction code against saved markup, in a real Chromium with
the real CSS engine, with no network. A BeautifulSoup reimplementation would
test a different selector engine and prove nothing about what actually runs.

Two kinds of fixture, and the difference matters:

  <platform>.html            captured from the live site by
                             `python -m connector.selftest --capture`.
                             Text nodes are redacted at capture time. This is
                             the one that catches a PLATFORM redesign.

  <platform>.synthetic.html  hand-written to the documented DOM shape. Catches
                             regressions on OUR side -- a refactor of _harvest,
                             a mistyped selector constant -- but by construction
                             can never notice the platform changing.

A real capture wins where both exist. Everything skips cleanly when neither
does, so the suite stays green until someone runs the self-test.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "scrapers"

PLATFORMS = ["twitter", "linkedin", "facebook"]


def _fixture(platform: str):
    """Prefer a real capture; fall back to the synthetic shape."""
    real = FIXTURES / f"{platform}.html"
    synthetic = FIXTURES / f"{platform}.synthetic.html"
    if real.exists():
        return real, "captured"
    if synthetic.exists():
        return synthetic, "synthetic"
    return None, None


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    try:
        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _chromium_available(),
    reason="Chromium not installed (expected on the server -- collection runs "
           "in the connector)",
)


class _Ctx:
    """
    The ScrapeContext surface _harvest uses, minus pacing and the network.

    Deliberately not the real ScrapeContext: that one charges a daily request
    budget and sleeps for human-scale intervals, neither of which belongs in a
    test.
    """

    def __init__(self, page, platform):
        self.page = page
        self.platform = platform
        self.containers_seen = 0
        self._posts = 0

    def note_containers(self, n):
        self.containers_seen = max(self.containers_seen, int(n or 0))

    def pace(self, kind="nav"):
        pass

    def scroll(self, times=1, pixels=0):
        pass

    def count_posts(self, n):
        self._posts += n

    def posts_remaining(self):
        return 50

    def assert_healthy(self):
        pass


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


def _harvest_fixture(browser, platform):
    """Run the platform's real _harvest against its fixture."""
    import importlib

    path, kind = _fixture(platform)
    if path is None:
        pytest.skip(f"no fixture for {platform}; run connector.selftest --capture")

    module = importlib.import_module(f"src.scrapers.{platform}")

    page = browser.new_page()
    try:
        page.set_content(path.read_text(encoding="utf-8"))
        ctx = _Ctx(page, platform)

        if platform == "twitter":
            posts = module._harvest(ctx, 20, poster_override=None,
                                    url_fallback="https://x.com")
        else:
            posts = module._harvest(ctx, 20, "https://example.invalid")
        return posts, kind
    finally:
        page.close()


# --- extraction ------------------------------------------------------------

@pytest.mark.parametrize("platform", PLATFORMS)
def test_selectors_extract_posts(browser, platform):
    posts, kind = _harvest_fixture(browser, platform)

    assert posts, (
        f"{platform}: the {kind} fixture rendered post containers but "
        f"_harvest extracted nothing -- the selectors no longer match"
    )


@pytest.mark.parametrize("platform", PLATFORMS)
def test_every_extracted_post_has_text(browser, platform):
    """
    The precise partial-rot case: containers match, the text selector does not.
    Posts come back structurally intact and semantically empty.
    """
    posts, _ = _harvest_fixture(browser, platform)

    empty = [p for p in posts if not (p.get("text") or "").strip()]
    assert not empty, f"{platform}: {len(empty)}/{len(posts)} posts have no text"


@pytest.mark.parametrize("platform", PLATFORMS)
def test_poster_attribution_survives(browser, platform):
    """
    A feed of posts all attributed to "Unknown" is a broken POSTER selector, and
    nothing else in the system would notice.
    """
    posts, _ = _harvest_fixture(browser, platform)

    named = [p for p in posts if p.get("poster") and p["poster"] != "Unknown"]
    assert named, f"{platform}: every post came back with no poster"


@pytest.mark.parametrize("platform", PLATFORMS)
def test_containers_are_reported(browser, platform):
    """
    Without this, base.py cannot tell selector rot from an empty page.
    """
    path, _ = _fixture(platform)
    if path is None:
        pytest.skip("no fixture")

    import importlib

    module = importlib.import_module(f"src.scrapers.{platform}")
    page = browser.new_page()
    try:
        page.set_content(path.read_text(encoding="utf-8"))
        ctx = _Ctx(page, platform)
        if platform == "twitter":
            module._harvest(ctx, 20, poster_override=None, url_fallback="https://x.com")
        else:
            module._harvest(ctx, 20, "https://example.invalid")

        assert ctx.containers_seen > 0, (
            f"{platform}._harvest never called ctx.note_containers()"
        )
    finally:
        page.close()


# --- platform-specific behaviour ------------------------------------------

def test_twitter_skips_promoted_posts(browser):
    """Ads are not intelligence. The fixture carries one."""
    posts, kind = _harvest_fixture(browser, "twitter")
    if kind != "synthetic":
        pytest.skip("captured fixtures may not contain a promoted post")

    assert not any("limited time offer" in p["text"].lower() for p in posts), (
        "a promoted tweet was harvested as a real post"
    )
    assert len(posts) == 2


def test_twitter_extracts_engagement_and_permalink(browser):
    posts, kind = _harvest_fixture(browser, "twitter")
    if kind != "synthetic":
        pytest.skip("engagement counts vary on captured fixtures")

    first = posts[0]
    assert first["likes"] == 1204, "abbreviated/expanded like counts not parsed"
    assert first["retweets"] == 87
    assert first["replies"] == 14
    assert "/status/" in first["url"], (
        "permalink not resolved; the search scraper used to hardcode the site root"
    )
    assert first["timestamp"], "no timestamp extracted from <time datetime=...>"


# --- the guard itself ------------------------------------------------------

def test_a_broken_selector_actually_fails_this_suite(browser, monkeypatch):
    """
    Proves these tests can fail. A selector test that passes against anything is
    worse than none, because it reads as coverage.
    """
    from src.scrapers import twitter as tw

    path, _ = _fixture("twitter")
    if path is None:
        pytest.skip("no fixture")

    monkeypatch.setattr(tw, "TEXT", "div[data-testid='thisSelectorIsGone']")

    page = browser.new_page()
    try:
        page.set_content(path.read_text(encoding="utf-8"))
        ctx = _Ctx(page, "twitter")
        posts = tw._harvest(ctx, 20, poster_override=None,
                            url_fallback="https://x.com")

        assert posts == [], "a dead text selector still produced posts"
        assert ctx.containers_seen > 0, (
            "containers were still rendered -- this is exactly the case "
            "_flag_extraction_failure turns into an error rather than 'ok'"
        )
    finally:
        page.close()
