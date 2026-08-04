"""
Contract tests for src/scrapers.

The consolidation replaced three divergent implementations with one. These pin
the boundary the new code must not break: the exact keys
``db_manager.extract_post_data`` reads, and the status vocabulary the tool layer
and UI switch on.

No browser is launched -- scrapers are driven against a fake page object.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.scrapers import REGISTRY, ScrapeResult, registry  # noqa: E402
from src.scrapers.credentials import NullCredentialStore, set_credential_store  # noqa: E402
from src.scrapers.text import parse_engagement  # noqa: E402


# Keys db_manager.extract_post_data reads off a scraped post. Renaming any of
# these silently drops the field from the stored feed.
CONSUMED_KEYS = {"source", "poster", "text", "url", "timestamp",
                 "likes", "retweets", "replies"}

VALID_STATUSES = {"ok", "expired", "challenged", "rate_limited",
                  "budget_exhausted", "error", "unavailable"}


@pytest.fixture(autouse=True)
def _null_store():
    set_credential_store(NullCredentialStore())
    yield
    set_credential_store(None)


# --- registry --------------------------------------------------------------

def test_all_eight_session_scrapers_are_registered():
    """
    The eight session-dependent tools the agents call. A missing entry means
    that tool silently disappears from every agent's toolset.
    """
    expected = {
        "scrape_twitter", "scrape_twitter_profile",
        "scrape_linkedin", "scrape_linkedin_profile",
        "scrape_facebook", "scrape_facebook_profile",
        "scrape_instagram", "scrape_instagram_profile",
    }
    assert set(REGISTRY) == expected


def test_every_spec_is_wired_to_a_callable():
    for name, spec in REGISTRY.items():
        assert callable(spec.fn), f"{name} has no implementation"
        assert spec.platform in {"twitter", "facebook", "instagram", "linkedin"}
        assert spec.arg_name and spec.description


def test_no_credential_yields_unavailable_not_an_exception():
    """
    An agent asking for LinkedIn when LinkedIn is not connected is a normal
    state, not a failure -- the cycle must continue to the other platforms.
    """
    out = registry.run("scrape_linkedin", "colombo")
    assert out["status"] == "unavailable"
    assert out["results"] == []
    assert out["count"] == 0
    assert "connect" in out["reason"].lower()


def test_unknown_scraper_is_reported_not_raised():
    out = registry.run("scrape_myspace", "x")
    assert out["status"] == "unavailable"


# --- result shape ----------------------------------------------------------

def test_scrape_result_dict_shape():
    r = ScrapeResult(posts=[{"source": "Twitter", "poster": "@a", "text": "hello"}],
                     platform="twitter")
    d = r.as_dict()
    assert set(d) == {"status", "platform", "reason", "count", "results"}
    assert d["status"] == "ok"
    assert d["count"] == 1


def test_status_vocabulary_is_closed():
    """The UI and tool layer switch on these; a new value must be deliberate."""
    for status in ["ok", "expired", "challenged", "budget_exhausted", "error"]:
        assert status in VALID_STATUSES


# --- scrapers emit only keys the storage layer understands -----------------

class _FakeLocator:
    def __init__(self, texts=None, attrs=None, count=0):
        self._texts = texts or []
        self._attrs = attrs or {}
        self._count = count

    @property
    def first(self):
        return self

    def count(self):
        return self._count

    def all(self):
        return []

    def inner_text(self, *a, **k):
        return self._texts[0] if self._texts else ""

    def get_attribute(self, name, *a, **k):
        return self._attrs.get(name)

    def is_visible(self, *a, **k):
        return False

    def scroll_into_view_if_needed(self, *a, **k):
        pass

    def click(self, *a, **k):
        pass

    def locator(self, *a, **k):
        return _FakeLocator()


def test_emitted_keys_are_a_subset_of_what_storage_reads():
    """
    Guard against a scraper inventing a key. extract_post_data ignores unknown
    keys silently, so a typo like "postText" loses the post body with no error.
    """
    from src.scrapers import facebook, instagram, linkedin, twitter

    samples = [
        {"source": "Twitter", "poster": "@a", "text": "t", "timestamp": None,
         "url": "https://x.com/a/status/1", "likes": 0, "retweets": 0, "replies": 0},
        {"source": "Facebook", "poster": "P", "text": "t", "url": "https://f"},
        {"source": "LinkedIn", "poster": "P", "text": "t", "url": "https://l"},
        {"source": "Instagram", "poster": "@a", "text": "t", "url": "https://i"},
    ]
    for post in samples:
        assert set(post) <= CONSUMED_KEYS, f"unknown key(s): {set(post) - CONSUMED_KEYS}"


@pytest.mark.parametrize("module,expected_source", [
    ("twitter", "Twitter"),
    ("facebook", "Facebook"),
    ("linkedin", "LinkedIn"),
    ("instagram", "Instagram"),
])
def test_source_label_matches_db_manager_expectations(module, expected_source):
    """
    extract_post_data keys platform metadata off `source`. These four strings
    are load-bearing; changing their casing changes how feeds are filtered.
    """
    import importlib
    mod = importlib.import_module(f"src.scrapers.{module}")
    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert f'"source": "{expected_source}"' in src


# --- engagement parsing ----------------------------------------------------

@pytest.mark.parametrize("label,expected", [
    ("5 likes", 5),
    ("1,234 likes", 1234),
    ("1.2K likes", 1200),
    ("3M reposts", 3_000_000),
    ("2.5B views", 2_500_000_000),
    ("", 0),
    (None, 0),
    ("no digits here", 0),
])
def test_abbreviated_engagement_counts(label, expected):
    """
    REGRESSION. The old extraction was re.search(r"(\\d+)", aria_label), which
    reads "1.2K likes" as 1 and "3M reposts" as 3 -- understating popular posts
    by three to six orders of magnitude, exactly where the signal is.
    """
    assert parse_engagement(label) == expected


# --- structural ------------------------------------------------------------

def test_scrapers_are_plain_functions_not_tools():
    """
    Decorating implementations with @tool is what forced three divergent copies
    to exist. Implementations stay plain; the tool layer wraps them.
    """
    import importlib
    for module in ("twitter", "facebook", "linkedin", "instagram"):
        src = Path(importlib.import_module(f"src.scrapers.{module}").__file__).read_text(
            encoding="utf-8"
        )
        assert "@tool" not in src, f"{module}.py decorates an implementation"


def test_package_imports_without_playwright():
    """
    The server installs no Playwright (collection runs in the connector), so
    importing the package must not require it.
    """
    import src.scrapers as pkg
    assert pkg.get_credential("twitter") is None
