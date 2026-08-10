"""
Threading: a developing story is one object, not forty discarded duplicates.

The dedup pipeline computes exactly the signal threading needs -- "this event
is semantically the same as that one" -- and then spends it on
link_similar_events(), which writes to Neo4j, which render.yaml disables, before
dropping the event. So a flood developing over three days left no object
anywhere representing the flood.

These tests cover the two things that make threading trustworthy: state is
derived from the timeline rather than stored as a judgement, and a brief that
could not be regenerated is visibly stale rather than quietly presented as
current.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)


# --- derived state ---------------------------------------------------------

@pytest.mark.parametrize(
    "age,escalated,expected",
    [
        (timedelta(minutes=5), False, "developing"),
        (timedelta(minutes=5), True, "escalating"),
        (timedelta(hours=7), False, "quiet"),
        (timedelta(hours=7), True, "escalating"),
        (timedelta(hours=25), False, "resolved"),
        # Resolved wins over escalating: a story nothing has touched in a day
        # is over, whatever its peak was.
        (timedelta(hours=25), True, "resolved"),
    ],
)
def test_state_is_derived_from_the_timeline(age, escalated, expected):
    from src.intelligence.stories import derive_state

    assert derive_state(
        last_seen=NOW - age, escalated=escalated, now=NOW
    ) == expected


def test_a_story_with_no_timestamp_is_developing():
    from src.intelligence.stories import derive_state

    assert derive_state(last_seen=None, escalated=False, now=NOW) == "developing"


def test_naive_timestamps_do_not_raise():
    """
    Rows written before the timezone-aware default would compare as naive and
    blow up mid-cycle.
    """
    from src.intelligence.stories import derive_state

    naive = (NOW - timedelta(hours=1)).replace(tzinfo=None)
    assert derive_state(last_seen=naive, escalated=False, now=NOW) == "developing"


# --- severity --------------------------------------------------------------

def test_severity_ordering():
    from src.intelligence.stories import severity_rank

    assert (
        severity_rank("low")
        < severity_rank("medium")
        < severity_rank("high")
        < severity_rank("critical")
    )


def test_an_unknown_severity_does_not_count_as_an_escalation():
    """A garbage value must not silently mark every story as escalating."""
    from src.intelligence.stories import severity_rank

    assert severity_rank("catastrophic") == severity_rank("low")
    assert severity_rank(None) == severity_rank("low")


# --- degradation without a database ---------------------------------------

def test_threading_without_a_database_reports_failure_rather_than_pretending():
    """
    The whole point of the seam. Without somewhere to write, the event is
    dropped exactly as before -- but attach() must return None so the caller
    counts it as unthreaded. A disabled feature reading as a working one is
    this codebase's signature bug.
    """
    from src.intelligence.stories import StoryTracker

    tracker = StoryTracker()
    tracker._unavailable = True

    result = tracker.attach(
        event_id="e2", matched_event_id="e1", summary="flooding continues",
        severity="high", domain="meteorological", similarity=0.9,
    )

    assert result is None
    assert tracker.recent() == []
    assert tracker.stories_needing_a_brief() == []


# --- the seam --------------------------------------------------------------

def test_the_aggregator_threads_instead_of_discarding():
    """
    REGRESSION. A semantic duplicate used to be handed to
    link_similar_events() -- Neo4j, disabled -- and then dropped.
    """
    import ast

    src = (PROJECT_ROOT / "src" / "nodes" / "combinedAgentNode.py").read_text(
        encoding="utf-8"
    )
    code = "\n".join(
        line for line in src.splitlines() if not line.strip().startswith("#")
    )

    assert "story_tracker.attach(" in code, (
        "the semantic-match branch no longer threads"
    )
    assert "link_similar_events" not in code, (
        "still writing the link to a disabled database"
    )

    # And the counters have to stay separate.
    assert '"threaded"' in code and '"thread_failed"' in code


def test_brief_regeneration_is_batched_and_capped():
    """
    One extra LLM call per cycle regardless of how many stories are live. A
    per-story call would put the cost back on a 60-second loop, which is the
    mistake the post filter already made once.
    """
    from src.nodes.combinedAgentNode import CombinedAgentNode

    assert CombinedAgentNode.STORY_BRIEF_BATCH <= 10

    import inspect

    source = inspect.getsource(CombinedAgentNode.regenerate_story_briefs)
    assert "self.llm.invoke" in source
    assert source.count("self.llm.invoke") == 1, (
        "brief regeneration makes more than one call"
    )


# --- honest briefs ---------------------------------------------------------

class _FakeTracker:
    def __init__(self, stories):
        self._stories = stories
        self.saved = {}

    def stories_needing_a_brief(self, limit=10):
        return self._stories[:limit]

    def save_brief(self, story_id, brief):
        self.saved[story_id] = brief
        return bool(brief)


def _node(llm, tracker):
    from src.intelligence import stories as stories_module
    from src.nodes.combinedAgentNode import CombinedAgentNode

    stories_module.set_story_tracker(tracker)
    node = CombinedAgentNode.__new__(CombinedAgentNode)
    node.llm = llm
    return node


PENDING = [
    {"id": "s1", "title": "Kelani rising", "brief": "River level rising.",
     "domain": "meteorological", "event_count": 4, "peak_severity": "high"},
    {"id": "s2", "title": "Port delays", "brief": "Congestion reported.",
     "domain": "economical", "event_count": 3, "peak_severity": "medium"},
]


def test_a_failed_regeneration_keeps_the_old_brief_and_marks_it_stale():
    """
    An old brief beats no brief. But a story showing last week's text as though
    it were current is the staleness problem the dashboard already had.
    """
    import json

    class DeadLLM:
        def invoke(self, prompt):
            raise RuntimeError("429 rate limited")

    tracker = _FakeTracker(list(PENDING))
    node = _node(DeadLLM(), tracker)

    written = node.regenerate_story_briefs()

    assert written == 0
    assert tracker.saved == {"s1": None, "s2": None}, (
        "a failed batch must mark every story stale, not silently skip them"
    )


def test_a_partial_reply_only_marks_the_missing_ones_stale():
    import json

    class PartialLLM:
        def invoke(self, prompt):
            class R:
                content = json.dumps([
                    {"id": 0, "title": "Kelani at warning level",
                     "brief": "The river has risen past the warning mark."},
                ])
            return R()

    tracker = _FakeTracker(list(PENDING))
    node = _node(PartialLLM(), tracker)

    written = node.regenerate_story_briefs()

    assert written == 1
    assert tracker.saved["s1"]
    assert tracker.saved["s2"] is None


def test_nothing_pending_makes_no_llm_call():
    """The cost gate. No movement, no call."""

    class CountingLLM:
        calls = 0

        def invoke(self, prompt):
            CountingLLM.calls += 1
            raise AssertionError("should not have been called")

    tracker = _FakeTracker([])
    node = _node(CountingLLM(), tracker)

    assert node.regenerate_story_briefs() == 0
    assert CountingLLM.calls == 0
