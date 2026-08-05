"""
src/scrapers/twitter.py
X / Twitter search and profile collection.

Consolidated from three copies. What each contributed, and what changed:

- ``utils.py:3522`` had the search-URL fallback chain and promoted-post filtering.
- ``profile_scrapers.py:45`` was the only copy that extracted engagement counts
  and resolved a real per-post URL -- and it never ran, because agent nodes
  reach scrapers through ``create_tool_set()``, which used the tool_factory copy.
- ``tool_factory.py:276`` was the copy that actually executed, and the weakest.

Both functions here now extract engagement and real URLs. The search scraper
previously hard-coded ``url: "https://x.com"`` for every post, which made
``extract_post_data`` synthesise a ``no-url://`` placeholder and left the feed
with unclickable entries.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from .base import ScrapeContext, ScrapeResult
from .text import (
    clean_twitter_text,
    extract_twitter_timestamp,
    parse_engagement,
)

logger = logging.getLogger("Roger.scrapers.twitter")

TWEET = "article[data-testid='tweet']"
TEXT = "div[data-testid='tweetText']"
USER = "div[data-testid='User-Name']"
SHOW_MORE = "[data-testid='tweet-text-show-more-link']"

POPUP_DISMISS = (
    "[data-testid='app-bar-close']",
    "[aria-label='Close']",
    "button:has-text('Not now')",
)

MIN_TEXT_LEN = 20
MAX_BARREN_SCROLLS = 5


def _dismiss_popups(ctx: ScrapeContext) -> None:
    for selector in POPUP_DISMISS:
        try:
            loc = ctx.page.locator(selector)
            if loc.count() and loc.first.is_visible(timeout=800):
                loc.first.click(timeout=2000)
        except Exception:
            continue


def _expand_truncated(ctx: ScrapeContext) -> None:
    """Click 'Show more' so long posts are captured whole, not truncated."""
    try:
        for button in ctx.page.locator(SHOW_MORE).all():
            try:
                if button.is_visible(timeout=500):
                    button.click(timeout=1500)
            except Exception:
                continue
    except Exception:
        pass


def _engagement(tweet) -> dict:
    out = {"likes": 0, "retweets": 0, "replies": 0}
    for key, testid in (("likes", "like"), ("retweets", "retweet"), ("replies", "reply")):
        try:
            loc = tweet.locator(f"[data-testid='{testid}']")
            if loc.count():
                out[key] = parse_engagement(loc.first.get_attribute("aria-label"))
        except Exception:
            continue
    return out


def _post_url(tweet, fallback: str) -> str:
    """Resolve the permalink. The search scraper used to hard-code the site root."""
    try:
        link = tweet.locator("a[href*='/status/']").first
        if link.count():
            href = link.get_attribute("href")
            if href:
                return href if href.startswith("http") else f"https://x.com{href}"
    except Exception:
        pass
    return fallback


def _is_promoted(tweet) -> bool:
    try:
        return bool(
            tweet.locator("span:has-text('Promoted')").count()
            or tweet.locator("span:has-text('Ad')").count()
        )
    except Exception:
        return False


def _harvest(ctx: ScrapeContext, max_items: int, *, poster_override: Optional[str],
             url_fallback: str) -> List[dict]:
    results: List[dict] = []
    seen = set()
    barren = 0

    while len(results) < max_items and barren < MAX_BARREN_SCROLLS:
        _expand_truncated(ctx)

        try:
            tweets = ctx.page.locator(TWEET).all()
            ctx.note_containers(len(tweets))
        except Exception:
            break

        found_this_pass = 0
        for tweet in tweets:
            if len(results) >= max_items:
                break
            try:
                if _is_promoted(tweet):
                    continue

                text = ""
                text_loc = tweet.locator(TEXT).first
                if text_loc.count():
                    text = clean_twitter_text(text_loc.inner_text())

                if not text or len(text) < MIN_TEXT_LEN:
                    continue

                if poster_override:
                    poster = poster_override
                else:
                    poster = "Unknown"
                    user_loc = tweet.locator(USER).first
                    if user_loc.count():
                        poster = user_loc.inner_text().split("\n")[0].strip() or "Unknown"

                timestamp = extract_twitter_timestamp(tweet)
                key = f"{poster}|{text[:60]}|{timestamp}"
                if key in seen:
                    continue
                seen.add(key)

                results.append({
                    "source": "Twitter",
                    "poster": poster,
                    "text": text,
                    "timestamp": timestamp,
                    "url": _post_url(tweet, url_fallback),
                    **_engagement(tweet),
                })
                found_this_pass += 1

            except Exception:
                continue

        if len(results) >= max_items:
            break

        barren = 0 if found_this_pass else barren + 1
        ctx.scroll()

    ctx.count_posts(len(results))
    return results


def scrape_search(ctx: ScrapeContext, query: str, max_items: int = 20) -> ScrapeResult:
    """
    Collect posts matching a search query.

    Tries the live-filter URL first, then progressively plainer forms -- X
    intermittently rejects ``f=live`` for some sessions.
    """
    from urllib.parse import quote

    q = quote(query)
    candidates = (
        f"https://x.com/search?q={q}&src=typed_query&f=live",
        f"https://x.com/search?q={q}&src=typed_query",
        f"https://x.com/search?q={q}",
    )

    for url in candidates:
        try:
            ctx.goto(url)          # paced; raises on challenge/expiry
        except (TimeoutError, Exception) as exc:
            # Challenge and expiry propagate out of run_scrape; only navigation
            # trouble is worth trying the next URL for.
            from .challenge import ChallengeDetected, SessionExpired
            if isinstance(exc, (ChallengeDetected, SessionExpired)):
                raise
            logger.warning("[twitter] %s failed: %s", url, exc)
            continue

        _dismiss_popups(ctx)
        try:
            ctx.page.wait_for_selector(TWEET, timeout=15000)
        except Exception:
            logger.warning("[twitter] no tweets rendered at %s", url)
            continue

        posts = _harvest(ctx, max_items, poster_override=None,
                         url_fallback="https://x.com")
        return ScrapeResult(posts=posts)

    return ScrapeResult(posts=[], status="error",
                        reason="no search URL returned results")


def scrape_profile(ctx: ScrapeContext, username: str, max_items: int = 20) -> ScrapeResult:
    """Collect a specific account's recent posts."""
    handle = username.lstrip("@")
    profile_url = f"https://x.com/{handle}"

    ctx.goto(profile_url)
    _dismiss_popups(ctx)

    try:
        ctx.page.wait_for_selector(TWEET, timeout=15000)
    except Exception:
        return ScrapeResult(posts=[], status="error",
                            reason=f"no posts rendered for @{handle}")

    posts = _harvest(ctx, max_items, poster_override=f"@{handle}",
                     url_fallback=profile_url)
    return ScrapeResult(posts=posts)
