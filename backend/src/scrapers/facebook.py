"""
src/scrapers/facebook.py
Facebook post search and profile collection.

BUG FIX carried by this module. ``scrape_facebook`` was defined twice in
utils.py -- at :4017 and again at :4590. Python binds the last definition, so
:4590 was the live one, and it had **dropped** ``expand_all_see_more()``.
Facebook truncates any post beyond a few lines behind a "See more" control, so
every long post was being captured as a fragment ending in "... See more" and
stored that way. The shadowed :4017 copy still had the expansion.

Restoring it is a correctness fix, not a preference: the feed has been silently
losing the body of its longest, most substantive posts.
"""

from __future__ import annotations

import logging
from typing import List
from urllib.parse import quote

from .base import ScrapeContext, ScrapeResult
from .text import clean_fb_text

logger = logging.getLogger("Roger.scrapers.facebook")

MESSAGE = "div[data-ad-preview='message']"

# Facebook rotates obfuscated class names constantly, so poster attribution
# needs several fallbacks. Ordered most- to least-reliable.
POSTER_SELECTORS = (
    "h3 a[role='link'] span",
    "h4 a[role='link'] span",
    "span[dir='auto'] a[role='link'] strong span",
    "a[role='link'][aria-label]",
    "strong span",
    "h3 span",
    "h4 span",
    "span.x193iq5w a",
    "a[href*='/user/']",
)

SEE_MORE_SELECTORS = (
    "div[role='button'] span:text-is('See more')",
    "div[role='button']:has-text('See more')",
    "span:text-is('See more')",
    "span:text-is('... See more')",
    "span:text-is('...See more')",
    "[role='button']:has-text('See more')",
    "div.x1i10hfl:has-text('See more')",
    "text='See more'",
    "text='... See more'",
)

MIN_TEXT_LEN = 20
MAX_BARREN_SCROLLS = 4


def expand_all_see_more(ctx: ScrapeContext) -> int:
    """
    Click every visible "See more" so post bodies are captured whole.

    Without this, long posts are stored truncated at the fold. Returns how many
    were expanded, which is worth logging: a sudden drop to zero across runs is
    the earliest signal that these selectors have rotted.
    """
    clicked = 0
    for selector in SEE_MORE_SELECTORS:
        try:
            buttons = ctx.page.locator(selector).all()
        except Exception:
            continue
        for button in buttons:
            try:
                if not button.is_visible(timeout=500):
                    continue
                button.scroll_into_view_if_needed(timeout=1500)
                button.click(force=True, timeout=2000)
                clicked += 1
            except Exception:
                continue
    if clicked:
        logger.debug("[facebook] expanded %d truncated post(s)", clicked)
    return clicked


def _poster_for(ctx: ScrapeContext, message_element) -> str:
    """Walk up to the post container, then try each attribution selector."""
    try:
        container = message_element.locator(
            "xpath=ancestor::div[contains(@class,'x1yztbdb')][1]"
        )
        if not container.count():
            container = message_element.locator("xpath=ancestor::div[@role='article'][1]")
        if not container.count():
            return "Unknown"

        for selector in POSTER_SELECTORS:
            try:
                loc = container.first.locator(selector).first
                if not loc.count():
                    continue
                if selector.endswith("[aria-label]"):
                    value = loc.get_attribute("aria-label")
                else:
                    value = loc.inner_text()
                value = (value or "").strip().split("\n")[0]
                if value and len(value) < 100:
                    return value
            except Exception:
                continue
    except Exception:
        pass
    return "Unknown"


def _harvest(ctx: ScrapeContext, max_items: int, source_url: str) -> List[dict]:
    results: List[dict] = []
    seen = set()
    barren = 0

    while len(results) < max_items and barren < MAX_BARREN_SCROLLS:
        expand_all_see_more(ctx)

        try:
            messages = ctx.page.locator(MESSAGE).all()
        except Exception:
            break

        found = 0
        for message in messages:
            if len(results) >= max_items:
                break
            try:
                text = clean_fb_text(message.inner_text())
                if not text or len(text) < MIN_TEXT_LEN:
                    continue

                key = text[:80]
                if key in seen:
                    continue
                seen.add(key)

                results.append({
                    "source": "Facebook",
                    "poster": _poster_for(ctx, message),
                    "text": text,
                    "url": source_url,
                })
                found += 1
            except Exception:
                continue

        if len(results) >= max_items:
            break

        barren = 0 if found else barren + 1
        ctx.scroll()

    ctx.count_posts(len(results))
    return results


def scrape_search(ctx: ScrapeContext, keyword: str, max_items: int = 10) -> ScrapeResult:
    """Collect posts matching a keyword from Facebook post search."""
    url = f"https://www.facebook.com/search/posts?q={quote(keyword)}"
    ctx.goto(url)

    try:
        ctx.page.wait_for_selector(MESSAGE, timeout=20000)
    except Exception:
        return ScrapeResult(posts=[], status="error",
                            reason=f"no posts rendered for {keyword!r}")

    return ScrapeResult(posts=_harvest(ctx, max_items, url))


def scrape_profile(ctx: ScrapeContext, profile_url: str, max_items: int = 10) -> ScrapeResult:
    """Collect recent posts from a specific page or profile."""
    ctx.goto(profile_url)

    try:
        ctx.page.wait_for_selector(MESSAGE, timeout=20000)
    except Exception:
        return ScrapeResult(posts=[], status="error",
                            reason=f"no posts rendered at {profile_url}")

    return ScrapeResult(posts=_harvest(ctx, max_items, profile_url))
