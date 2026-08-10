"""
Gazette summarisation and story headlines.

Both existed as a slice of raw text presented as though it were a summary:

    story.title = summary[:200]          -> a paragraph, cut mid-word
    gazette.summary = pdf_text[:500]     -> the PDF's index page

The gazette case was the more misleading of the two. The PDF was downloaded in
full -- 194,466 characters -- and then the first 500 were taken, which on every
gazette are dot leaders and page numbers. The agent, handed that, wrote "a
gazette has been published, signalling ongoing legislative activity, though the
specific provisions remain largely unparsed". The provisions were never
unparsed. They were fetched and discarded.

The network- and model-dependent parts are exercised live elsewhere; these are
the pure functions, so they run anywhere.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# --- story headlines --------------------------------------------------------

@pytest.mark.parametrize(
    "summary,expected_absent",
    [
        ("Sri Lanka Political Summary: **Executive Summary** The latest Sri "
         "Lankan Government Gazette has been published.", "**"),
        ("Business Intelligence Summary: The competitive landscape reveals a "
         "lack of engagement.", "Summary:"),
    ],
)
def test_headlines_carry_no_markdown_or_domain_prefix(summary, expected_absent):
    from src.intelligence.stories import headline_from

    assert expected_absent not in headline_from(summary)


def test_a_headline_is_not_cut_mid_word():
    """
    REGRESSION. summary[:200] produced "...though the specific provi", which
    reads as a rendering fault rather than an abbreviation.
    """
    from src.intelligence.stories import headline_from

    long_summary = (
        "The latest Sri Lankan Government Gazette dated 31 July 2026 has been "
        "published, signalling ongoing legislative activity, though the "
        "specific provisions remain largely unparsed in the current dataset."
    )
    headline = headline_from(long_summary)
    body = headline.rstrip("…").strip()
    # Every whole word in the headline must be a whole word in the source.
    assert all(word in long_summary.split() for word in body.split()[-1:])
    assert not headline.endswith("provi")


def test_headline_is_idempotent():
    """It runs on the way out as well as in, so stories already stored are
    cleaned without a migration. That only works if re-running is a no-op."""
    from src.intelligence.stories import headline_from

    for text in (
        "Sri Lanka Political Summary: **Executive Summary** A gazette was "
        "published with several provisions and notices attached to it.",
        "Flood warning issued for the Kelani basin",
        "",
    ):
        once = headline_from(text)
        assert headline_from(once) == once


# --- gazette language -------------------------------------------------------

@pytest.mark.parametrize(
    "filename,expected",
    [
        ("Gazette-2026-07-24-S.pdf", "sinhala"),
        ("Gazette-2026-07-24-T.pdf", "tamil"),
        ("Gazette-2026-07-17-E.pdf", "english"),
        # REGRESSION: the part-numbered variants. endswith("S.pdf") missed
        # these, and the variable defaulted to "english", so Sinhala text was
        # handed downstream labelled English -- and preferred over real English.
        ("Gazette-2026-07-31-Siii.pdf", "sinhala"),
        ("Gazette-2026-07-17-Sii.pdf", "sinhala"),
        ("Gazette-2026-07-17-Tii.pdf", "tamil"),
    ],
)
def test_gazette_language_comes_from_the_filename(filename, expected):
    from src.utils.utils import _gazette_language

    assert _gazette_language(f"https://www.gazette.lk/dl/Gazette/07/{filename}") == expected


# --- gazette index stripping ------------------------------------------------

def test_the_index_pages_are_dropped():
    """
    The first pages of every gazette are an index of dot leaders. Summarising
    them yields a summary of the table of contents.
    """
    from src.utils.utils import strip_gazette_index

    raw = "\n".join([
        "Notices calling for Tenders … … … … … 1234",
        "Examinations, Results … … … … 1240",
        "   ",
        "1256",
        "The Minister of Lands has ordered the acquisition of land at Yekattha.",
    ])
    kept = strip_gazette_index(raw)

    assert "Minister of Lands" in kept
    assert "…" not in kept
    assert "1256" not in kept.splitlines()


def test_sampling_reaches_past_the_publication_rules():
    """
    Taking the first N characters summarised the gazette's own publication
    rules -- submission deadlines and where to send notices -- so the model
    reported that the gazette "explains the rules for publishing the Gazette
    itself", which is true and useless.
    """
    from src.utils.utils import _sample_gazette

    body = ("RULES FOR PUBLICATION " * 400) + ("ACTUAL NOTICE CONTENT " * 400)
    sampled = _sample_gazette(body)

    assert "ACTUAL NOTICE CONTENT" in sampled


def test_indic_text_gets_a_smaller_character_budget():
    """
    Sinhala costs roughly three times more tokens per character than English.
    A 14,000-character Sinhala sample measured 10,269 tokens against an
    8,000/minute limit and was rejected with HTTP 413.
    """
    from src.utils.utils import _sample_gazette, _is_indic

    sinhala = "අනුමැතිය ලබා දීම සඳහා ඉදිරිපත් කරන ලද " * 900
    english = "The Minister has approved the acquisition of land " * 900

    assert _is_indic(sinhala) is True
    assert _is_indic(english) is False
    assert len(_sample_gazette(sinhala)) < len(_sample_gazette(english))


def test_an_unsummarised_gazette_returns_none_rather_than_raw_pdf():
    """
    No summary is an honest answer. Raw PDF text presented as a summary is not,
    and that is what reached the feed:

        0000 - B 82815 - (2026/07) E - 01 පිටුව පිටුව තනතුරු ඇබෑෑර්තු … … -
    """
    from src.utils.utils import summarise_gazette

    assert summarise_gazette("", title="x") is None
    assert summarise_gazette("too short to be a gazette", title="x") is None
