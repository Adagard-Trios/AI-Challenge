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
        # "Paced" and "not connected" are different facts and used to produce
        # the same message. On a 60-second agent loop against a 15-minute
        # cooling-off window, a connected account reported "No account
        # connected. Connect one in Settings" fourteen times out of fifteen --
        # telling the user to fix something that was not broken, and telling
        # the agent there was nothing to collect from.
        paced, wait = _pacing_state(spec.platform)
        if paced:
            return {
                "status": "paced",
                "platform": spec.platform,
                "reason": (
                    f"{spec.platform} was collected recently and is inside its "
                    f"cooling-off window; about {wait}s left. The account is "
                    f"connected and working -- this pacing is what keeps it "
                    f"that way."
                ),
                "retry_after_seconds": wait,
                "count": 0,
                "results": [],
            }

        return unavailable(
            spec.platform,
            f"No {spec.platform} account connected. Connect one in Settings -> "
            "Accounts.",
        )
    if credential.is_expired:
        return unavailable(
            spec.platform,
            f"The connected {spec.platform} session has expired. Reconnect it.",
        )

    result: ScrapeResult = run_scrape(credential, spec.fn, value, max_items=max_items)
    payload = result.as_dict()
    _read_images(payload)
    return payload


def _pacing_state(platform: str) -> tuple:
    """
    (is_paced, seconds_remaining) for a platform, asked of whichever credential
    store is installed.

    Duck-typed rather than importing the bridge: a store that does not pace
    simply lacks these methods, and the answer is "not paced" -- which is
    correct for NullCredentialStore and the file-backed one.
    """
    try:
        from src.scrapers.credentials import get_credential_store

        store = get_credential_store()
        if not hasattr(store, "is_paced"):
            return False, 0
        if not store.is_paced(platform):
            return False, 0
        return True, getattr(store, "seconds_until_ready", lambda _: 0)(platform)
    except Exception:  # noqa: BLE001
        return False, 0


def _read_images(payload: dict) -> None:
    """
    Fold the text inside each post's images into that post's text.

    Placed here rather than in a caller because this is the one seam every
    scrape passes through -- the agent's LangChain tools, the dashboard's
    "Collect now", and the selftest all arrive via run(). Enriching in a caller
    is how the previous gap happened: images were read on the Collect-now path
    and silently discarded on the agent loop, so automatic collection captured
    image URLs and threw them away.

    The agent then reasons over the post text with the image text already in
    it, which is what makes an image-only flood notice classifiable at all.

    Best-effort throughout: OCR is an enrichment, and losing it must never cost
    the posts.
    """
    posts = payload.get("posts")
    if not posts:
        return

    if not any(p.get("images") for p in posts if isinstance(p, dict)):
        return

    try:
        from src.images.pipeline import process_image
    except Exception:  # noqa: BLE001
        return

    for post in posts:
        if not isinstance(post, dict):
            continue
        urls = post.get("images") or []
        if not urls:
            continue

        extracted = []
        for url in urls[:4]:
            try:
                image = process_image(url)
            except Exception:  # noqa: BLE001
                continue
            if image.has_text:
                extracted.append(image.ocr_text.strip())
            # Carried so a caller that persists the post can record the hash
            # without fetching the image a second time.
            post.setdefault("image_hashes", []).append(image.phash)

        if extracted:
            # Labelled, so a reader can tell a typed caption from a machine
            # reading a photograph -- they warrant different trust.
            joined = "\n[text in image] ".join(extracted)
            post["text"] = f"{post.get('text', '')}\n\n[text in image] {joined}".strip()
            post["ocr_text"] = "\n".join(extracted)


def session_dependent_names() -> list:
    return sorted(REGISTRY)
