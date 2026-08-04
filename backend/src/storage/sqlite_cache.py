"""
src/storage/sqlite_cache.py
Fast hash-based cache for first-tier deduplication
"""

import sqlite3
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple
from .config import config

logger = logging.getLogger("sqlite_cache")


class SQLiteCache:
    """
    Fast hash-based cache for exact match deduplication.
    Uses MD5 hash of first N characters for O(1) lookup.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or config.SQLITE_DB_PATH
        self._init_db()
        logger.info(f"[SQLiteCache] Initialized at {self.db_path}")

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
        now = datetime.utcnow().isoformat()
        preview = summary[:2000]  # Store full summary (was 200)

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
