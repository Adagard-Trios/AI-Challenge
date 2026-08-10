"""
src/storage/sqlite_cache.py
Fast hash-based cache for first-tier deduplication.

TWO BACKENDS, ONE API
---------------------
The name is now half a lie: when DATABASE_URL is set this stores rows in that
database instead of a local SQLite file, and every method below routes to
whichever backend is in play. The class keeps its name and its signatures
because StorageManager and six call sites depend on both, and renaming it would
be a larger change than the one that matters.

The file backend is correct for a single process and is what a laptop runs.
It is wrong in two ways once deployed:

  - Per-replica. Every API pod reads its own copy through
    StorageManager.get_feeds_since(), so the same event is "new" to each one and
    what a user sees depends on which pod answered.
  - Ephemeral. Render's free tier has no persistent disk, so the file dies on
    every deploy, restart and spin-down -- and the first cycle afterwards
    re-emits events it had already suppressed.
"""

import sqlite3
import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from .config import config

logger = logging.getLogger("sqlite_cache")


def _shared_enabled() -> bool:
    """
    Whether to use the shared database rather than a local file.

    Keyed on DATABASE_URL because that is what already decides where accounts,
    stories and entities live; splitting dedup across a different store would
    let the two disagree about what exists.
    """
    return bool((os.getenv("DATABASE_URL") or "").strip())


class SQLiteCache:
    """
    Fast hash-based cache for exact match deduplication.
    Uses MD5 hash of first N characters for O(1) lookup.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or config.SQLITE_DB_PATH
        # An explicit db_path forces the file backend. Tests pass one, and a
        # test that silently wrote to the shared database would be worse than
        # useless.
        self._shared = _shared_enabled() and db_path is None

        if self._shared:
            logger.info("[SQLiteCache] using the shared database "
                        "(DATABASE_URL); dedup is visible to every replica")
        else:
            self._init_db()
            logger.info(f"[SQLiteCache] Initialized at {self.db_path}")

    # -- shared backend ------------------------------------------------------

    def _session(self):
        from auth.db import session_scope

        return session_scope()

    @staticmethod
    def _row_to_dict(row) -> dict:
        """
        Same shape the file backend returns, including ISO strings for the
        timestamps -- callers serialise these straight to JSON.
        """
        return {
            "content_hash": row.content_hash,
            "first_seen": row.first_seen.isoformat() if row.first_seen else None,
            "last_seen": row.last_seen.isoformat() if row.last_seen else None,
            "event_id": row.event_id,
            "summary_preview": row.summary_preview,
        }

    def _init_db(self):
        """Initialize database schema"""
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_hashes (
                content_hash TEXT PRIMARY KEY,
                first_seen TIMESTAMP NOT NULL,
                last_seen TIMESTAMP NOT NULL,
                event_id TEXT,
                summary_preview TEXT
            )
        """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_last_seen ON seen_hashes(last_seen)"
        )
        conn.commit()
        conn.close()

    def _get_hash(self, summary: str) -> str:
        """Generate MD5 hash from first N characters"""
        normalized = summary[: config.EXACT_MATCH_CHARS].strip().lower()
        return hashlib.md5(normalized.encode("utf-8")).hexdigest()

    def has_exact_match(
        self, summary: str, retention_hours: Optional[int] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if summary exists in cache (exact match).

        Returns:
            (is_duplicate, event_id)
        """
        if not summary:
            return False, None

        retention_hours = retention_hours or config.SQLITE_RETENTION_HOURS
        content_hash = self._get_hash(summary)

        if self._shared:
            from .seen_hashes_model import SeenHash

            cutoff = datetime.now(timezone.utc) - timedelta(hours=retention_hours)
            try:
                with self._session() as session:
                    row = (
                        session.query(SeenHash)
                        .filter(SeenHash.content_hash == content_hash,
                                SeenHash.last_seen > cutoff)
                        .one_or_none()
                    )
                    return (True, row.event_id) if row else (False, None)
            except Exception as exc:  # noqa: BLE001
                # Never let a dedup lookup take the cycle down. Reporting "not
                # a duplicate" risks a repeat; raising loses the event.
                logger.warning("[SQLiteCache] shared lookup failed (%s); "
                               "treating as new", exc)
                return False, None

        cutoff = datetime.utcnow() - timedelta(hours=retention_hours)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            "SELECT event_id FROM seen_hashes WHERE content_hash = ? AND last_seen > ?",
            (content_hash, cutoff.isoformat()),
        )
        result = cursor.fetchone()
        conn.close()

        if result:
            logger.debug(f"[SQLiteCache] EXACT MATCH found: {content_hash[:8]}...")
            return True, result[0]

        return False, None

    def add_entry(self, summary: str, event_id: str):
        """Add new entry to cache or update existing"""
        if not summary:
            return

        content_hash = self._get_hash(summary)
        preview = summary[:2000]  # Store full summary (was 200)

        if self._shared:
            from .seen_hashes_model import SeenHash, utcnow as _utcnow

            try:
                with self._session() as session:
                    row = session.get(SeenHash, content_hash)
                    if row is None:
                        session.add(SeenHash(
                            content_hash=content_hash,
                            first_seen=_utcnow(),
                            last_seen=_utcnow(),
                            event_id=event_id,
                            summary_preview=preview,
                        ))
                    else:
                        # Touch only last_seen. first_seen is when this content
                        # was FIRST observed and is what the retention window
                        # and the story timeline are measured from.
                        row.last_seen = _utcnow()
                logger.debug("[SQLiteCache] Added: %s... (%s)",
                             content_hash[:8], event_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[SQLiteCache] shared write failed (%s); this "
                               "event may be re-emitted next cycle", exc)
            return

        now = datetime.utcnow().isoformat()
        conn = sqlite3.connect(self.db_path)

        # Try update first
        cursor = conn.execute(
            "UPDATE seen_hashes SET last_seen = ? WHERE content_hash = ?",
            (now, content_hash),
        )

        # If no rows updated, insert new
        if cursor.rowcount == 0:
            conn.execute(
                "INSERT INTO seen_hashes VALUES (?, ?, ?, ?, ?)",
                (content_hash, now, now, event_id, preview),
            )

        conn.commit()
        conn.close()
        logger.debug(f"[SQLiteCache] Added: {content_hash[:8]}... ({event_id})")

    def cleanup_old_entries(self, retention_hours: Optional[int] = None):
        """Remove entries older than retention period"""
        retention_hours = retention_hours or config.SQLITE_RETENTION_HOURS

        if self._shared:
            from .seen_hashes_model import SeenHash

            cutoff = datetime.now(timezone.utc) - timedelta(hours=retention_hours)
            try:
                with self._session() as session:
                    deleted = (
                        session.query(SeenHash)
                        .filter(SeenHash.last_seen < cutoff)
                        .delete(synchronize_session=False)
                    )
                if deleted:
                    logger.info("[SQLiteCache] Cleaned up %d old entries", deleted)
                return deleted
            except Exception as exc:  # noqa: BLE001
                logger.warning("[SQLiteCache] shared cleanup failed: %s", exc)
                return 0

        cutoff = datetime.utcnow() - timedelta(hours=retention_hours)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            "DELETE FROM seen_hashes WHERE last_seen < ?", (cutoff.isoformat(),)
        )
        deleted = cursor.rowcount
        conn.commit()
        conn.close()

        if deleted > 0:
            logger.info(f"[SQLiteCache] Cleaned up {deleted} old entries")

        return deleted

    def get_all_entries(self, limit: int = 100, offset: int = 0) -> list:
        """
        Paginated retrieval of all cached entries.
        Returns list of dicts with event metadata.
        """
        if self._shared:
            from .seen_hashes_model import SeenHash

            try:
                with self._session() as session:
                    rows = (
                        session.query(SeenHash)
                        .order_by(SeenHash.last_seen.desc())
                        .limit(limit).offset(offset).all()
                    )
                    return [self._row_to_dict(r) for r in rows]
            except Exception as exc:  # noqa: BLE001
                logger.warning("[SQLiteCache] shared read failed: %s", exc)
                return []

        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            "SELECT content_hash, first_seen, last_seen, event_id, summary_preview FROM seen_hashes ORDER BY last_seen DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )

        results = []
        for row in cursor.fetchall():
            results.append(
                {
                    "content_hash": row[0],
                    "first_seen": row[1],
                    "last_seen": row[2],
                    "event_id": row[3],
                    "summary_preview": row[4],
                }
            )

        conn.close()
        return results

    def search_entries(self, query: str, limit: int = 10) -> list:
        """
        Search for entries containing specific text.
        Args:
            query: Text to search for (case-insensitive LIKE)
            limit: Max results
        """
        if not query or len(query) < 2:
            return []

        if self._shared:
            from .seen_hashes_model import SeenHash

            try:
                with self._session() as session:
                    rows = (
                        session.query(SeenHash)
                        # ilike, not like: SQLite's LIKE is case-insensitive by
                        # default and Postgres's is not, so a plain port would
                        # have quietly made search case-sensitive.
                        .filter(SeenHash.summary_preview.ilike(f"%{query}%"))
                        .order_by(SeenHash.last_seen.desc())
                        .limit(limit).all()
                    )
                    return [self._row_to_dict(r) for r in rows]
            except Exception as exc:  # noqa: BLE001
                logger.warning("[SQLiteCache] shared search failed: %s", exc)
                return []

        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            "SELECT content_hash, first_seen, last_seen, event_id, summary_preview FROM seen_hashes WHERE summary_preview LIKE ? ORDER BY last_seen DESC LIMIT ?",
            (f"%{query}%", limit),
        )

        results = []
        for row in cursor.fetchall():
            results.append(
                {
                    "content_hash": row[0],
                    "first_seen": row[1],
                    "last_seen": row[2],
                    "event_id": row[3],
                    "summary_preview": row[4],
                }
            )

        conn.close()
        return results

    def get_entries_since(self, timestamp: str) -> list:
        """
        Get entries added/updated after timestamp.

        Args:
            timestamp: ISO format timestamp string

        Returns:
            List of entry dicts
        """
        if self._shared:
            from .seen_hashes_model import SeenHash

            try:
                since = datetime.fromisoformat(str(timestamp))
                if since.tzinfo is None:
                    # The file backend compared naive ISO strings. A naive
                    # value here would raise against a timezone-aware column,
                    # so assume UTC -- which is what the caller was writing.
                    since = since.replace(tzinfo=timezone.utc)
                with self._session() as session:
                    rows = (
                        session.query(SeenHash)
                        .filter(SeenHash.last_seen > since)
                        .order_by(SeenHash.last_seen.desc()).all()
                    )
                    return [self._row_to_dict(r) for r in rows]
            except Exception as exc:  # noqa: BLE001
                logger.warning("[SQLiteCache] shared since-query failed: %s", exc)
                return []

        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            "SELECT content_hash, first_seen, last_seen, event_id, summary_preview FROM seen_hashes WHERE last_seen > ? ORDER BY last_seen DESC",
            (timestamp,),
        )

        results = []
        for row in cursor.fetchall():
            results.append(
                {
                    "content_hash": row[0],
                    "first_seen": row[1],
                    "last_seen": row[2],
                    "event_id": row[3],
                    "summary_preview": row[4],
                }
            )

        conn.close()
        return results

    def get_stats(self) -> dict:
        """Get cache statistics"""
        conn = sqlite3.connect(self.db_path)

        cursor = conn.execute("SELECT COUNT(*) FROM seen_hashes")
        total = cursor.fetchone()[0]

        cutoff_24h = datetime.utcnow() - timedelta(hours=24)
        cursor = conn.execute(
            "SELECT COUNT(*) FROM seen_hashes WHERE last_seen > ?",
            (cutoff_24h.isoformat(),),
        )
        last_24h = cursor.fetchone()[0]

        conn.close()

        return {
            "total_entries": total,
            "entries_last_24h": last_24h,
            "db_path": self.db_path,
        }
