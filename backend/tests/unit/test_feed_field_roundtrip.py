"""
Fields must survive the whole trip: aggregator -> ChromaDB -> API -> frontend.

The aggregator computes region, fake_news_score and llm_filtered per event, and
all three were being dropped -- at three independent points:

  1. combinedAgentNode called store_event() without passing them at all.
  2. store_event() accepted a `metadata` argument, handed it to Neo4j (off by
     default), and never merged it into the ChromaDB record -- which is the one
     get_recent_feeds() actually reads back.
  3. /api/feeds rebuilt each event from a fixed whitelist that omitted them.

/api/feed, which serves the in-memory copy, carried them the whole time. So the
same event had different fields depending on whether the client got it from the
initial load or a live websocket update, and the sidebar's region filter had
nothing to filter until the first push arrived.
"""

import ast
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CARRIED = ("region", "fake_news_score", "llm_filtered")


# --- the round trip --------------------------------------------------------

def test_metadata_reaches_the_chromadb_record():
    """store_event must merge caller metadata into what ChromaDB stores."""
    from src.storage.storage_manager import StorageManager

    captured = {}

    class FakeChroma:
        def add_event(self, event_id, summary, metadata=None):
            captured.update(metadata or {})

    class Noop:
        def __getattr__(self, _):
            return lambda *a, **k: None

    mgr = StorageManager.__new__(StorageManager)
    mgr.sqlite_cache = Noop()
    mgr.chromadb = FakeChroma()
    mgr.neo4j = Noop()
    mgr.stats = {"errors": 0, "unique_stored": 0}

    mgr.store_event(
        event_id="e1", summary="s", domain="social", severity="high",
        impact_type="risk", confidence_score=0.82,
        metadata={"region": "world", "fake_news_score": 0.12, "llm_filtered": True},
    )

    for key in CARRIED:
        assert key in captured, f"{key} never reached the ChromaDB record"
    assert captured["region"] == "world"
    assert captured["confidence_score"] == 0.82


def test_core_fields_win_over_caller_metadata():
    """A caller must not be able to overwrite the event's own domain/severity."""
    from src.storage.storage_manager import StorageManager

    captured = {}

    class FakeChroma:
        def add_event(self, event_id, summary, metadata=None):
            captured.update(metadata or {})

    class Noop:
        def __getattr__(self, _):
            return lambda *a, **k: None

    mgr = StorageManager.__new__(StorageManager)
    mgr.sqlite_cache = Noop()
    mgr.chromadb = FakeChroma()
    mgr.neo4j = Noop()
    mgr.stats = {"errors": 0, "unique_stored": 0}

    mgr.store_event(
        event_id="e1", summary="s", domain="social", severity="high",
        impact_type="risk", confidence_score=0.8,
        metadata={"domain": "HIJACKED", "severity": "low"},
    )

    assert captured["domain"] == "social"
    assert captured["severity"] == "high"


def test_numbers_come_back_as_numbers():
    """
    REGRESSION. ChromaDBStore.add_event str()s every value, so confidence came
    back as the string "0.85" -- handed to a frontend whose type says number,
    making every comparison on it a string comparison.
    """
    from src.storage.storage_manager import _as_float

    assert _as_float("0.85", 0.5) == pytest.approx(0.85)
    assert _as_float(0.85, 0.5) == pytest.approx(0.85)
    assert _as_float(None, 0.5) == 0.5
    assert _as_float("", 0.5) == 0.5
    assert _as_float("None", None) is None, (
        'str(None) round-trips as the literal "None"'
    )
    assert _as_float("garbage", 0.5) == 0.5


def test_unjudged_events_read_back_as_none_not_zero():
    """A missing fake-news score must stay missing, not become a clean 0.0."""
    from src.storage.storage_manager import _as_float

    assert _as_float(None, None) is None
    assert _as_float("None", None) is None


# --- the call sites --------------------------------------------------------

def test_aggregator_passes_the_fields_to_storage():
    src = (PROJECT_ROOT / "src" / "nodes" / "combinedAgentNode.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(src)

    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "store_event"):
            kwargs = {kw.arg for kw in node.keywords}
            assert "metadata" in kwargs, (
                f"combinedAgentNode.py:{node.lineno} stores an event without "
                "region/fake_news_score/llm_filtered"
            )
            return
    pytest.fail("no store_event call found in the aggregator")


@pytest.mark.parametrize("method", ["get_recent_feeds", "get_feeds_since"])
def test_read_paths_return_the_fields(method):
    """
    Both read methods build the same dict literal; fixing only one would leave
    the websocket delta and the initial load disagreeing again.
    """
    src = (PROJECT_ROOT / "src" / "storage" / "storage_manager.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(src)

    fn = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == method),
        None,
    )
    assert fn is not None, f"{method} is gone"

    keys = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Dict):
            keys |= {k.value for k in node.keys if isinstance(k, ast.Constant)}

    for field in CARRIED:
        assert field in keys, f"{method} does not return {field}"


def test_feeds_endpoint_does_not_drop_the_fields():
    src = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    fn = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == "get_feeds_from_db"),
        None,
    )
    assert fn is not None, "get_feeds_from_db is gone"

    keys = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Dict):
            keys |= {k.value for k in node.keys if isinstance(k, ast.Constant)}

    for field in CARRIED:
        assert field in keys, (
            f"/api/feeds normalization drops {field}, so the initial load and "
            "the live websocket update disagree about the event's shape"
        )
