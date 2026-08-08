"""
Writing to the board, and clearing it out again.

Two stages are covered here. B1 mirrors classified events onto the board from
the aggregator -- nothing reads them yet, which is the point: the board is
populated and observed before anything depends on it, so the stage that starts
consuming it has real data to be judged against rather than an empty table and
a hypothesis.

B2 ages and evicts. That stage also closes three leaks that predate the board:

  ChromaDB          had NO delete method at all, only clear_collection(), so
                    the semantic corpus grew forever on the largest thing this
                    system keeps on disk.
  trending_detector cleanup_old_data(days=7) was DEFINED AND NEVER CALLED.
  ks_activations    ~1,500 rows/hour; an audit table that grows forever is the
                    same bug it exists to help find.

Needs a database. Skips without one, and the decay maths -- the part easiest to
get wrong -- is covered separately in test_blackboard_decay.py with no database
at all.
"""

import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def store():
    from src.blackboard.store import BoardStore

    try:
        from auth.db import init_db

        init_db()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no database: {exc}")

    instance = BoardStore()
    if not instance.available():
        pytest.skip("board tables unavailable")
    return instance


def _eid():
    return f"ev-{uuid.uuid4().hex[:10]}"


def _cleanup(event_ids):
    from auth.db import session_scope
    from src.blackboard.models import BoardEntry

    with session_scope() as session:
        session.query(BoardEntry).filter(
            BoardEntry.event_id.in_(list(event_ids))
        ).delete(synchronize_session=False)


# --- writing ----------------------------------------------------------------

def test_an_event_reaches_the_board(store):
    event_id = _eid()
    try:
        assert store.record_event(
            event_id=event_id, summary="Flooding in Ratnapura",
            domain="meteorological", severity="high", confidence=0.8,
            entity_keys=["Ratnapura"],
        )
        top = store.top_entries(limit=50)
        assert any(e["event_id"] == event_id for e in top)
    finally:
        _cleanup([event_id])


def test_a_repeat_reinforces_rather_than_duplicating(store):
    """
    THE behavioural point of B1.

    Today a semantic duplicate is DROPPED and its corroboration computed, used
    once for a confidence bump, and forgotten -- so six outlets reporting one
    flood are worth exactly as much as one tweet. Here a repeat raises
    salience and increments a count, which is what later makes corroborated
    things harder to evict.

    It also must not create a second row: the aggregator can see one event
    twice in a cycle, and a board counting re-processing as corroboration
    would be reporting confidence it does not have.
    """
    from auth.db import session_scope
    from src.blackboard.models import BoardEntry

    event_id = _eid()
    try:
        store.record_event(event_id=event_id, summary="Flood", severity="high")
        store.record_event(event_id=event_id, summary="Flood again",
                           severity="high")
        store.record_event(event_id=event_id, summary="Flood once more",
                           severity="high")

        with session_scope() as session:
            rows = session.query(BoardEntry).filter(
                BoardEntry.event_id == event_id).all()
            assert len(rows) == 1, "a repeat created a second row"
            assert rows[0].corroborations == 2
    finally:
        _cleanup([event_id])


def test_severity_dominates_the_starting_salience(store):
    """
    Confidence only modulates. An uncertain report of something critical still
    deserves attention -- discounting it heavily by confidence is how a system
    misses the thing it half-saw.
    """
    from src.blackboard.store import _base_salience_for

    assert _base_salience_for("critical", 0.3) > _base_salience_for("low", 1.0)
    assert 0.0 < _base_salience_for(None, None) <= 1.0


def test_the_board_never_takes_down_the_cycle_that_feeds_it(monkeypatch):
    """
    It is an enrichment during the shadow stages. A write failure must cost the
    board, never the feed.
    """
    from src.blackboard.store import BoardStore

    instance = BoardStore()
    monkeypatch.setattr(instance, "_sessions", lambda: (_ for _ in ()).throw(
        RuntimeError("database on fire")))

    # Must return None rather than raising.
    assert instance.record_event(event_id="x", summary="y") is None


def test_unavailable_is_distinguishable_from_empty(monkeypatch):
    """
    "The board is off" and "the board is empty" are different facts. This
    codebase has been bitten repeatedly by code reporting the second when it
    means the first.
    """
    from src.blackboard.store import BoardStore

    instance = BoardStore()
    monkeypatch.setattr(instance, "_sessions", lambda: None)
    assert instance.available() is False
    assert instance.top_entries() == []


# --- maintenance ------------------------------------------------------------

def test_a_faded_entry_is_evicted_and_a_fresh_one_is_not(store):
    from auth.db import session_scope
    from src.blackboard import maintenance
    from src.blackboard.models import BoardEntry

    stale_id, fresh_id = _eid(), _eid()
    try:
        store.record_event(event_id=stale_id, summary="old", severity="low")
        store.record_event(event_id=fresh_id, summary="new", severity="high")

        # Age the stale one by rewriting when it was last seen.
        with session_scope() as session:
            row = session.query(BoardEntry).filter(
                BoardEntry.event_id == stale_id).one()
            row.last_reinforced = datetime.now(timezone.utc) - timedelta(hours=48)
            row.created_at = datetime.now(timezone.utc) - timedelta(hours=48)

        maintenance.run()

        with session_scope() as session:
            remaining = {
                r.event_id for r in session.query(BoardEntry).filter(
                    BoardEntry.event_id.in_([stale_id, fresh_id])).all()
            }
        assert stale_id not in remaining, "a faded entry survived"
        assert fresh_id in remaining, "a fresh entry was evicted"
    finally:
        _cleanup([stale_id, fresh_id])


def test_an_entry_held_by_a_story_survives_eviction(store):
    """
    The story is the long-term memory of a developing situation. Deleting its
    contributing events leaves a thread whose evidence has vanished -- "44
    events" with nothing behind it.
    """
    from auth.db import session_scope
    from src.blackboard import maintenance
    from src.blackboard.models import BoardEntry

    event_id = _eid()
    try:
        store.record_event(event_id=event_id, summary="threaded",
                           severity="low", story_id="story-keepme")
        with session_scope() as session:
            row = session.query(BoardEntry).filter(
                BoardEntry.event_id == event_id).one()
            row.last_reinforced = datetime.now(timezone.utc) - timedelta(hours=40)
            row.created_at = datetime.now(timezone.utc) - timedelta(hours=40)

        maintenance.run()

        with session_scope() as session:
            assert session.query(BoardEntry).filter(
                BoardEntry.event_id == event_id).count() == 1
    finally:
        _cleanup([event_id])


def test_maintenance_reports_what_it_did(store):
    """A cleanup that reports nothing cannot be watched, and an unwatched
    cleanup is indistinguishable from one that stopped running."""
    from src.blackboard import maintenance

    stats = maintenance.run()
    assert set(stats) >= {"aged", "evicted", "foci_expired", "activations_pruned"}


# --- the leaks this closes --------------------------------------------------

def test_chromadb_can_delete_individual_events():
    """
    REGRESSION for a gap that predates the board: ChromaDBStore had NO delete
    at all -- only clear_collection(), which is all-or-nothing. The semantic
    corpus therefore grew forever.
    """
    from src.storage.chromadb_store import ChromaDBStore

    assert hasattr(ChromaDBStore, "delete_events")


def test_the_chromadb_document_count_actually_falls():
    """
    THE test that proves eviction reaches the layer that consumes disk.

    Asserting the method EXISTS is not the same as asserting it works. The
    corpus is the largest thing this system keeps, so "we added a delete" is
    worth nothing unless the count goes down -- and a delete that silently
    no-ops would look identical to one that works.
    """
    import uuid

    from src.storage.chromadb_store import ChromaDBStore

    store = ChromaDBStore()
    if not store.client:
        pytest.skip("ChromaDB unavailable")

    before = store.get_stats().get("total_documents", 0)

    ids = [f"evict-{uuid.uuid4().hex[:10]}" for _ in range(3)]
    for event_id in ids:
        store.add_event(event_id, f"Test flood event {event_id}")

    after_add = store.get_stats().get("total_documents", 0)
    assert after_add == before + 3, (
        f"expected {before + 3} documents after adding 3, got {after_add}"
    )

    store.delete_events(ids)

    after_delete = store.get_stats().get("total_documents", 0)
    assert after_delete == before, (
        f"documents did not fall back to {before} after eviction "
        f"(got {after_delete}); the semantic corpus still grows forever"
    )


def test_the_trending_cleanup_is_finally_called():
    """
    trending_detector.cleanup_old_data(days=7) has always existed and never
    been called -- the only caller of that NAME is StorageManager's own
    method, which prunes SQLite instead.
    """
    source = (PROJECT_ROOT / "src" / "blackboard" / "maintenance.py").read_text(
        encoding="utf-8")
    assert "cleanup_old_data" in source


def test_eviction_does_not_touch_the_sqlite_dedup_window():
    """
    THE regression hazard. If eviction removed a dedup entry younger than
    SQLITE_RETENTION_HOURS, the evicted event would look new on the next scrape
    and be re-emitted -- resurrecting the "same events every cycle forever" bug
    that dedup_key exists to prevent.
    """
    source = (PROJECT_ROOT / "src" / "blackboard" / "maintenance.py").read_text(
        encoding="utf-8")
    assert "sqlite_cache" not in source and "seen_hashes" not in source, (
        "maintenance touches the dedup window; evicted events would be "
        "re-emitted as new"
    )
