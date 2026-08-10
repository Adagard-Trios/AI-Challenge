"""
Tests for the orchestrator's dedup, scoring and domain wiring.

Three defects, all of which produced a dashboard that looked populated and
plausible while being wrong:

  - dedup could never fire, so the same events re-emitted every 60s forever
  - high_priority_count was mathematically pinned at 0
  - all five domains wrote to storage labelled "political"
"""

import ast
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

NODES = PROJECT_ROOT / "src" / "nodes"

DOMAINS = {
    "socialAgentNode.py": "social",
    "politicalAgentNode.py": "political",
    "economicalAgentNode.py": "economical",
    "meteorologicalAgentNode.py": "meteorological",
    "intelligenceAgentNode.py": "intelligence",
}


# --- C. domain labelling ---------------------------------------------------

@pytest.mark.parametrize("node_name,domain", sorted(DOMAINS.items()))
def test_storage_managers_get_an_explicit_domain(node_name, domain):
    """
    REGRESSION. Both managers default to domain="political"
    (db_manager.py:56, :262). Constructing them bare made all five agents write
    :PoliticalPost with domain="political" -- so the knowledge graph had no
    domain separation, domain-filtered RAG returned everything, and the shared
    URL-uniqueness constraint turned a post scraped by two agents into a
    cross-domain false duplicate, silently dropping the second write.
    """
    src = (NODES / node_name).read_text(encoding="utf-8")
    assert "Neo4jManager()" not in src, f"{node_name} constructs Neo4jManager with no domain"
    assert "ChromaDBManager()" not in src, f"{node_name} constructs ChromaDBManager with no domain"
    assert f'Neo4jManager(domain="{domain}")' in src
    assert f'ChromaDBManager(domain="{domain}")' in src


def test_every_agent_uses_a_distinct_domain():
    """Two agents sharing a domain string would re-create the collision."""
    assert len(set(DOMAINS.values())) == len(DOMAINS)


# --- D. deduplication ------------------------------------------------------

def test_store_event_accepts_a_separate_dedup_key():
    import inspect
    from src.storage.storage_manager import StorageManager

    params = inspect.signature(StorageManager.store_event).parameters
    assert "dedup_key" in params
    assert params["dedup_key"].default is None, "must default to None for old callers"


def test_dedup_key_is_what_reaches_the_sqlite_tier(tmp_path, monkeypatch):
    """
    THE regression. The aggregator looks up the ORIGINAL summary, then an LLM
    rewrites it, then the rewrite was stored. SQLite keys on
    md5(text[:120].lower()) (sqlite_cache.py:47), so the hashes could never
    match and exact-match dedup never fired once.
    """
    from src.storage.storage_manager import StorageManager

    recorded = {}

    class FakeSqlite:
        def add_entry(self, text, event_id):
            recorded["text"] = text

    class Noop:
        def __getattr__(self, _):
            return lambda *a, **k: None

    mgr = StorageManager.__new__(StorageManager)
    mgr.sqlite_cache = FakeSqlite()
    mgr.chromadb = Noop()
    mgr.neo4j = Noop()
    mgr.stats = {"errors": 0, "stored": 0, "duplicates": 0}

    mgr.store_event(
        event_id="e1",
        summary="LLM REWRITE of the event",
        domain="social",
        severity="high",
        impact_type="risk",
        confidence_score=0.8,
        dedup_key="original agent summary",
    )

    assert recorded["text"] == "original agent summary", (
        "the LLM rewrite was stored as the dedup key; next cycle's lookup of "
        "the original can never match it"
    )


def test_dedup_key_defaults_to_summary():
    """Callers that do not rewrite the text keep their old behaviour."""
    from src.storage.storage_manager import StorageManager

    recorded = {}

    class FakeSqlite:
        def add_entry(self, text, event_id):
            recorded["text"] = text

    class Noop:
        def __getattr__(self, _):
            return lambda *a, **k: None

    mgr = StorageManager.__new__(StorageManager)
    mgr.sqlite_cache = FakeSqlite()
    mgr.chromadb = Noop()
    mgr.neo4j = Noop()
    mgr.stats = {"errors": 0, "stored": 0, "duplicates": 0}

    mgr.store_event(event_id="e", summary="only text", domain="d",
                    severity="low", impact_type="risk", confidence_score=0.1)

    assert recorded["text"] == "only text"


def test_aggregator_passes_the_original_summary():
    src = (NODES / "combinedAgentNode.py").read_text(encoding="utf-8")
    assert "dedup_key=original_summary" in src


# --- E. confidence ceiling -------------------------------------------------

SEVERITY_BASE = {"low": 0.25, "medium": 0.45, "high": 0.7, "critical": 0.9}


def _score(severity, impact="risk", risk_score=None):
    """Mirrors calculate_score in combinedAgentNode."""
    explicit = risk_score
    base = (float(explicit) if explicit not in (None, "", 0, 0.0)
            else SEVERITY_BASE.get(severity, 0.25))
    return min(1.0, base + (0.1 if impact == "opportunity" else 0.0))


def test_high_priority_threshold_is_reachable():
    """
    REGRESSION. base was risk_score, which NO node sets, so it was always 0.0.
    Ceiling was 0.0 + 0.3 + 0.2 + 0.1 = 0.6 against a 0.7 threshold -- the
    "High Priority Events" tile was pinned at 0 by arithmetic.
    """
    assert _score("high") >= 0.7
    assert _score("critical") >= 0.7
    assert _score("critical", "opportunity") >= 0.7


def test_low_severity_stays_below_the_threshold():
    """The fix must not make everything high priority instead."""
    assert _score("low") < 0.7
    assert _score("medium") < 0.7
    assert _score("medium", "opportunity") < 0.7


def test_explicit_risk_score_still_wins():
    """Honour risk_score when an agent does provide one."""
    assert _score("low", risk_score=0.95) == pytest.approx(0.95)


def test_score_is_capped_at_one():
    assert _score("critical", "opportunity", risk_score=0.99) <= 1.0


def test_no_reference_to_the_dead_risk_score_only_formula():
    src = (NODES / "combinedAgentNode.py").read_text(encoding="utf-8")
    assert "return base + boost + opp_boost" not in src


# --- E2. corroboration boost ----------------------------------------------

def test_corroboration_counts_sources():
    """
    REGRESSION. It was `min(0.3, 0.1)` -- a constant. A story corroborated by
    six outlets scored the same as one corroborated by a single tweet, while
    still paying the ChromaDB query.
    """
    import io
    import re
    import tokenize

    raw = (NODES / "combinedAgentNode.py").read_text(encoding="utf-8")
    # Strip comments -- the explanatory comment quotes the very expression this
    # test forbids -- then strip whitespace so spacing cannot affect the match.
    code = "".join(
        tok.string if tok.type != tokenize.COMMENT else ""
        for tok in tokenize.generate_tokens(io.StringIO(raw).readline)
    )
    code = re.sub(r"\s+", "", code)

    assert "min(0.3,0.1)" not in code, "constant corroboration boost is back"
    assert "0.1*corroborations" in code


# --- E3. dashboard domain buckets -----------------------------------------

def test_risk_buckets_reference_only_real_domains():
    """
    REGRESSION. The buckets read domain_risks.get("mobility") and .get("market")
    -- strings no agent emits -- while "meteorological" was mapped to nothing,
    so weather never influenced the risk radar.
    """
    src = (NODES / "combinedAgentNode.py").read_text(encoding="utf-8")
    real = set(DOMAINS.values())

    tree = ast.parse(src)
    referenced = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "domain_risks"
                and node.args and isinstance(node.args[0], ast.Constant)):
            referenced.add(node.args[0].value)

    phantom = referenced - real
    assert not phantom, f"risk buckets read domains no agent emits: {sorted(phantom)}"
    assert "meteorological" in referenced, "weather still absent from the risk radar"
