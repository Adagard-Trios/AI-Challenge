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
from typing import List, Optional

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


def clean_twitter_text(text: Optional[str]) -> str:
    """Strip t.co shorteners and feed chrome from tweet text."""
    if not text:
        return ""

    text = re.sub(r"Show more", "", text, flags=re.IGNORECASE)
    text = re.sub(r"https://t\.co/\w+", "", text)
    text = re.sub(r"pic\.twitter\.com/\w+", "", text)
    text = re.sub(r"\s+", " ", text)
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())

    return text.strip()


def extract_twitter_timestamp(tweet_element) -> Optional[str]:
    """
    Pull an ISO timestamp off a tweet article.

    Prefers the <time datetime="..."> attribute, which is absolute; falls back
    to the rendered relative text ("2h") only when the attribute is absent.
    """
    selectors = (
        "time",
        "[datetime]",
        "a[href*='/status/'] time",
        "div[data-testid='User-Name'] a[href*='/status/']",
    )
    for selector in selectors:
        try:
            loc = tweet_element.locator(selector)
            if loc.count() == 0:
                continue
            element = loc.first
            attr = element.get_attribute("datetime")
            if attr:
                return attr
            rendered = element.inner_text()
            if rendered:
                return rendered.strip()
        except Exception:
            continue
    return None


def parse_engagement(value: Optional[str]) -> int:
    """
    Parse an aria-label engagement count.

    Handles the abbreviated forms the UI renders at scale -- "1.2K likes",
    "3M reposts" -- which a bare \\d+ regex reads as 1 and 3 respectively.
    """
    if not value:
        return 0
    match = re.search(r"([\d,]+(?:\.\d+)?)\s*([KMB])?", value, flags=re.IGNORECASE)
    if not match:
        return 0
    number = float(match.group(1).replace(",", ""))
    suffix = (match.group(2) or "").upper()
    multiplier = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(suffix, 1)
    return int(number * multiplier)


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


def fetch_media_via_private_api(page, media_id: Optional[str]) -> dict:
    """
    Caption AND image URLs, from one call to the same endpoint.

    The response already contained the images; only the caption was being read
    and the rest discarded. Since every request against a logged-in account
    spends daily budget, fetching them separately would double the cost of the
    single most expensive thing we do.

    Returns {"caption": str|None, "images": [url, ...]} and never raises --
    Instagram reshapes this endpoint often, and a media fetch that fails must
    degrade to "no images", not abort a scrape.
    """
    out: dict = {"caption": None, "images": []}
    if not media_id:
        return out

    try:
        response = page.request.get(
            f"https://i.instagram.com/api/v1/media/{media_id}/info/",
            headers={
                "User-Agent": INSTAGRAM_APP_UA,
                "X-IG-App-ID": INSTAGRAM_APP_ID,
            },
            timeout=20000,
        )
        if response.status != 200:
            return out

        items = (response.json().get("items") or [])
        if not items:
            return out

        item = items[0]
        out["caption"] = (item.get("caption") or {}).get("text")

        # A carousel nests its images; a single post carries them at the top
        # level. Handle both rather than assuming, since a carousel silently
        # returning nothing is the kind of gap nobody notices.
        nodes = item.get("carousel_media") or [item]
        for node in nodes:
            url = _best_image_url(node)
            if url and url not in out["images"]:
                out["images"].append(url)

    except Exception:
        return out

    return out


# Where each platform puts the post's own photographs, as opposed to avatars,
# reaction icons and tracking pixels. Kept together so a rotted selector is
# fixed in one place -- the same reasoning as hygiene.py holding the launch
# profiles.
POST_IMAGE_SELECTORS = {
    "twitter": '[data-testid="tweetPhoto"] img, img[src*="/media/"]',
    "facebook": 'img[src*="scontent"]',
    "linkedin": (
        "img.update-components-image__image, "
        'img[src*="media.licdn.com/dms/image"]'
    ),
}

# Avatars and UI chrome share the same <img> tag as content. Filtering by URL
# is more durable than by CSS class, which these platforms rotate constantly.
_IMAGE_URL_REJECT = (
    "profile_images", "profile_pic", "/emoji/", "/sticker",
    "spacer", "transparent", "1x1", "rsrc.php",
)

# Below this the image is an icon or a thumbnail; OCR on it reads nothing and
# a perceptual hash of it collides with every other icon.
MIN_IMAGE_DIMENSION = 200


def extract_image_urls(container, platform: str, limit: int = 4) -> List[str]:
    """
    Photographs attached to one post.

    Best-effort by design: a missed image costs an OCR opportunity, while a
    raised exception costs the whole post. Every failure path here returns what
    has been found so far.
    """
    selector = POST_IMAGE_SELECTORS.get(platform.lower())
    if not selector:
        return []

    urls: List[str] = []
    try:
        images = container.locator(selector)
        for i in range(min(images.count(), limit * 3)):
            if len(urls) >= limit:
                break
            try:
                node = images.nth(i)
                url = node.get_attribute("src") or ""
                if not url.startswith("http"):
                    continue
                if any(bad in url for bad in _IMAGE_URL_REJECT):
                    continue

                # naturalWidth reflects the decoded image, not the CSS box, so
                # it rejects a large photo scaled down as well as a real icon.
                try:
                    width = node.evaluate("el => el.naturalWidth || 0")
                    height = node.evaluate("el => el.naturalHeight || 0")
                    if width and width < MIN_IMAGE_DIMENSION:
                        continue
                    if height and height < MIN_IMAGE_DIMENSION:
                        continue
                except Exception:
                    pass       # unmeasurable is not a reason to drop it

                if url not in urls:
                    urls.append(url)
            except Exception:
                continue
    except Exception:
        return urls

    return urls


def _best_image_url(node: dict) -> Optional[str]:
    """
    Highest-resolution candidate for one media node.

    Instagram orders `candidates` largest-first, but ordering is a convention
    rather than a guarantee, so pick by area. OCR on a thumbnail reads nothing
    useful, which makes this worth the few lines.
    """
    versions = (node.get("image_versions2") or {}).get("candidates") or []
    best, best_area = None, -1
    for candidate in versions:
        url = candidate.get("url")
        if not url:
            continue
        area = int(candidate.get("width") or 0) * int(candidate.get("height") or 0)
        if area > best_area:
            best, best_area = url, area
    return best
