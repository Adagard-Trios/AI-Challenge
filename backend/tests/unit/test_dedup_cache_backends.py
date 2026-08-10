"""
The first-tier dedup cache, on both backends.

SQLiteCache wrote to a file on local disk. That is correct for one process and
wrong in two ways once deployed:

  - Per-replica. Every API pod reads it through
    StorageManager.get_feeds_since(), so the same event is "new" to each pod
    that has not seen it, and what a user sees depends on which one answered.
  - Ephemeral. Render's free tier has no persistent disk, so the file dies on
    every deploy, restart and spin-down -- and the first cycle afterwards
    re-emits events it had already suppressed.

The class keeps its name and its API; only the storage changes, chosen by
DATABASE_URL. That makes the important test a PARITY test: both backends must
answer identically, or moving between them changes behaviour in ways nobody
notices until the deployed instance behaves unlike the laptop.

The Postgres tests skip when DATABASE_URL is unset. The file-backend tests
always run, so the laptop path is always covered.
"""

import os
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _file_cache():
    from src.storage.sqlite_cache import SQLiteCache

    return SQLiteCache(db_path=tempfile.mktemp(suffix=".db"))


def _shared_cache():
    if not (os.getenv("DATABASE_URL") or "").strip():
        pytest.skip("DATABASE_URL unset (docker compose up -d postgres)")
    from auth.db import init_db
    from src.storage.sqlite_cache import SQLiteCache

    init_db()
    cache = SQLiteCache()
    if not cache._shared:
        pytest.skip("cache did not select the shared backend")
    return cache


@pytest.fixture(params=["file", "shared"])
def cache(request):
    """Every parity test below runs against both backends."""
    return _file_cache() if request.param == "file" else _shared_cache()


def _unique(prefix="Kelani river rising near Nagalagam"):
    return f"{prefix} {uuid.uuid4().hex[:8]}"


# --- parity -----------------------------------------------------------------

def test_an_unseen_summary_is_not_a_duplicate(cache):
    assert cache.has_exact_match(_unique()) == (False, None)


def test_a_stored_summary_is_a_duplicate_and_returns_its_event_id(cache):
    summary = _unique()
    cache.add_entry(summary, "ev-1")
    assert cache.has_exact_match(summary) == (True, "ev-1")


def test_restoring_the_same_content_touches_rather_than_duplicates(cache):
    """
    first_seen is when the content was FIRST observed, and the retention window
    is measured from last_seen. Overwriting first_seen on every sighting would
    make a long-running story look new each time it is mentioned.
    """
    summary = _unique()
    cache.add_entry(summary, "ev-1")
    first = cache.get_all_entries(limit=50)
    original = next(r for r in first if r["event_id"] == "ev-1")

    cache.add_entry(summary, "ev-2")
    after = cache.get_all_entries(limit=50)
    same = [r for r in after if r["content_hash"] == original["content_hash"]]

    assert len(same) == 1, "the same content produced a second row"
    assert same[0]["first_seen"] == original["first_seen"], (
        "first_seen was overwritten; the retention window would slide forever"
    )


def test_empty_input_is_never_a_duplicate(cache):
    assert cache.has_exact_match("") == (False, None)
    cache.add_entry("", "ev-x")   # must not raise


def test_search_is_case_insensitive(cache):
    """
    SQLite's LIKE is case-insensitive by default and Postgres's is NOT. A
    literal port of the SQL would have quietly made search case-sensitive on
    the deployed instance only -- the exact shape of bug this codebase keeps
    producing, where two paths disagree and one is never exercised locally.
    """
    summary = _unique("Ratnapura landslide warning")
    cache.add_entry(summary, "ev-1")

    assert cache.search_entries("ratnapura", limit=5), (
        "lowercase query found nothing; search is case-sensitive on this "
        "backend"
    )
    assert cache.search_entries("RATNAPURA", limit=5)


def test_entries_since_accepts_a_naive_timestamp(cache):
    """
    The file backend compared naive ISO strings, so callers pass naive values.
    A naive datetime against a timezone-aware column raises, which would have
    made get_feeds_since() return nothing -- an empty dashboard, no error.
    """
    cache.add_entry(_unique(), "ev-1")
    naive = (datetime.utcnow() - timedelta(minutes=5)).isoformat()
    assert len(cache.get_entries_since(naive)) >= 1


def test_cleanup_removes_only_what_is_past_retention(cache):
    """A cleanup that removes everything empties the dedup window, and the
    next cycle re-emits every event it had already suppressed."""
    cache.add_entry(_unique(), "ev-fresh")
    cache.cleanup_old_entries(retention_hours=24)
    assert cache.get_all_entries(limit=50), "cleanup removed fresh entries"


# --- the property the migration exists for ----------------------------------

def test_two_replicas_share_one_dedup_view():
    """
    THE test. Two cache instances, as two API replicas would be, against one
    database. Before this, each had its own file and neither could see the
    other's suppressions.
    """
    from src.storage.sqlite_cache import SQLiteCache

    first = _shared_cache()
    second = SQLiteCache()          # a separate replica

    summary = _unique("Flood warning Ratnapura")
    assert first.has_exact_match(summary) == (False, None)
    first.add_entry(summary, "ev-A")

    assert second.has_exact_match(summary) == (True, "ev-A"), (
        "a second replica does not see the first one's dedup entry, so the "
        "same event would be emitted twice"
    )


def test_an_explicit_path_always_means_the_file_backend():
    """
    Tests pass db_path. A test that silently wrote to the shared database
    would be worse than useless -- it would pollute real data and pass.
    """
    from src.storage.sqlite_cache import SQLiteCache

    cache = SQLiteCache(db_path=tempfile.mktemp(suffix=".db"))
    assert cache._shared is False


def test_the_shared_table_is_registered_for_creation():
    """
    Without the import in init_db, the table is never created and every lookup
    fails against a missing table -- reporting every event as new, which is
    silent and looks like a very busy news day.
    """
    source = (PROJECT_ROOT / "auth" / "db.py").read_text(encoding="utf-8")
    assert "seen_hashes_model" in source
