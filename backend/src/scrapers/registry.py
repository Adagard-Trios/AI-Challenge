"""
src/scrapers/registry.py
One table mapping a scraper name to its implementation.

This is what lets the tool layer *delegate* rather than reimplement. The
previous arrangement had tool_factory.py defining its own copy of all eight
social scrapers as closures, which is how three divergent versions of the same
logic came to exist -- and why the copy that actually ran was the weakest.

Adding a platform means adding a row here, not another 200-line closure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Optional

from . import facebook, instagram, linkedin, twitter
from .base import ScrapeResult, run_scrape
from .credentials import get_credential


@dataclass(frozen=True)
class ScraperSpec:
    platform: str
    fn: Callable
    arg_name: str          # the caller-facing argument this scraper takes
    description: str


REGISTRY: Dict[str, ScraperSpec] = {
    "scrape_twitter": ScraperSpec(
        "twitter", twitter.scrape_search, "query",
        "Search X/Twitter for recent posts matching a query.",
    ),
    "scrape_twitter_profile": ScraperSpec(
        "twitter", twitter.scrape_profile, "username",
        "Collect recent posts from a specific X/Twitter account.",
    ),
    "scrape_linkedin": ScraperSpec(
        "linkedin", linkedin.scrape_search, "keywords",
        "Search LinkedIn content for posts matching keywords.",
    ),
    "scrape_linkedin_profile": ScraperSpec(
        "linkedin", linkedin.scrape_profile, "company_or_username",
        "Collect recent posts from a LinkedIn company page or person.",
    ),
    "scrape_facebook": ScraperSpec(
        "facebook", facebook.scrape_search, "keyword",
        "Search Facebook posts for a keyword.",
    ),
    "scrape_facebook_profile": ScraperSpec(
        "facebook", facebook.scrape_profile, "profile_url",
        "Collect recent posts from a Facebook page or profile URL.",
    ),
    "scrape_instagram": ScraperSpec(
        "instagram", instagram.scrape_hashtag, "keyword",
        "Collect Instagram posts for a hashtag.",
    ),
    "scrape_instagram_profile": ScraperSpec(
        "instagram", instagram.scrape_profile, "username",
        "Collect recent posts from an Instagram account.",
    ),
}


def unavailable(platform: str, reason: str) -> dict:
    """
    Uniform 'cannot run' payload.

    Deliberately not an exception: an agent asking for LinkedIn when LinkedIn is
    not connected is a normal state, not a failure, and the loop must continue
    to the other platforms.
    """
    return {
        "status": "unavailable",
        "platform": platform,
        "reason": reason,
        "count": 0,
        "results": [],
    }


def run(name: str, value: str, max_items: int = 20) -> dict:
    """
    Execute a registered scraper by name.

    Resolves the credential, runs under the pacing/health machinery in base.py,
    and returns a plain dict for the tool layer to serialise.
    """
    spec = REGISTRY.get(name)
    if spec is None:
        return unavailable("unknown", f"no scraper registered as {name!r}")

    credential = get_credential(spec.platform)
    if credential is None:
        return unavailable(
            spec.platform,
            f"No {spec.platform} account connected. Connect one in Settings -> "
            "Accounts; collection runs in the connector on your own machine.",
        )
    if credential.is_expired:
        return unavailable(
            spec.platform,
            f"The connected {spec.platform} session has expired. Reconnect it.",
        )

    result: ScrapeResult = run_scrape(credential, spec.fn, value, max_items=max_items)
    return result.as_dict()


def session_dependent_names() -> list:
    return sorted(REGISTRY)
