"""
src/intelligence/summaries.py
Turning a scraped post into something readable.

Every domain agent builds its insight summary the same way:

    f"{district}: {post_text[:200]}"

which produces four visible problems, all of them reaching the dashboard:

1. **Cut mid-word.** A hard 200-character slice with no word boundary and no
   ellipsis, so summaries end "...near Kadawat" and the reader cannot tell
   whether the text was truncated or the scrape was broken.
2. **Run-on text.** LinkedIn and Facebook cleaners preserve newlines, and HTML
   collapses those to single spaces, so a multi-paragraph post renders as one
   long sentence with no punctuation between the parts.
3. **Scrape junk.** RT prefixes, @handle pile-ups, trailing hashtag clusters and
   surviving URLs, all of which are noise to a reader and to the LLM filter.
4. **Whitespace.** Doubled spaces and non-breaking spaces from the platforms'
   own markup.

The LLM filter rewrites most summaries into `enhanced_summary`, so these were
mostly visible on events the model could not judge -- which, since that is
exactly when a reader most needs to read the raw text themselves, is the worst
possible time for it to be unreadable.

Deliberately conservative: this removes chrome, never content. When in doubt it
leaves text alone, because a summary that keeps a stray hashtag is a much
smaller problem than one that has silently dropped a fact.
"""

from __future__ import annotations

import re
from typing import Optional

# Retweet / quote prefixes. Anchored to the start; "RT" mid-sentence is a word.
_RT_PREFIX = re.compile(r"^\s*(RT|QT)\s*[@:]\s*[\w.]+\s*:?\s*", re.IGNORECASE)

# Leading @handle pile-ups: "@a @b @c the actual point" -> "the actual point".
# Only at the start, and only when several are stacked, so a post that is
# genuinely addressed to someone keeps its meaning.
_LEADING_HANDLES = re.compile(r"^(?:\s*@[\w.]{2,30}\b)+\s*")

# Trailing hashtag clusters: "...stay safe #SriLanka #flood #weather".
# Only at the END, so a hashtag used inline as a word survives.
_TRAILING_HASHTAGS = re.compile(r"(?:\s*#[\w]+\b)+\s*$")

# Link shorteners and bare URLs that survived platform-specific cleaning.
_URLS = re.compile(r"https?://\S+|www\.\S+|\b\w+\.co/\w+")

# Platform chrome that appears in extracted text.
_CHROME = re.compile(
    r"\b(Show more|See more|See translation|Translate post|Read more|"
    r"Show this thread|Quote Tweet)\b[.:\s]*",
    re.IGNORECASE,
)

# Non-breaking and zero-width characters that platforms sprinkle through markup.
_INVISIBLES = str.maketrans({
    " ": " ", "​": "", "‌": "", "‍": "", "﻿": "",
})

_SENTENCE_END = re.compile(r"[.!?:;]$")


def clean_post_text(text: Optional[str]) -> str:
    """
    Strip scrape chrome and normalise whitespace, preserving the content.

    Line breaks become sentence breaks rather than disappearing: HTML collapses
    a newline to a space, so "Terminal 2 is closed\\nContact ops" renders as
    "Terminal 2 is closed Contact ops". A full stop is inserted where the author
    clearly ended a thought and did not punctuate it.
    """
    if not text:
        return ""

    text = str(text).translate(_INVISIBLES)
    text = _RT_PREFIX.sub("", text)
    text = _CHROME.sub(" ", text)
    text = _URLS.sub("", text)
    text = _LEADING_HANDLES.sub("", text)

    # Rebuild paragraph by paragraph so line breaks become punctuation.
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]

    joined = []
    for i, line in enumerate(lines):
        if i and not _SENTENCE_END.search(joined[-1]):
            joined[-1] = joined[-1] + "."
        joined.append(line)

    text = " ".join(joined)

    text = _TRAILING_HASHTAGS.sub("", text)
    text = re.sub(r"\s+", " ", text)
    # Whitespace left in front of punctuation by the removals above.
    text = re.sub(r"\s+([.,!?;:])", r"\1", text)

    return text.strip()


# What a domain agent's LLM summary is allowed to run to.
#
# Was 300, inline in five agent nodes. These summaries are executive-summary
# style and routinely cover several rivers, districts or indicators, so 300
# landed mid-sentence on roughly a third of them -- 20 of 56 stored feeds ended
# in an ellipsis, and the feed read as though collection had failed rather than
# as though the text had been shortened.
#
# Still bounded: a runaway model response should not become an unbounded feed
# card or an unbounded embedding. 1200 fits the summaries actually being
# produced while leaving the cap in place for anything pathological.
AGENT_SUMMARY_LIMIT = 1200


def truncate(text: str, limit: int = 200) -> str:
    """
    Cut on a sentence boundary where possible, a word boundary otherwise, and
    say that it was cut.

    `text[:200]` ends mid-word with no ellipsis, which reads as a broken scrape
    rather than a shortened one. A word-boundary cut fixed that but still ended
    mid-thought -- "Both rivers are…" told a reader nothing about the rivers.
    Ending on a full stop costs a few characters and leaves a complete
    statement, which is the difference between a shortened summary and a
    partial one.
    """
    if not text or len(text) <= limit:
        return text

    window = text[: limit + 1]

    # Prefer the last sentence end. Only accept it if it keeps most of the
    # budget -- otherwise a summary whose first sentence is very short would
    # throw away everything after it.
    sentence_end = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
    if sentence_end >= int(limit * 0.6):
        return window[: sentence_end + 1]

    cut = window.rfind(" ")

    # Keep at least half the budget; otherwise a very long token would leave a
    # uselessly short summary.
    if cut < limit // 2:
        return text[:limit].rstrip() + "…"

    return window[:cut].rstrip(" ,;:.-") + "…"


def build_summary(prefix: str, text: Optional[str], limit: int = 200) -> str:
    """
    The one call every domain agent should make.

    `prefix` is the label the agent puts in front ("Gampaha", "Sri Lanka
    Economy (Banking)"). The limit applies to the post text, not the prefix, so
    a long label cannot silently eat the content.
    """
    cleaned = truncate(clean_post_text(text), limit)
    prefix = (prefix or "").strip().rstrip(":")

    if not cleaned:
        return prefix
    if not prefix:
        return cleaned
    return f"{prefix}: {cleaned}"
