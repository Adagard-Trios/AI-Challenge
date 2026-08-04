"""
src/scrapers/instagram.py
Instagram hashtag and profile collection.

Consolidated from utils.py:3885 / :4458 (byte-identical duplicates) and
profile_scrapers.py:651.

Runs on the MOBILE launch profile: Instagram serves a substantially simpler DOM
to mobile Safari, which is what these selectors target.

Caption handling: the rendered DOM truncates long captions, so full text comes
from Instagram's own media endpoint, reached through the page's request context
so it carries the same session and the same pacing as any other request. The
DOM text remains the fallback when that endpoint changes shape, which it does
often.
"""

from __future__ import annotations

import logging
from typing import List

from .base import ScrapeContext, ScrapeResult
from .text import extract_media_id_instagram, fetch_caption_via_private_api

logger = logging.getLogger("Roger.scrapers.instagram")

POST_LINK = "a[href*='/p/'], a[href*='/reel/']"
CAPTION_FALLBACK = "article h1, article span"

MIN_TEXT_LEN = 10
SCROLL_PASSES = 8


def _collect_links(ctx: ScrapeContext, max_items: int) -> List[str]:
    """Scroll the grid and gather post permalinks."""
    links: List[str] = []
    seen = set()

    for _ in range(SCROLL_PASSES):
        if len(links) >= max_items:
            break
        try:
            for anchor in ctx.page.locator(POST_LINK).all():
                href = anchor.get_attribute("href")
                if not href:
                    continue
                url = href if href.startswith("http") else f"https://www.instagram.com{href}"
                if url not in seen:
                    seen.add(url)
                    links.append(url)
                    if len(links) >= max_items:
                        break
        except Exception:
            pass
        ctx.scroll(pixels=2500)

    return links[:max_items]


def _caption_for(ctx: ScrapeContext, url: str) -> str:
    """Visit a post and return its caption, preferring the untruncated form."""
    ctx.goto(url)

    media_id = extract_media_id_instagram(ctx.page)
    caption = fetch_caption_via_private_api(ctx.page, media_id)
    if caption:
        return caption.strip()

    try:
        loc = ctx.page.locator(CAPTION_FALLBACK).first
        if loc.count():
            return (loc.inner_text() or "").strip()
    except Exception:
        pass
    return ""


def _harvest(ctx: ScrapeContext, links: List[str], poster: str) -> List[dict]:
    results: List[dict] = []

    for url in links:
        if ctx.posts_remaining() <= 0:
            logger.info("[instagram] daily post budget reached; stopping early")
            break
        try:
            text = _caption_for(ctx, url)
            if not text or len(text) < MIN_TEXT_LEN:
                continue
            results.append({
                "source": "Instagram",
                "poster": poster,
                "text": text,
                "url": url,
            })
        except Exception as exc:
            from .challenge import ChallengeDetected, SessionExpired
            if isinstance(exc, (ChallengeDetected, SessionExpired)):
                raise      # must reach run_scrape, never be swallowed per-post
            logger.debug("[instagram] skipped %s: %s", url, exc)
            continue

    ctx.count_posts(len(results))
    return results


def scrape_hashtag(ctx: ScrapeContext, keyword: str, max_items: int = 10) -> ScrapeResult:
    """Collect posts from a hashtag page."""
    tag = keyword.replace(" ", "").lstrip("#").lower()
    ctx.goto(f"https://www.instagram.com/explore/tags/{tag}/")

    links = _collect_links(ctx, max_items)
    if not links:
        return ScrapeResult(posts=[], status="error",
                            reason=f"no posts found for #{tag}")

    return ScrapeResult(posts=_harvest(ctx, links, "(Instagram User)"))


def scrape_profile(ctx: ScrapeContext, username: str, max_items: int = 10) -> ScrapeResult:
    """Collect recent posts from an account."""
    handle = username.lstrip("@")
    ctx.goto(f"https://www.instagram.com/{handle}/")

    links = _collect_links(ctx, max_items)
    if not links:
        return ScrapeResult(posts=[], status="error",
                            reason=f"no posts found for @{handle}")

    return ScrapeResult(posts=_harvest(ctx, links, f"@{handle}"))
