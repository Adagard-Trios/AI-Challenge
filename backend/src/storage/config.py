"""
src/storage/config.py
Centralized storage configuration with environment variable support
"""

import os
from pathlib import Path

# Base paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
CHROMADB_DIR = DATA_DIR / "chromadb"
NEO4J_DATA_DIR = DATA_DIR / "neo4j"
FEEDS_CSV_DIR = DATA_DIR / "feeds"

# Ensure directories exist
for dir_path in [DATA_DIR, CACHE_DIR, CHROMADB_DIR, NEO4J_DATA_DIR, FEEDS_CSV_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)


class StorageConfig:
    """Configuration for all storage backends"""

    # SQLite Configuration
    SQLITE_DB_PATH: str = os.getenv("SQLITE_DB_PATH", str(CACHE_DIR / "feeds.db"))
    SQLITE_RETENTION_HOURS: int = int(os.getenv("SQLITE_RETENTION_HOURS", "24"))

    # ChromaDB Configuration
    CHROMADB_PATH: str = os.getenv("CHROMADB_PATH", str(CHROMADB_DIR))
    CHROMADB_COLLECTION: str = os.getenv("CHROMADB_COLLECTION", "Roger_feeds")
    CHROMADB_SIMILARITY_THRESHOLD: float = float(
        os.getenv("CHROMADB_SIMILARITY_THRESHOLD", "0.85")
    )
    CHROMADB_EMBEDDING_MODEL: str = os.getenv(
        "CHROMADB_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
    )

    # Neo4j Configuration (supports both NEO4J_USER and NEO4J_USERNAME)
    NEO4J_URI: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_USER: str = os.getenv("NEO4J_USERNAME", os.getenv("NEO4J_USER", "neo4j"))
    NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "")
    NEO4J_DATABASE: str = os.getenv("NEO4J_DATABASE", "neo4j")
    # Auto-enable if URI contains 'neo4j.io' (Aura) or explicitly set
    NEO4J_ENABLED: bool = os.getenv(
        "NEO4J_ENABLED", ""
    ).lower() == "true" or "neo4j.io" in os.getenv("NEO4J_URI", "")

    # CSV Export Configuration
    CSV_EXPORT_DIR: str = os.getenv("CSV_EXPORT_DIR", str(FEEDS_CSV_DIR))

    # Deduplication Settings
    EXACT_MATCH_CHARS: int = int(os.getenv("EXACT_MATCH_CHARS", "120"))

    @classmethod
    def get_config_summary(cls) -> dict:
        """Get configuration summary for logging"""
        return {
            "sqlite_path": cls.SQLITE_DB_PATH,
            "chromadb_path": cls.CHROMADB_PATH,
            "chromadb_collection": cls.CHROMADB_COLLECTION,
            "similarity_threshold": cls.CHROMADB_SIMILARITY_THRESHOLD,
            "neo4j_enabled": cls.NEO4J_ENABLED,
            "neo4j_uri": cls.NEO4J_URI if cls.NEO4J_ENABLED else "disabled",
        }


config = StorageConfig()
