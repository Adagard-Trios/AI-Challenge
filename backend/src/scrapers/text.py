"""
src/scrapers/text.py
Post-text cleaners, one copy each.

These previously existed as: clean_linkedin_text x7 (utils.py:3266, 3806, 4260,
4286, 4320, 4347, 4371), clean_fb_text x2, extract_media_id_instagram x2 and
fetch_caption_via_private_api x2 -- all byte-identical duplicates, verified by
comparison rather than assumption.
"""

from __future__ import annotations

import re
from typing import Optional

from .hygiene import INSTAGRAM_APP_ID, INSTAGRAM_APP_UA


def clean_linkedin_text(text: Optional[str]) -> str:
    """Strip LinkedIn feed chrome from post text."""
    if not text:
        return ""

    # "…see more" / "See translation" affordances
    text = re.sub(r"…\s*see more", "", text, flags=re.IGNORECASE)
    text = re.sub(r"See translation", "", text, flags=re.IGNORECASE)
    # "3d • Edited •" relative-time headers
    text = re.sub(r"\b\d+[dwmo]\s*•\s*(Edited)?\s*•?", "", text)
    text = re.sub(r".+posted this", "", text)
    text = re.sub(r"\d+[\.,]?\d*\s*reactions", "", text)
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())

    return text.strip()


def clean_fb_text(text: Optional[str]) -> str:
    """Strip Facebook feed chrome from post text."""
    if not text:
        return ""

    # Runs of single letters, an artefact of Facebook's obfuscated markup
    text = re.sub(r"\b(?:[a-zA-Z]\s+){4,}\b", "", text)
    text = re.sub(r"(Facebook\s*){2,}", "", text)
    text = re.sub(r"Like\s*Comment\s*Share", "", text)
    text = re.sub(r"All reactions:\s*\d+\s*", "", text)
    text = re.sub(r"\n\d+\n", "\n", text)
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())

    return text.strip()


def extract_media_id_instagram(page) -> Optional[str]:
    """Pull an Instagram media id out of the rendered page HTML."""
    try:
        html = page.content()
    except Exception:
        return None

    match = re.search(r'"media_id":"(\d+)"', html)
    if match:
        return match.group(1)
    match = re.search(r'"id":"(\d+_\d+)"', html)
    if match:
        return match.group(1)
    return None


def fetch_caption_via_private_api(page, media_id: Optional[str]) -> Optional[str]:
    """
    Fetch a post caption from Instagram's media endpoint.

    Used because the rendered DOM truncates long captions. Issued through the
    page's own request context, so it carries the same session and is subject to
    the same pacing as any other request we make.
    """
    if not media_id:
        return None

    api_url = f"https://i.instagram.com/api/v1/media/{media_id}/info/"

    try:
        response = page.request.get(
            api_url,
            headers={
                "User-Agent": INSTAGRAM_APP_UA,
                "X-IG-App-ID": INSTAGRAM_APP_ID,
            },
            timeout=20000,
        )
        if response.status != 200:
            return None

        data = response.json()
        items = data.get("items") or []
        if items:
            caption = items[0].get("caption") or {}
            return caption.get("text")
    except Exception:
        # Endpoint shape changes often; a failed caption fetch must never abort
        # the scrape -- the DOM text is still there as a fallback.
        return None

    return None
