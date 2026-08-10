"""
src/storage/seen_hashes_model.py
The first-tier dedup table, as a shared-database model.

WHY
---
SQLiteCache writes to a file on local disk (data/cache/feeds.db). Every API
replica reads it through StorageManager.get_feeds_since(), so with more than one
replica each has its own private view of what has already been seen: the same
event is "new" to every pod that has not seen it, and the feed a user gets
depends on which one they reached.

On the deployed instance it is worse than divergent -- it is ephemeral. Render's
free tier has no persistent disk, so the file is destroyed on every deploy,
restart and spin-down, taking the whole dedup window with it. The first cycle
after a restart therefore re-emits events it had already suppressed.

Putting this on the same DATABASE_URL as everything else fixes both, and needs
no new infrastructure: auth/db.py already owns that engine and already handles
Neon autosuspend and the Supabase pooler.

This is a MODEL ONLY. The switch lives in sqlite_cache.py, which keeps its
existing API so nothing above it changes.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Index, String, Text

from auth.models import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SeenHash(Base):
    """
    One row per deduplicated summary.

    Mirrors the original SQLite schema exactly -- same primary key, same
    columns, same index -- so behaviour does not change with the backend. The
    only difference is that first_seen/last_seen are real timestamps rather than
    ISO strings, because comparing strings only works while everyone agrees to
    write ISO-8601 and Postgres would rather not.
    """

    __tablename__ = "seen_hashes"

    content_hash = Column(String(64), primary_key=True)
    first_seen = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    last_seen = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    event_id = Column(String(64), nullable=True)
    # Not truncated to 200: storage_manager stores the full summary here so the
    # COLLECTED POSTS panel and search have something to read.
    summary_preview = Column(Text, nullable=True)


Index("idx_seen_hashes_last_seen", SeenHash.last_seen)
