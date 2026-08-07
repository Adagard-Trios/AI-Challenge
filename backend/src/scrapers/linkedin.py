"""
src/scrapers/linkedin.py
LinkedIn feed-search and company/person collection.

Consolidated from utils.py:3281 (search) and profile_scrapers.py:802 (profile).

Removed in the move: the env-var password login at utils.py:3299-3319, which
read LINKEDIN_USER / LINKEDIN_PASSWORD and drove a scripted login when no
session file was present. Scripted password login is exactly the pattern
LinkedIn's challenge system is tuned to catch, it puts a plaintext password in
the server environment, and it cannot survive 2FA. Sessions now come from the
connector, captured by the user in a real browser.

Also fixed: the search scraper set every post's url to "https://www.linkedin.com",
so extract_post_data synthesised a no-url:// placeholder and the feed produced
unclickable entries. Real permalinks are resolved from the post URN.
"""

from __future__ import annotations

import logging
from typing import List, Optional
from urllib.parse import quote

from .base import ScrapeContext, ScrapeResult
from .text import clean_linkedin_text, extract_image_urls

logger = logging.getLogger("Roger.scrapers.linkedin")

POST = "div.feed-shared-update-v2, li.artdeco-card"
TEXT = "div.update-components-text span.break-words, span.break-words"
POSTER = "span.update-components-actor__name span[dir='ltr']"
SEE_MORE = "button.feed-shared-inline-show-more-text__see-more-less-toggle"

MIN_TEXT_LEN = 20
MAX_BARREN_SCROLLS = 4


def _expand(ctx: ScrapeContext) -> None:
    """LinkedIn collapses long posts behind a see-more toggle, like Facebook."""
    try:
        for button in ctx.page.locator(SEE_MORE).all():
            try:
                if button.is_visible(timeout=500):
                    button.click(timeout=1500)
            except Exception:
                continue
    except Exception:
        pass


def _permalink(post) -> Optional[str]:
    """
    Resolve a post permalink from its URN.

    LinkedIn puts the activity URN on the container as data-urn; the canonical
    permalink is /feed/update/<urn>/.
    """
    for attr in ("data-urn", "data-id"):
        try:
            urn = post.get_attribute(attr)
            if urn and "activity" in urn:
                return f"https://www.linkedin.com/feed/update/{urn}/"
        except Exception:
            continue
    try:
        link = post.locator("a[href*='/feed/update/']").first
        if link.count():
            href = link.get_attribute("href")
            if href:
                return href if href.startswith("http") else f"https://www.linkedin.com{href}"
    except Exception:
        pass
    return None


def _harvest(ctx: ScrapeContext, max_items: int, fallback_url: str) -> List[dict]:
    results: List[dict] = []
    seen = set()
    barren = 0

    while len(results) < max_items and barren < MAX_BARREN_SCROLLS:
        _expand(ctx)

        try:
            posts = ctx.page.locator(POST).all()
            ctx.note_containers(len(posts))
        except Exception:
            break

        found = 0
        for post in posts:
            if len(results) >= max_items:
                break
            try:
                text_loc = post.locator(TEXT).first
                if not text_loc.count():
                    continue
                text = clean_linkedin_text(text_loc.inner_text())
                if not text or len(text) < MIN_TEXT_LEN:
                    continue

                key = text[:80]
                if key in seen:
                    continue
                seen.add(key)

                poster = "Unknown"
                try:
                    poster_loc = post.locator(POSTER).first
                    if poster_loc.count():
                        poster = (poster_loc.inner_text() or "").strip() or "Unknown"
                except Exception:
                    pass

                results.append({
                    "source": "LinkedIn",
                    "poster": poster,
                    "text": text,
                    "url": _permalink(post) or fallback_url,
                    "images": extract_image_urls(post, "linkedin"),
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


def scrape_search(ctx: ScrapeContext, keywords: str, max_items: int = 10) -> ScrapeResult:
    """Collect posts matching keywords from LinkedIn content search."""
    url = (
        "https://www.linkedin.com/search/results/content/"
        f"?keywords={quote(keywords)}&sortBy=%22date_posted%22"
    )
    ctx.goto(url)

    try:
        ctx.page.wait_for_selector(POST, timeout=20000)
    except Exception:
        return ScrapeResult(posts=[], status="error",
                            reason=f"no posts rendered for {keywords!r}")

    return ScrapeResult(posts=_harvest(ctx, max_items, url))


def scrape_profile(ctx: ScrapeContext, target: str, max_items: int = 10) -> ScrapeResult:
    """
    Collect recent activity for a company or person.

    ``target`` may be a bare slug or a full URL.
    """
    if target.startswith("http"):
        base = target.rstrip("/")
    else:
        slug = target.strip("/")
        kind = "company" if "/" not in slug else ""
        base = f"https://www.linkedin.com/{kind or 'in'}/{slug}"

    url = f"{base}/posts/"
    ctx.goto(url)

    try:
        ctx.page.wait_for_selector(POST, timeout=20000)
    except Exception:
        return ScrapeResult(posts=[], status="error",
                            reason=f"no posts rendered at {url}")

    return ScrapeResult(posts=_harvest(ctx, max_items, url))
