"""
src/storage/storage_manager.py
Unified storage manager orchestrating 3-tier deduplication pipeline
"""

import logging
import re
from typing import Dict, Any, List, Optional, Tuple
import csv
from datetime import datetime
from pathlib import Path

from .config import config
from .sqlite_cache import SQLiteCache
from .chromadb_store import ChromaDBStore
from .neo4j_graph import Neo4jGraph

logger = logging.getLogger("storage_manager")

# Trending detection integration
try:
    from ..utils.trending_detector import record_topic_mention

    TRENDING_AVAILABLE = True
except ImportError:
    TRENDING_AVAILABLE = False
    logger.warning("[StorageManager] Trending detector not available")


class StorageManager:
    """
    Unified storage interface implementing 3-tier deduplication:

    Tier 1: SQLite - Fast hash lookup (microseconds)
    Tier 2: ChromaDB - Semantic similarity (milliseconds)
    Tier 3: Accept unique events

    Also handles:
    - Feed persistence (CSV export)
    - Knowledge graph tracking (Neo4j)
    - Statistics and monitoring
    """

    def __init__(self):
        logger.info("[StorageManager] Initializing multi-database storage system")

        # Initialize all storage backends
        self.sqlite_cache = SQLiteCache()
        self.chromadb = ChromaDBStore()
        self.neo4j = Neo4jGraph()

        # Statistics tracking
        self.stats = {
            "total_processed": 0,
            "exact_duplicates": 0,
            "semantic_duplicates": 0,
            "unique_stored": 0,
            "errors": 0,
        }

        logger.info("[StorageManager] Configuration loaded")

    def is_duplicate(
        self, summary: str, threshold: Optional[float] = None
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Check if summary is duplicate using 3-tier pipeline.

        Returns:
            (is_duplicate, reason, match_data)

        Reasons:
            - "exact_match" - SQLite hash match
            - "semantic_match" - ChromaDB similarity match
            - "unique" - New event
        """
        if not summary or len(summary.strip()) < 10:
            return False, "too_short", None

        self.stats["total_processed"] += 1

        # TIER 1: SQLite exact match (fastest)
        is_exact, event_id = self.sqlite_cache.has_exact_match(summary)
        if is_exact:
            self.stats["exact_duplicates"] += 1
            logger.info(f"[DEDUPE] ✓ EXACT MATCH (SQLite): {summary[:60]}...")
            return True, "exact_match", {"matched_event_id": event_id}

        # TIER 2: ChromaDB semantic similarity
        similar = self.chromadb.find_similar(summary, threshold=threshold)
        if similar:
            self.stats["semantic_duplicates"] += 1
            logger.info(
                f"[DEDUPE] ✓ SEMANTIC MATCH (ChromaDB): "
                f"similarity={similar['similarity']:.3f} | {summary[:60]}..."
            )
            return True, "semantic_match", similar

        # TIER 3: Unique event
        logger.info(f"[DEDUPE] ✓ UNIQUE EVENT: {summary[:60]}...")
        return False, "unique", None

    def store_event(
        self,
        event_id: str,
        summary: str,
        domain: str,
        severity: str,
        impact_type: str,
        confidence_score: float,
        timestamp: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Store event in all databases.
        Should only be called AFTER is_duplicate() returns False.
        """
        timestamp = timestamp or datetime.utcnow().isoformat()

        try:
            # Store in SQLite cache
            self.sqlite_cache.add_entry(summary, event_id)

            # Store in ChromaDB for semantic search
            chroma_metadata = {
                "domain": domain,
                "severity": severity,
                "impact_type": impact_type,
                "confidence_score": confidence_score,
                "timestamp": timestamp,
            }
            self.chromadb.add_event(event_id, summary, chroma_metadata)

            # Store in Neo4j knowledge graph
            self.neo4j.add_event(
                event_id=event_id,
                domain=domain,
                summary=summary,
                severity=severity,
                impact_type=impact_type,
                confidence_score=confidence_score,
                timestamp=timestamp,
                metadata=metadata,
            )

            # Record keywords for trending detection
            if TRENDING_AVAILABLE:
                self._record_trending_mentions(summary, domain, metadata)

            self.stats["unique_stored"] += 1
            logger.debug(f"[STORE] Stored event {event_id[:8]}... in all databases")

        except Exception as e:
            self.stats["errors"] += 1
            logger.error(f"[STORE] Error storing event: {e}")

    def _extract_keywords(self, text: str, max_keywords: int = 5) -> List[str]:
        """
        Extract significant keywords from text for trending detection.

        Args:
            text: Text to extract keywords from
            max_keywords: Maximum number of keywords to return

        Returns:
            List of keywords (2-3 word phrases)
        """
        # Common stopwords to filter out
        stopwords = {
            "the",
            "is",
            "at",
            "which",
            "on",
            "a",
            "an",
            "and",
            "or",
            "but",
            "in",
            "with",
            "to",
            "for",
            "of",
            "as",
            "by",
            "from",
            "that",
            "this",
            "be",
            "are",
            "was",
            "were",
            "been",
            "being",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "must",
            "shall",
            "can",
            "need",
            "dare",
            "ought",
            "used",
            "सिंहल",
            "தமிழ்",  # Common Sinhala/Tamil particles
        }

        # Clean text
        text = text.lower()
        text = re.sub(r"http\S+|www\.\S+", "", text)  # Remove URLs
        text = re.sub(r"[^\w\s]", " ", text)  # Remove punctuation

        # Split into words
        words = text.split()

        # Filter stopwords and short words
        filtered = [w for w in words if w not in stopwords and len(w) > 2]

        # Extract significant words (prioritize proper nouns, locations, etc.)
        keywords = []

        # Single important words (capitalized in original or long words)
        for word in filtered[:20]:
            if len(word) > 4:  # Longer words are often more significant
                keywords.append(word)

        # Deduplicate and limit
        seen = set()
        unique_keywords = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                unique_keywords.append(kw)

        return unique_keywords[:max_keywords]

    def _record_trending_mentions(
        self, summary: str, domain: str, metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Extract keywords from summary and record them for trending detection.

        Args:
            summary: Event summary text
            domain: Event domain (political, economical, etc.)
            metadata: Optional metadata with platform info
        """
        try:
            keywords = self._extract_keywords(summary)
            source = metadata.get("platform", "scraper") if metadata else "scraper"

            for keyword in keywords:
                record_topic_mention(topic=keyword, source=source, domain=domain)

            if keywords:
                logger.debug(
                    f"[TRENDING] Recorded {len(keywords)} keywords: {keywords[:3]}..."
                )

        except Exception as e:
            logger.warning(f"[TRENDING] Error recording mentions: {e}")

    def link_similar_events(self, event_id_1: str, event_id_2: str, similarity: float):
        """Create similarity link in Neo4j"""
        self.neo4j.link_similar_events(event_id_1, event_id_2, similarity)

    def export_feed_to_csv(
        self, feed: List[Dict[str, Any]], filename: Optional[str] = None
    ):
        """
        Export feed to CSV for archival and analysis.
        Creates daily files by default.
        """
        if not feed:
            return

        try:
            # Generate filename
            if filename is None:
                date_str = datetime.utcnow().strftime("%Y-%m-%d")
                filename = f"feed_{date_str}.csv"

            filepath = Path(config.CSV_EXPORT_DIR) / filename
            filepath.parent.mkdir(parents=True, exist_ok=True)

            # Check if file exists to decide whether to write header
            file_exists = filepath.exists()

            fieldnames = [
                "event_id",
                "timestamp",
                "domain",
                "severity",
                "impact_type",
                "confidence_score",
                "summary",
            ]

            with open(filepath, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)

                if not file_exists:
                    writer.writeheader()

                for event in feed:
                    writer.writerow(
                        {
                            "event_id": event.get("event_id", ""),
                            "timestamp": event.get("timestamp", ""),
                            "domain": event.get(
                                "domain", event.get("target_agent", "")
                            ),
                            "severity": event.get("severity", ""),
                            "impact_type": event.get("impact_type", ""),
                            "confidence_score": event.get(
                                "confidence_score", event.get("confidence", 0)
                            ),
                            "summary": event.get(
                                "summary", event.get("content_summary", "")
                            ),
                        }
                    )

            logger.info(f"[CSV] Exported {len(feed)} events to {filepath}")

        except Exception as e:
            logger.error(f"[CSV] Export error: {e}")

    def get_recent_feeds(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Retrieve recent feeds from SQLite with ChromaDB metadata.

        Args:
            limit: Maximum number of feeds to return

        Returns:
            List of feed dictionaries with full metadata
        """
        try:
            entries = self.sqlite_cache.get_all_entries(limit=limit, offset=0)

            feeds = []
            for entry in entries:
                event_id = entry.get("event_id")
                if not event_id:
                    continue

                try:
                    chroma_data = self.chromadb.collection.get(ids=[event_id])
                    if chroma_data and chroma_data["metadatas"]:
                        metadata = chroma_data["metadatas"][0]
                        feeds.append(
                            {
                                "event_id": event_id,
                                "summary": entry.get("summary_preview", ""),
                                "domain": metadata.get("domain", "unknown"),
                                "severity": metadata.get("severity", "medium"),
                                "impact_type": metadata.get("impact_type", "risk"),
                                "confidence": metadata.get("confidence_score", 0.5),
                                "timestamp": metadata.get(
                                    "timestamp", entry.get("last_seen")
                                ),
                            }
                        )
                except Exception as e:
                    logger.warning(f"Could not fetch ChromaDB data for {event_id}: {e}")
                    feeds.append(
                        {
                            "event_id": event_id,
                            "summary": entry.get("summary_preview", ""),
                            "domain": "unknown",
                            "severity": "medium",
                            "impact_type": "risk",
                            "confidence": 0.5,
                            "timestamp": entry.get("last_seen"),
                        }
                    )

            return feeds

        except Exception as e:
            logger.error(f"[FEED_RETRIEVAL] Error: {e}")
            return []

        return feeds

    def search_feeds(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Search feeds by keyword and return enriched results.
        """
        try:
            entries = self.sqlite_cache.search_entries(query, limit=limit)
            feeds = []

            for entry in entries:
                event_id = entry.get("event_id")
                if not event_id:
                    continue

                try:
                    # Try to get metadata from Chroma (optional)
                    chroma_data = self.chromadb.collection.get(ids=[event_id])
                    metadata = {}
                    if chroma_data and chroma_data["metadatas"]:
                        metadata = chroma_data["metadatas"][0]

                    feeds.append(
                        {
                            "event_id": event_id,
                            "summary": entry.get("summary_preview", ""),
                            "domain": metadata.get("domain", "unknown"),
                            "severity": metadata.get("severity", "medium"),
                            "timestamp": metadata.get(
                                "timestamp", entry.get("last_seen")
                            ),
                            "source": metadata.get("source", "feed"),
                        }
                    )
                except Exception:
                    # Fallback if chroma fails
                    feeds.append(
                        {
                            "event_id": event_id,
                            "summary": entry.get("summary_preview", ""),
                            "domain": "unknown",
                            "severity": "medium",
                            "timestamp": entry.get("last_seen"),
                        }
                    )

            return feeds

        except Exception as e:
            logger.error(f"[FEED_SEARCH] Error searching for '{query}': {e}")
            return []

    def get_feeds_since(self, timestamp: datetime) -> List[Dict[str, Any]]:
        """
        Get all feeds added after given timestamp.

        Args:
            timestamp: Datetime object

        Returns:
            List of feed dictionaries
        """
        try:
            iso_timestamp = timestamp.isoformat()
            entries = self.sqlite_cache.get_entries_since(iso_timestamp)

            feeds = []
            for entry in entries:
                event_id = entry.get("event_id")
                if not event_id:
                    continue

                try:
                    chroma_data = self.chromadb.collection.get(ids=[event_id])
                    if chroma_data and chroma_data["metadatas"]:
                        metadata = chroma_data["metadatas"][0]
                        feeds.append(
                            {
                                "event_id": event_id,
                                "summary": entry.get("summary_preview", ""),
                                "domain": metadata.get("domain", "unknown"),
                                "severity": metadata.get("severity", "medium"),
                                "impact_type": metadata.get("impact_type", "risk"),
                                "confidence": metadata.get("confidence_score", 0.5),
                                "timestamp": metadata.get(
                                    "timestamp", entry.get("last_seen")
                                ),
                            }
                        )
                except Exception:
                    feeds.append(
                        {
                            "event_id": event_id,
                            "summary": entry.get("summary_preview", ""),
                            "domain": "unknown",
                            "severity": "medium",
                            "impact_type": "risk",
                            "confidence": 0.5,
                            "timestamp": entry.get("last_seen"),
                        }
                    )

            return feeds

        except Exception as e:
            logger.error(f"[FEED_RETRIEVAL] Error: {e}")
            return []

    def get_feed_count(self) -> int:
        """Get total feed count from database"""
        try:
            stats = self.sqlite_cache.get_stats()
            return stats.get("total_entries", 0)
        except Exception as e:
            logger.error(f"[FEED_COUNT] Error: {e}")
            return 0

    def cleanup_old_data(self):
        """Cleanup old entries from SQLite cache"""
        try:
            deleted = self.sqlite_cache.cleanup_old_entries()
            if deleted > 0:
                logger.info(f"[CLEANUP] Removed {deleted} old cache entries")
        except Exception as e:
            logger.error(f"[CLEANUP] Error: {e}")

    def get_comprehensive_stats(self) -> Dict[str, Any]:
        """Get statistics from all storage backends"""
        return {
            "deduplication": {
                **self.stats,
                "dedup_rate": (
                    (self.stats["exact_duplicates"] + self.stats["semantic_duplicates"])
                    / max(self.stats["total_processed"], 1)
                    * 100
                ),
            },
            "sqlite": self.sqlite_cache.get_stats(),
            "chromadb": self.chromadb.get_stats(),
            "neo4j": self.neo4j.get_stats(),
        }

    def __del__(self):
        """Cleanup on destruction"""
        try:
            self.neo4j.close()
        except Exception:
            pass  # Ignore close errors
