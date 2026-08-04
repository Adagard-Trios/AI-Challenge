"""
src/storage/chromadb_store.py
Semantic similarity search using ChromaDB with sentence transformers
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger("chromadb_store")

try:
    import chromadb
    from chromadb.config import Settings

    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    logger.warning("[ChromaDB] Package not installed. Semantic deduplication disabled.")

from .config import config


class ChromaDBStore:
    """
    Semantic similarity search for advanced deduplication.
    Uses sentence transformers to detect paraphrased/similar content.
    """

    def __init__(self):
        self.client = None
        self.collection = None

        if not CHROMADB_AVAILABLE:
            logger.warning(
                "[ChromaDB] Not available - using fallback (no semantic dedup)"
            )
            return

        try:
            self._init_client()
            logger.info(
                f"[ChromaDB] Initialized collection: {config.CHROMADB_COLLECTION}"
            )
        except Exception as e:
            logger.error(f"[ChromaDB] Initialization failed: {e}")
            self.client = None

    def _init_client(self):
        """Initialize ChromaDB client and collection"""
        self.client = chromadb.PersistentClient(
            path=config.CHROMADB_PATH,
            settings=Settings(anonymized_telemetry=False, allow_reset=True),
        )

        # Get or create collection with sentence transformer embedding
        self.collection = self.client.get_or_create_collection(
            name=config.CHROMADB_COLLECTION,
            metadata={
                "description": "Roger intelligence feed semantic deduplication",
                "embedding_model": config.CHROMADB_EMBEDDING_MODEL,
            },
        )

    def find_similar(
        self, summary: str, threshold: Optional[float] = None, n_results: int = 1
    ) -> Optional[Dict[str, Any]]:
        """
        Find semantically similar entries.

        Returns:
            Dict with {id, summary, distance, metadata} if found, else None
        """
        if not self.client or not summary:
            return None

        threshold = threshold or config.CHROMADB_SIMILARITY_THRESHOLD

        try:
            results = self.collection.query(query_texts=[summary], n_results=n_results)

            if not results["ids"] or not results["ids"][0]:
                return None

            # ChromaDB returns L2 distance (lower is more similar)
            # Convert to similarity score (higher is more similar)
            distance = results["distances"][0][0]

            # For L2 distance, typical range is 0-2 for normalized embeddings
            # Convert to similarity: 1 - (distance / 2)
            similarity = 1.0 - min(distance / 2.0, 1.0)

            if similarity >= threshold:
                match_id = results["ids"][0][0]
                match_meta = results["metadatas"][0][0] if results["metadatas"] else {}
                match_doc = results["documents"][0][0] if results["documents"] else ""

                logger.info(
                    f"[ChromaDB] SEMANTIC MATCH found: "
                    f"similarity={similarity:.3f} (threshold={threshold}) "
                    f"id={match_id[:8]}..."
                )

                return {
                    "id": match_id,
                    "summary": match_doc,
                    "similarity": similarity,
                    "distance": distance,
                    "metadata": match_meta,
                }

            return None

        except Exception as e:
            logger.error(f"[ChromaDB] Query error: {e}")
            return None

    def add_event(
        self, event_id: str, summary: str, metadata: Optional[Dict[str, Any]] = None
    ):
        """Add event to ChromaDB for future similarity checks"""
        if not self.client or not summary:
            return

        try:
            # Prepare metadata (ChromaDB doesn't support nested dicts or None values)
            safe_metadata = {}
            if metadata:
                for key, value in metadata.items():
                    if value is not None and not isinstance(value, (dict, list)):
                        safe_metadata[key] = str(value)

            # Add timestamp
            safe_metadata["indexed_at"] = datetime.utcnow().isoformat()

            self.collection.add(
                ids=[event_id], documents=[summary], metadatas=[safe_metadata]
            )

            logger.debug(f"[ChromaDB] Added event: {event_id[:8]}...")

        except Exception as e:
            logger.error(f"[ChromaDB] Add error: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get collection statistics"""
        if not self.client:
            return {"status": "unavailable"}

        try:
            count = self.collection.count()
            return {
                "status": "active",
                "total_documents": count,
                "collection_name": config.CHROMADB_COLLECTION,
                "embedding_model": config.CHROMADB_EMBEDDING_MODEL,
                "similarity_threshold": config.CHROMADB_SIMILARITY_THRESHOLD,
            }
        except Exception as e:
            logger.error(f"[ChromaDB] Stats error: {e}")
            return {"status": "error", "error": str(e)}

    def clear_collection(self):
        """Clear all entries (use with caution!)"""
        if not self.client:
            return

        try:
            self.client.delete_collection(config.CHROMADB_COLLECTION)
            self._init_client()  # Recreate empty collection
            logger.warning("[ChromaDB] Collection cleared!")
        except Exception as e:
            logger.error(f"[ChromaDB] Clear error: {e}")
