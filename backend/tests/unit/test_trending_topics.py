"""
What counts as a trending topic.

A topic used to be the first five words of the event summary:

    words = summary.split()[:5]

That is a prefix, not a topic, and the dashboard showed exactly that. "Sri
Lanka Economy (Sri Lanka" trended at 50x -- five words ending inside a
parenthesis it never closed -- next to "passed", "social" and "presence", which
are whatever incidental words happened to land in position four.

A bad topic is worse than no topic: the panel shows five, so each piece of
noise evicts something real.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _topics(summary, **extra):
    from src.nodes.combinedAgentNode import topics_from_event

    return topics_from_event({"summary": summary, **extra})


def test_extracted_entities_are_preferred():
    """
    The pipeline already extracts entities and canonicalises them through the
    taxonomy, so five spellings of one place are one entry. Those ARE topics
    and re-deriving them from text would be strictly worse.
    """
    topics = _topics(
        "irrelevant text",
        entities=[{"type": "PLACE", "name": "Colombo Port"},
                  {"type": "ORG", "name": "Ministry of Lands"}],
    )
    assert topics == ["Colombo Port", "Ministry of Lands"]


def test_the_source_label_is_not_the_subject():
    """
    REGRESSION. Scrapers prefix "Sri Lanka Economy (Sri Lanka Economy): " and
    the first five words of that is "Sri Lanka Economy (Sri Lanka" -- which is
    what trended at 50x, unbalanced parenthesis and all.
    """
    topics = _topics(
        "Sri Lanka Economy (Sri Lanka Economy): Now its with Asiri Hospitals?"
    )
    assert "Asiri Hospitals" in topics
    assert not any("(" in t for t in topics)
    assert not any(t.lower().startswith("sri lanka economy") for t in topics)


@pytest.mark.parametrize("summary", [
    "The absence of customer sentiment data indicates competitors may not be "
    "monitoring feedback, posing a low-severity risk.",
    "Limited digital presence suggests competitors may be underinvesting in "
    "digital marketing.",
])
def test_generic_prose_yields_no_topics_at_all(summary):
    """
    REGRESSION for "competitors 40x", "social 20x", "presence 20x".

    Returning nothing is correct here. Filling a quota with whatever words were
    available is what put those on the dashboard.
    """
    assert _topics(summary) == []


def test_a_capital_after_a_full_stop_is_grammar_not_a_name():
    """"What", "Correction" and "Limited" were counted because they start
    sentences, not because they name anything."""
    topics = _topics("Now its with Asiri Hospitals? What is happening? "
                     "Correction: directors sold shares.")
    assert "Asiri Hospitals" in topics
    for noise in ("What", "Correction", "Now"):
        assert noise not in topics


def test_multi_word_names_survive_at_a_sentence_start():
    """The rule above must not discard "Ministry of Lands has ruled..."."""
    assert "Ministry of Lands" in _topics(
        "Ministry of Lands has approved the acquisition."
    )


def test_the_and_gazette_are_not_two_topics():
    topics = _topics("The Gazette authorises a new office under the Ministry "
                     "of Lands in Yekattha.")
    assert "Gazette" in topics
    assert "The Gazette" not in topics


def test_topics_are_capped_so_one_event_cannot_flood_the_panel():
    from src.nodes.combinedAgentNode import _MAX_TOPICS_PER_EVENT

    topics = _topics(
        "Kelani Ganga and Nilwala Ganga and Kalu Ganga and Mahaweli Ganga and "
        "Gin Ganga and Walawe Ganga all reported rising levels."
    )
    assert 0 < len(topics) <= _MAX_TOPICS_PER_EVENT
