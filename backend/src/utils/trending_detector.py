"""
src/utils/trending_detector.py
Trending/Velocity Detection Module for Roger

Tracks topic mention frequency over time to detect:
- Topics gaining traction (momentum)
- Sudden volume spikes (alerts)
- Trending topics across the system

Uses SQLite for persistence.
"""

import os
import json
import sqlite3
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path

logger = logging.getLogger("Roger.trending")

# Default database path
DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "trending.db"
)

# Stopwords - common terms that should NOT trigger trending alerts
# These are generic Sri Lankan context words that appear in almost every news item
TRENDING_STOPWORDS = {
    # Country/location
    "sri",
    "lanka",
    "srilanka",
    "sri lanka",
    "colombo",
    "lka",
    # Government/political generic terms
    "government",
    "gov",
    "political",
    "politics",
    "minister",
    "ministry",
    "parliament",
    "president",
    "presidential",
    "cabinet",
    # Economy generic terms
    "economy",
    "economic",
    "economical",
    "finance",
    "financial",
    # Common news words
    "news",
    "report",
    "update",
    "latest",
    "breaking",
    "today",
    "announced",
    "statement",
    "official",
    "officials",
    # Time words
    "yesterday",
    "tomorrow",
    "week",
    "month",
    "year",
    "hour",
    "minute",
    "second",
    "time",
    "date",
    # Days
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    # Months
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    # Generic actions/descriptions
    "said",
    "says",
    "told",
    "according",
    "sources",
    "media",
    "press",
    "release",
    "statement",
    "general",
    "public",
    "national",
    "international",
    "local",
    "central",
    "department",
    "division",
    "authority",
    "board",
    "committee",
    "director",
    "secretary",
    "commission",
    "report",
    "reports",
    "reported",
    # Location generic
    "district",
    "province",
    "area",
    "region",
    "island",
    "nation",
    "country",
    "state",
    "western",
    "eastern",
    "southern",
    "northern",
    "central",
}


class TrendingDetector:
    """
    Detects trending topics and velocity spikes.

    Features:
    - Records topic mentions with timestamps
    - Calculates momentum (current_hour / avg_last_6_hours)
    - Detects spikes (>3x normal volume in 1 hour)
    - Returns trending topics for dashboard display
    """

    def __init__(
        self,
        db_path: str = None,
        spike_threshold: float = 3.0,
        momentum_threshold: float = 2.0,
    ):
        """
        Initialize the TrendingDetector.

        Args:
            db_path: Path to SQLite database (default: data/trending.db)
            spike_threshold: Multiplier for spike detection (default: 3x)
            momentum_threshold: Minimum momentum to be considered trending (default: 2.0)
        """
        self.db_path = db_path or DEFAULT_DB_PATH
        self.spike_threshold = spike_threshold
        self.momentum_threshold = momentum_threshold

        # Ensure directory exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        # Initialize database
        self._init_db()
        logger.info(f"[TrendingDetector] Initialized with db: {self.db_path}")

    def _init_db(self):
        """Create tables if they don't exist"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS topic_mentions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT NOT NULL,
                    topic_hash TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    source TEXT,
                    domain TEXT
                )
            """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_topic_hash ON topic_mentions(topic_hash)
            """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_timestamp ON topic_mentions(timestamp)
            """
            )

            # Hourly aggregates for faster queries
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS hourly_counts (
                    topic_hash TEXT NOT NULL,
                    hour_bucket TEXT NOT NULL,
                    count INTEGER DEFAULT 1,
                    topic TEXT,
                    PRIMARY KEY (topic_hash, hour_bucket)
                )
            """
            )
            conn.commit()

    def _topic_hash(self, topic: str) -> str:
        """Generate a hash for a topic (normalized lowercase)"""
        normalized = topic.lower().strip()
        return hashlib.md5(normalized.encode()).hexdigest()[:12]

    def _get_hour_bucket(self, dt: datetime = None) -> str:
        """Get the hour bucket string (YYYY-MM-DD-HH)"""
        dt = dt or datetime.now(timezone.utc)
        return dt.strftime("%Y-%m-%d-%H")

    def record_mention(
        self,
        topic: str,
        source: str = None,
        domain: str = None,
        timestamp: datetime = None,
    ):
        """
        Record a topic mention.

        Args:
            topic: The topic/keyword mentioned
            source: Source of the mention (e.g., 'twitter', 'news')
            domain: Domain (e.g., 'political', 'economical')
            timestamp: When the mention occurred (default: now)
        """
        # Skip stopwords - common generic terms that shouldn't trigger trending
        normalized_topic = topic.lower().strip()
        if normalized_topic in TRENDING_STOPWORDS:
            return  # Silently skip stopwords

        topic_hash = self._topic_hash(topic)
        ts = timestamp or datetime.now(timezone.utc)
        hour_bucket = self._get_hour_bucket(ts)

        with sqlite3.connect(self.db_path) as conn:
            # Insert mention
            conn.execute(
                """
                INSERT INTO topic_mentions (topic, topic_hash, timestamp, source, domain)
                VALUES (?, ?, ?, ?, ?)
            """,
                (topic.lower().strip(), topic_hash, ts.isoformat(), source, domain),
            )

            # Update hourly aggregate
            conn.execute(
                """
                INSERT INTO hourly_counts (topic_hash, hour_bucket, count, topic)
                VALUES (?, ?, 1, ?)
                ON CONFLICT(topic_hash, hour_bucket) DO UPDATE SET count = count + 1
            """,
                (topic_hash, hour_bucket, topic.lower().strip()),
            )

            conn.commit()

    def record_mentions_batch(self, mentions: List[Dict[str, Any]]):
        """
        Record multiple mentions at once.

        Args:
            mentions: List of dicts with keys: topic, source, domain, timestamp
        """
        for mention in mentions:
            self.record_mention(
                topic=mention.get("topic", ""),
                source=mention.get("source"),
                domain=mention.get("domain"),
                timestamp=mention.get("timestamp"),
            )

    def get_momentum(self, topic: str) -> float:
        """
        Calculate momentum for a topic.

        Momentum = mentions_in_current_hour / avg_mentions_in_last_6_hours

        Returns:
            Momentum value (1.0 = normal, >2.0 = trending, >3.0 = spike)
        """
        topic_hash = self._topic_hash(topic)
        now = datetime.now(timezone.utc)
        current_hour = self._get_hour_bucket(now)

        with sqlite3.connect(self.db_path) as conn:
            # Get current hour count
            result = conn.execute(
                """
                SELECT count FROM hourly_counts 
                WHERE topic_hash = ? AND hour_bucket = ?
            """,
                (topic_hash, current_hour),
            ).fetchone()
            current_count = result[0] if result else 0

            # Get average of last 6 hours
            past_hours = []
            for i in range(1, 7):
                past_dt = now - timedelta(hours=i)
                past_hours.append(self._get_hour_bucket(past_dt))

            placeholders = ",".join(["?" for _ in past_hours])
            result = conn.execute(
                f"""
                SELECT AVG(count) FROM hourly_counts 
                WHERE topic_hash = ? AND hour_bucket IN ({placeholders})
            """,
                [topic_hash] + past_hours,
            ).fetchone()
            avg_count = (
                result[0] if result and result[0] else 0.1
            )  # Avoid division by zero

            return current_count / avg_count if avg_count > 0 else current_count

    def is_spike(self, topic: str, window_hours: int = 1) -> bool:
        """
        Check if a topic is experiencing a spike.

        A spike is when current volume > spike_threshold * normal volume.
        """
        momentum = self.get_momentum(topic)
        return momentum >= self.spike_threshold

    def get_trending_topics(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get topics with momentum above threshold.

        Returns:
            List of trending topics with their momentum values
        """
        now = datetime.now(timezone.utc)
        current_hour = self._get_hour_bucket(now)

        trending = []

        with sqlite3.connect(self.db_path) as conn:
            # Get all topics mentioned in current hour
            results = conn.execute(
                """
                SELECT DISTINCT topic, topic_hash, count 
                FROM hourly_counts 
                WHERE hour_bucket = ?
                ORDER BY count DESC
                LIMIT 50
            """,
                (current_hour,),
            ).fetchall()

            for topic, topic_hash, count in results:
                momentum = self.get_momentum(topic)

                if momentum >= self.momentum_threshold:
                    trending.append(
                        {
                            "topic": topic,
                            "momentum": round(momentum, 2),
                            "mentions_this_hour": count,
                            "is_spike": momentum >= self.spike_threshold,
                            "severity": (
                                "high"
                                if momentum >= 5
                                else "medium" if momentum >= 3 else "low"
                            ),
                        }
                    )

        # Sort by momentum descending
        trending.sort(key=lambda x: x["momentum"], reverse=True)
        return trending[:limit]

    def get_spike_alerts(self, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Get topics with spike alerts (>3x normal volume).

        Returns:
            List of spike alerts
        """
        return [t for t in self.get_trending_topics(limit=50) if t["is_spike"]][:limit]

    def get_topic_history(self, topic: str, hours: int = 24) -> List[Dict[str, Any]]:
        """
        Get hourly mention counts for a topic.

        Args:
            topic: Topic to get history for
            hours: Number of hours to look back

        Returns:
            List of hourly counts
        """
        topic_hash = self._topic_hash(topic)
        now = datetime.now(timezone.utc)

        history = []
        with sqlite3.connect(self.db_path) as conn:
            for i in range(hours):
                hour_dt = now - timedelta(hours=i)
                hour_bucket = self._get_hour_bucket(hour_dt)

                result = conn.execute(
                    """
                    SELECT count FROM hourly_counts 
                    WHERE topic_hash = ? AND hour_bucket = ?
                """,
                    (topic_hash, hour_bucket),
                ).fetchone()

                history.append(
                    {"hour": hour_bucket, "count": result[0] if result else 0}
                )

        return list(reversed(history))  # Oldest first

    def cleanup_old_data(self, days: int = 7):
        """
        Remove data older than specified days.

        Args:
            days: Number of days to keep
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_str = cutoff.isoformat()
        cutoff_bucket = self._get_hour_bucket(cutoff)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                DELETE FROM topic_mentions WHERE timestamp < ?
            """,
                (cutoff_str,),
            )
            conn.execute(
                """
                DELETE FROM hourly_counts WHERE hour_bucket < ?
            """,
                (cutoff_bucket,),
            )
            conn.commit()

        logger.info(f"[TrendingDetector] Cleaned up data older than {days} days")


# Singleton instance for easy access
_trending_detector = None


def get_trending_detector() -> TrendingDetector:
    """Get the global TrendingDetector instance"""
    global _trending_detector
    if _trending_detector is None:
        _trending_detector = TrendingDetector()
    return _trending_detector


# Convenience functions
def record_topic_mention(topic: str, source: str = None, domain: str = None):
    """Record a single topic mention"""
    get_trending_detector().record_mention(topic, source, domain)


def get_trending_now(limit: int = 10) -> List[Dict[str, Any]]:
    """Get current trending topics"""
    return get_trending_detector().get_trending_topics(limit)


def get_spikes() -> List[Dict[str, Any]]:
    """Get current spike alerts"""
    return get_trending_detector().get_spike_alerts()
