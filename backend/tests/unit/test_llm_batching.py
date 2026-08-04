"""
The LLM post filter: call volume and what happens when a call fails.

The filter ran once per post, serially, inside a 60s loop -- 50-150 sequential
Groq calls per cycle. When rate limiting inevitably hit, the fallback INVENTED
severity="medium" and fake_news_score=0.3 and let them through, so a throttled
run filled the dashboard with fabricated scores that looked exactly like real
verdicts. Only a logger.warning recorded it.
"""

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class RecordingLLM:
    """Answers every batch correctly and counts calls."""

    def __init__(self):
        self.calls = []

    def invoke(self, prompt):
        self.calls.append(prompt)
        n = prompt.count("\n\n[")  # numbered posts in the batch
        # The prompt embeds "[0] ..." for the first post before the blank-line
        # separated ones, so recover the count from the explicit instruction.
        import re

        m = re.search(r"ids 0 to (\d+)", prompt)
        n = int(m.group(1)) + 1 if m else n

        class R:
            content = json.dumps([
                {
                    "id": i,
                    "keep": True,
                    "is_meaningful": True,
                    "fake_news_probability": 0.1,
                    "severity": "high",
                    "region": "sri_lanka",
                    "enhanced_summary": f"clean {i}",
                }
                for i in range(n)
            ])

        return R()


class ExplodingLLM:
    def __init__(self):
        self.calls = 0

    def invoke(self, prompt):
        self.calls += 1
        raise RuntimeError("429 rate limited")


def _node(llm):
    """A CombinedAgentNode with storage stubbed out."""
    from src.nodes.combinedAgentNode import CombinedAgentNode

    node = CombinedAgentNode.__new__(CombinedAgentNode)
    node.llm = llm
    node._seen_summaries_count = {}

    class NoStorage:
        class chromadb:
            @staticmethod
            def find_similar(*a, **k):
                return None

    node.storage = NoStorage()
    return node


def _posts(n, domain="social", text="Sri Lanka economic outlook remains uncertain"):
    return [{"summary": f"{text} number {i}", "domain": domain} for i in range(n)]


# --- batching --------------------------------------------------------------

def test_one_call_per_domain_not_one_per_post():
    """REGRESSION. 30 posts across 3 domains used to mean 30 sequential calls."""
    llm = RecordingLLM()
    node = _node(llm)

    posts = _posts(10, "social") + _posts(10, "political") + _posts(10, "economical")
    results = node._llm_filter_posts(posts)

    assert len(results) == 30
    assert len(llm.calls) == 3, (
        f"expected one call per domain, got {len(llm.calls)}"
    )
    assert all(r["llm_filtered"] for r in results)


def test_large_domains_are_chunked_not_sent_whole():
    """A single 200-post domain must not become one enormous prompt."""
    from src.nodes.combinedAgentNode import CombinedAgentNode

    llm = RecordingLLM()
    node = _node(llm)

    n = CombinedAgentNode.LLM_FILTER_BATCH_SIZE * 3 + 1
    results = node._llm_filter_posts(_posts(n, "social"))

    assert len(results) == n
    assert len(llm.calls) == 4
    assert all(r is not None for r in results)


def test_results_stay_aligned_with_their_posts():
    """Batching must not reorder verdicts relative to inputs."""
    llm = RecordingLLM()
    node = _node(llm)

    posts = _posts(5, "social") + _posts(5, "political")
    results = node._llm_filter_posts(posts)

    for post, result in zip(posts, results):
        assert result["original_summary"] == post["summary"]


def test_short_posts_are_rejected_without_an_llm_call():
    llm = RecordingLLM()
    node = _node(llm)

    results = node._llm_filter_posts([{"summary": "hi", "domain": "social"}])

    assert results[0] == {"keep": False, "reason": "too_short"}
    assert llm.calls == []


# --- honest failure --------------------------------------------------------

def test_failed_call_does_not_invent_a_severity():
    """
    THE regression. The old fallback returned severity="medium" and
    fake_news_score=0.3 -- numbers no model produced -- and they reached the
    dashboard indistinguishable from real verdicts.
    """
    node = _node(ExplodingLLM())

    results = node._llm_filter_posts(_posts(3, "social"))

    for r in results:
        assert r["llm_filtered"] is False
        assert r["severity"] is None, "invented a severity for an unjudged post"
        assert r["fake_news_score"] is None, "invented a fake-news score"
        assert r["keep"] is True, "an outage should degrade, not empty the feed"


def test_partial_verdicts_mark_only_the_missing_ones():
    """A reply covering 2 of 5 posts must not silently score the other 3."""

    class PartialLLM:
        def invoke(self, prompt):
            class R:
                content = json.dumps([
                    {"id": 0, "keep": True, "is_meaningful": True,
                     "fake_news_probability": 0.1, "severity": "high",
                     "region": "sri_lanka", "enhanced_summary": "clean 0"},
                    {"id": 3, "keep": True, "is_meaningful": True,
                     "fake_news_probability": 0.1, "severity": "low",
                     "region": "world", "enhanced_summary": "clean 3"},
                ])

            return R()

    node = _node(PartialLLM())
    results = node._llm_filter_posts(_posts(5, "social"))

    assert [r["llm_filtered"] for r in results] == [True, False, False, True, False]
    assert results[0]["severity"] == "high"
    assert results[3]["severity"] == "low"
    for i in (1, 2, 4):
        assert results[i]["severity"] is None


def test_malformed_json_is_a_failure_not_a_verdict():
    class GarbageLLM:
        def invoke(self, prompt):
            class R:
                content = "I'm sorry, I can't help with that."

            return R()

    node = _node(GarbageLLM())
    results = node._llm_filter_posts(_posts(2, "social"))

    assert all(r["llm_filtered"] is False for r in results)
    assert all(r["severity"] is None for r in results)


def test_fenced_json_is_still_parsed():
    """Models routinely wrap JSON in ```json fences."""

    class FencedLLM:
        def invoke(self, prompt):
            class R:
                content = (
                    "```json\n"
                    + json.dumps([{
                        "id": 0, "keep": True, "is_meaningful": True,
                        "fake_news_probability": 0.05, "severity": "critical",
                        "region": "sri_lanka", "enhanced_summary": "clean",
                    }])
                    + "\n```"
                )

            return R()

    node = _node(FencedLLM())
    results = node._llm_filter_posts(_posts(1, "social"))

    assert results[0]["llm_filtered"] is True
    assert results[0]["severity"] == "critical"


def test_high_fake_news_probability_still_rejects():
    """The quality gate must survive the rewrite."""

    class FakeNewsLLM:
        def invoke(self, prompt):
            class R:
                content = json.dumps([{
                    "id": 0, "keep": True, "is_meaningful": True,
                    "fake_news_probability": 0.95, "severity": "high",
                    "region": "sri_lanka", "enhanced_summary": "clean",
                }])

            return R()

    node = _node(FakeNewsLLM())
    results = node._llm_filter_posts(_posts(1, "social"))

    assert results[0]["keep"] is False


# --- the caller ------------------------------------------------------------

def test_aggregator_falls_back_to_the_agents_own_severity():
    """
    An unverified event must keep the severity its domain agent derived, and
    take no fake-news penalty, rather than inheriting an invented one.
    """
    src = (PROJECT_ROOT / "src" / "nodes" / "combinedAgentNode.py").read_text(
        encoding="utf-8"
    )
    assert 'severity = llm_result.get("severity") or original_severity' in src
    assert "fake_penalty = (fake_score * 0.2) if fake_score is not None else 0.0" in src
    assert '"llm_filtered": llm_filtered' in src, (
        "the verified/unverified distinction must reach the frontend"
    )


def test_the_invented_fallback_values_are_gone():
    import ast
    import io
    import re
    import tokenize

    raw = (PROJECT_ROOT / "src" / "nodes" / "combinedAgentNode.py").read_text(
        encoding="utf-8"
    )
    # Strip comments -- they quote the very values this test forbids.
    code = "".join(
        tok.string if tok.type != tokenize.COMMENT else ""
        for tok in tokenize.generate_tokens(io.StringIO(raw).readline)
    )
    code = re.sub(r"\s+", "", code)

    assert '"fake_news_score":0.3' not in code, "invented fake-news score is back"
    assert "_llm_filter_post(" not in code.replace("_llm_filter_posts(", ""), (
        "the per-post filter is back"
    )
