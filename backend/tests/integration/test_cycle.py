"""
One full aggregation cycle, end to end, offline.

This is the test that has been missing. Across two audits this codebase yielded
~35 defects, and almost every one of them lived at a boundary that unit tests do
not cross: a node returning a key the state schema did not declare, a scraper
emitting `severity` while its consumer read `status`, a scoring formula whose
ceiling sat below its own threshold, storage dropping fields the API promised.
Each component passed its own tests. The system still produced a feed that was
wrong in ways nobody could see.

So this exercises the real aggregator, the real dedup decision, the real LLM
filter path, the real scoring and the real snapshot -- over fixture insights
shaped like what the five domain agents actually emit. Nothing is mocked except
the two things that would make the test slow, flaky or expensive: the network
(via fixture insights) and the LLM (via a deterministic double).

If this passes and the feed is still wrong, the fixtures are wrong. That is a
much better failure to have.
"""

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# --- doubles ---------------------------------------------------------------

class InMemoryStorage:
    """
    Faithful to the StorageManager contract, without SQLite/Chroma/Neo4j.

    Dedup keys on the same normalisation the real SQLite tier uses
    (md5 of the lowercased first 120 chars), so the cross-cycle behaviour this
    test asserts is the behaviour production gets.
    """

    def __init__(self):
        self.seen = {}          # dedup_key -> event_id
        self.events = []        # everything store_event was called with
        self.stats = {"errors": 0, "unique_stored": 0}
        self.linked = []

        store = self

        class _Chroma:
            @staticmethod
            def find_similar(summary, threshold=None):
                # Corroboration lookup. Returns prior events sharing a keyword,
                # which is enough to exercise the boost arithmetic.
                head = " ".join(str(summary).lower().split()[:4])
                return [e for e in store.events
                        if head and head in str(e["summary"]).lower()] or None

        self.chromadb = _Chroma()

    @staticmethod
    def _key(text):
        import hashlib
        return hashlib.md5(str(text)[:120].lower().encode()).hexdigest()

    def is_duplicate(self, summary, threshold=None):
        if not summary or len(str(summary).strip()) < 10:
            return False, "too_short", None
        key = self._key(summary)
        if key in self.seen:
            return True, "exact_match", {"matched_event_id": self.seen[key]}
        return False, "unique", None

    def store_event(self, event_id, summary, domain, severity, impact_type,
                    confidence_score, timestamp=None, metadata=None,
                    dedup_key=None, entities=None):
        self.seen[self._key(dedup_key or summary)] = event_id
        self.events.append({
            "event_id": event_id, "summary": summary, "domain": domain,
            "severity": severity, "impact_type": impact_type,
            "confidence_score": confidence_score, "metadata": metadata or {},
            "entities": entities or [],
        })
        self.stats["unique_stored"] += 1

    def link_similar_events(self, a, b, similarity):
        self.linked.append((a, b, similarity))


class ScriptedLLM:
    """Answers the batch filter honestly and deterministically."""

    def __init__(self, keep=True, severity=None):
        self.calls = 0
        self._keep = keep
        self._severity = severity

    def invoke(self, prompt):
        import re

        self.calls += 1
        m = re.search(r"ids 0 to (\d+)", prompt)
        n = int(m.group(1)) + 1 if m else 1

        payload = [
            {
                "id": i,
                "keep": self._keep,
                "is_meaningful": self._keep,
                "fake_news_probability": 0.05,
                # None means "defer to the agent's own severity", which is the
                # path an unverified event takes.
                "severity": self._severity or "high",
                "region": "sri_lanka",
                "enhanced_summary": f"Cleaned summary {i}",
                # Deliberately non-canonical surface forms: the pipeline is
                # expected to fold these onto canonical names.
                "entities": [
                    {"type": "PLACE", "name": "Gampaha District", "role": "affected"},
                    {"type": "INFRASTRUCTURE", "name": "Colombo Port", "role": "affected"},
                    {"type": "SECTOR", "name": "garments", "role": "mentioned"},
                ],
            }
            for i in range(n)
        ]

        class R:
            content = json.dumps(payload)

        return R()


class DeadLLM:
    def invoke(self, prompt):
        raise RuntimeError("429 rate limited")


# --- fixture insights ------------------------------------------------------

def domain_insights():
    """
    Shaped like what the five domain agents actually emit -- including the
    fields whose absence caused real bugs: distinct domains, explicit severity,
    impact_type, and a structured_data blob on the summary insights.
    """
    return [
        {"source_event_id": "s1", "domain": "social",
         "summary": "Colombo residents report severe traffic disruption after heavy rain",
         "severity": "high", "impact_type": "risk"},
        {"source_event_id": "p1", "domain": "political",
         "summary": "Parliament debates the new import tariff schedule this week",
         "severity": "medium", "impact_type": "risk"},
        {"source_event_id": "p2", "domain": "political",
         "summary": "Trade agreement signed opening apparel access to a new market",
         "severity": "low", "impact_type": "opportunity"},
        {"source_event_id": "e1", "domain": "economical",
         "summary": "Central Bank holds the policy rate at 8.75 percent this quarter",
         "severity": "medium", "impact_type": "risk"},
        {"source_event_id": "m1", "domain": "meteorological",
         "summary": "River monitoring gap: 3 of 30 rivernet stations are not reporting",
         "severity": "low", "impact_type": "risk"},
        {"source_event_id": "i1", "domain": "intelligence",
         "summary": "Competitor announces a new distribution hub in Gampaha district",
         "severity": "medium", "impact_type": "opportunity"},
    ]


def make_node(llm=None, storage=None):
    from src.nodes.combinedAgentNode import CombinedAgentNode

    node = CombinedAgentNode.__new__(CombinedAgentNode)
    node.llm = llm or ScriptedLLM()
    node.storage = storage or InMemoryStorage()
    node._seen_summaries_count = {}
    return node


def run_cycle(node, insights=None):
    """
    FeedAggregator -> DataRefresher, driven through the REAL state model.

    CombinedAgentState is a Pydantic BaseModel and the nodes read it with
    attribute access, so passing a plain dict here would silently produce an
    empty feed -- which is exactly the shape of bug this test exists to catch.
    Using the real type also exercises the domain_insights reducer.
    """
    from src.states.combinedAgentState import CombinedAgentState

    state = CombinedAgentState(
        domain_insights=insights if insights is not None else domain_insights()
    )
    aggregated = node.feed_aggregator_agent(state)

    after = state.model_copy(update=aggregated)
    refreshed = node.data_refresher_agent(after)

    out = {**aggregated, **refreshed}
    # Normalise the snapshot key so assertions do not depend on which node
    # produced it.
    out["snapshot"] = (
        refreshed.get("risk_dashboard_snapshot")
        or aggregated.get("risk_dashboard_snapshot")
        or {}
    )
    return out


# --- the cycle produces a feed --------------------------------------------

def test_a_cycle_produces_events():
    node = make_node()
    out = run_cycle(node)

    feed = out.get("final_ranked_feed") or []
    assert feed, "a cycle over six domain insights produced an empty feed"


def test_every_event_carries_the_full_contract():
    """
    Fields have been dropped at three separate layers in this codebase's
    history. The frontend types them as present; assert they are.
    """
    node = make_node()
    feed = run_cycle(node)["final_ranked_feed"]

    required = {
        "event_id", "summary", "domain", "confidence", "severity",
        "impact_type", "region", "fake_news_score", "llm_filtered", "timestamp",
    }
    for event in feed:
        missing = required - set(event)
        assert not missing, f"event missing {sorted(missing)}: {event}"


def test_domains_are_preserved_not_collapsed():
    """
    REGRESSION. Every agent constructed its storage managers bare, and both
    default to domain="political", so all five domains were written as one.
    """
    node = make_node()
    feed = run_cycle(node)["final_ranked_feed"]

    domains = {e["domain"] for e in feed}
    assert len(domains) >= 4, f"domains collapsed to {domains}"
    assert "political" in domains and "social" in domains


def test_high_priority_events_are_reachable():
    """
    REGRESSION. base was risk_score, which no node sets, so the score ceiling
    was 0.6 against a 0.7 threshold -- the tile was pinned at 0 by arithmetic.
    """
    node = make_node()
    out = run_cycle(node)

    snapshot = out["snapshot"]
    high = snapshot.get("high_priority_count")
    assert high is not None, "snapshot has no high_priority_count"
    assert high > 0, "no event reached high priority; the ceiling is below the threshold again"


def test_a_high_severity_event_counts_even_with_a_fake_news_penalty():
    """
    REGRESSION, found by this test on its first run. severity "high" maps to a
    base of exactly 0.7 and the threshold was `confidence >= 0.7` -- the same
    number. Confidence only moves DOWN from base for a typical event, because
    the fake-news penalty applies to nearly everything while the corroboration
    boost applies to little, so a "high" event with a fake_news_score of 0.05
    landed at 0.69 and was not counted. Only "critical" could ever qualify.

    A tile called "High Priority Events" that a high-severity event cannot
    enter is the original arithmetic-ceiling bug, one decimal further in.
    """
    node = make_node()
    out = run_cycle(node, insights=[{
        "source_event_id": "h1", "domain": "social",
        "summary": "Severe flooding reported across three Colombo suburbs overnight",
        "severity": "high", "impact_type": "risk",
    }])

    event = out["final_ranked_feed"][0]
    assert event["severity"] == "high"
    assert event["confidence"] < 0.7, (
        "fixture no longer reproduces the boundary; the penalty must land it "
        "just under 0.7 for this test to mean anything"
    )
    assert out["snapshot"]["high_priority_count"] == 1, (
        "a high-severity event was not counted as high priority"
    )


def test_a_low_severity_event_is_not_high_priority():
    """
    The fix must not make everything high priority instead.

    The LLM filter is allowed to reassess severity, and it wins -- so the
    double has to agree it is low, or this asserts nothing.
    """
    node = make_node(llm=ScriptedLLM(severity="low"))
    out = run_cycle(node, insights=[{
        "source_event_id": "l1", "domain": "social",
        "summary": "Local cricket club announces its annual fixture list for the season",
        "severity": "low", "impact_type": "risk",
    }])

    assert out["snapshot"]["high_priority_count"] == 0


def test_opportunities_survive_the_pipeline():
    """The product tracks risks AND opportunities; only risks used to arrive."""
    node = make_node()
    feed = run_cycle(node)["final_ranked_feed"]

    assert any(e["impact_type"] == "opportunity" for e in feed), (
        "every opportunity was dropped or relabelled as a risk"
    )


# --- dedup across cycles ---------------------------------------------------

def test_the_same_events_do_not_re_emit_next_cycle():
    """
    REGRESSION, and the one with the worst compounding. Dedup looked up the
    original summary and stored the LLM's rewrite, so the md5 could never
    match; with a 60s loop the same events re-emitted forever, each logged
    "UNIQUE EVENT".
    """
    storage = InMemoryStorage()
    node = make_node(storage=storage)

    first = run_cycle(node)["final_ranked_feed"]
    assert first

    second = run_cycle(node)["final_ranked_feed"]
    assert not second, (
        f"{len(second)} event(s) re-emitted on an identical second cycle; "
        "dedup is keyed on the wrong text again"
    )


def test_genuinely_new_events_still_get_through():
    """Dedup must not become a wall."""
    storage = InMemoryStorage()
    node = make_node(storage=storage)

    run_cycle(node)
    fresh = [{
        "source_event_id": "n1", "domain": "economical",
        "summary": "Port of Colombo announces a new berth allocation schedule",
        "severity": "high", "impact_type": "risk",
    }]
    out = run_cycle(node, insights=fresh)

    assert out["final_ranked_feed"], "a genuinely new event was dropped as a duplicate"


# --- the honest failure path ----------------------------------------------

def test_an_llm_outage_degrades_rather_than_fabricates():
    """
    REGRESSION. The fallback invented severity="medium" and
    fake_news_score=0.3 and returned them under a successful shape, so a
    throttled run filled the dashboard with numbers no model produced.
    """
    node = make_node(llm=DeadLLM())
    feed = run_cycle(node)["final_ranked_feed"]

    assert feed, "an LLM outage emptied the feed; it should degrade, not vanish"

    for event in feed:
        assert event["llm_filtered"] is False
        assert event["fake_news_score"] is None, "invented a fake-news score"

    # Severity falls back to the agent's own keyword-derived value.
    by_id = {e["summary"]: e for e in feed}
    assert any(e["severity"] in ("low", "medium", "high") for e in by_id.values())


def test_a_working_llm_marks_events_verified():
    node = make_node()
    feed = run_cycle(node)["final_ranked_feed"]

    assert all(e["llm_filtered"] is True for e in feed)
    assert all(isinstance(e["fake_news_score"], float) for e in feed)


def test_the_llm_is_called_once_per_domain_not_once_per_post():
    """50-150 sequential calls per 60s cycle is what made throttling routine."""
    llm = ScriptedLLM()
    node = make_node(llm=llm)
    run_cycle(node)

    assert llm.calls <= 6, (
        f"{llm.calls} LLM calls for six insights across five domains; "
        "batching regressed"
    )


# --- the snapshot ----------------------------------------------------------

def test_risk_indices_are_populated_from_real_domains():
    """
    REGRESSION. The buckets read domain_risks.get("mobility") and .get("market")
    -- strings no agent emits -- while meteorological mapped to nothing.
    """
    node = make_node()
    out = run_cycle(node)
    snapshot = out["snapshot"]

    for key in ("logistics_friction", "compliance_volatility", "market_instability"):
        assert key in snapshot, f"snapshot missing {key}"

    assert any(
        snapshot.get(k) for k in
        ("logistics_friction", "compliance_volatility", "market_instability")
    ), "every risk index is zero despite six insights across five domains"


def test_regulatory_activity_is_labelled_as_a_count():
    """It is a story tally, not a calibrated index, and must say so."""
    node = make_node()
    out = run_cycle(node)
    snapshot = out["snapshot"]

    if "regulatory_activity" in snapshot:
        assert snapshot.get("regulatory_activity_is_count") is True
        assert "regulatory_story_count" in snapshot


def test_confidence_is_a_number_in_range():
    node = make_node()
    feed = run_cycle(node)["final_ranked_feed"]

    for event in feed:
        assert isinstance(event["confidence"], (int, float)), (
            f"confidence is {type(event['confidence']).__name__}, not a number"
        )
        assert 0.0 <= event["confidence"] <= 1.0


# --- storage ---------------------------------------------------------------

def test_events_are_stored_once_not_twice():
    """
    REGRESSION. Subgraph wrappers returned the whole accumulated state into an
    operator.add reducer, so every post was written twice.
    """
    storage = InMemoryStorage()
    node = make_node(storage=storage)
    feed = run_cycle(node)["final_ranked_feed"]

    assert len(storage.events) == len(feed), (
        f"{len(storage.events)} writes for {len(feed)} events"
    )


def test_storage_receives_the_computed_metadata():
    """region / fake_news_score / llm_filtered were computed then dropped."""
    storage = InMemoryStorage()
    node = make_node(storage=storage)
    run_cycle(node)

    assert storage.events
    for stored in storage.events:
        assert "region" in stored["metadata"], (
            "region never reached storage, so /api/feeds cannot filter by it"
        )
        assert "llm_filtered" in stored["metadata"]


# --- entities --------------------------------------------------------------

def test_the_storage_double_matches_the_real_signature():
    """
    A double that drifts from the real signature stops testing what it claims
    while still passing. This caught `entities` being added to store_event.
    """
    import inspect

    from src.storage.storage_manager import StorageManager

    real = set(inspect.signature(StorageManager.store_event).parameters)
    fake = set(inspect.signature(InMemoryStorage.store_event).parameters)

    missing = real - fake
    assert not missing, (
        f"InMemoryStorage.store_event is missing {sorted(missing)}; the double "
        "no longer stands in for the real thing"
    )


def test_entities_are_canonicalised_before_they_reach_storage():
    """
    Relevance is a join on names. "Colombo Port" and "Port of Colombo" must
    arrive as one identity or the join silently under-matches, which looks
    exactly like a quiet news day.
    """
    storage = InMemoryStorage()
    node = make_node(storage=storage)
    run_cycle(node)

    assert storage.events
    names = {e["name"] for ev in storage.events for e in ev["entities"]}

    assert "Port of Colombo" in names, f"not canonicalised: {sorted(names)}"
    assert "Colombo Port" not in names, "a raw surface form reached storage"
    assert "Gampaha" in names
    assert "apparel" in names, "'garments' did not fold onto its canonical sector"


def test_events_carry_entities_to_the_feed():
    node = make_node()
    feed = run_cycle(node)["final_ranked_feed"]

    for event in feed:
        assert "entities" in event
        assert event["entities_extracted"] is True


def test_an_llm_outage_reports_entities_as_not_extracted():
    """
    The honest failure path. Zero entities because no model ran must be
    distinguishable from zero entities because the post named nothing --
    otherwise relevance silently scores every event as irrelevant.
    """
    node = make_node(llm=DeadLLM())
    feed = run_cycle(node)["final_ranked_feed"]

    assert feed
    for event in feed:
        assert event["entities"] == []
        assert event["entities_extracted"] is False


def test_a_reply_without_the_entities_key_is_not_read_as_empty():
    """A prompt or parsing regression must surface, not look like a quiet post."""

    class NoEntitiesLLM:
        def invoke(self, prompt):
            import re

            m = re.search(r"ids 0 to (\d+)", prompt)
            n = int(m.group(1)) + 1 if m else 1

            class R:
                content = json.dumps([
                    {"id": i, "keep": True, "is_meaningful": True,
                     "fake_news_probability": 0.05, "severity": "medium",
                     "region": "sri_lanka", "enhanced_summary": f"s{i}"}
                    for i in range(n)
                ])

            return R()

    node = make_node(llm=NoEntitiesLLM())
    feed = run_cycle(node)["final_ranked_feed"]

    assert feed
    assert all(e["entities_extracted"] is False for e in feed), (
        "a reply with no entities field was recorded as a successful empty "
        "extraction"
    )
