"""
src/utils/db_manager.py
Production-Grade Database Manager for Neo4j and ChromaDB
Handles feed aggregation, uniqueness checking, and vector storage
"""

import os
import hashlib
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import json

# Neo4j
try:
    from neo4j import GraphDatabase
    from neo4j.exceptions import ServiceUnavailable, AuthError

    NEO4J_AVAILABLE = True
except ImportError:
    NEO4J_AVAILABLE = False

# ChromaDB
try:
    import chromadb
    from chromadb.config import Settings
    from langchain_chroma import Chroma
    from langchain_core.documents import Document

    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False

logger = logging.getLogger("Roger.db_manager")
logger.setLevel(logging.INFO)


class Neo4jManager:
    """
    Production-grade Neo4j manager for multi-domain feed tracking.
    Supports separate labels for each agent domain:
    - PoliticalPost, EconomicalPost, MeteorologicalPost, SocialPost

    Handles:
    - Post uniqueness checking (URL + content hash) per domain
    - Post storage with metadata
    - Relationship tracking
    - Fast duplicate detection
    """

    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        domain: str = "political",
    ):
        """Initialize Neo4j connection with domain-specific labeling"""
        if not NEO4J_AVAILABLE:
            logger.warning(
                "[NEO4J] neo4j package not installed. Install with: pip install neo4j langchain-neo4j"
            )
            self.driver = None
            return

        # Set domain-specific label
        domain_map = {
            "political": "PoliticalPost",
            "economical": "EconomicalPost",
            "economic": "EconomicalPost",
            "meteorological": "MeteorologicalPost",
            "weather": "MeteorologicalPost",
            "social": "SocialPost",
        }
        self.domain = domain.lower()
        self.label = domain_map.get(self.domain, "Post")  # Fallback to generic Post

        self.uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.user = user or os.getenv("NEO4J_USER", "neo4j")
        self.password = password or os.getenv("NEO4J_PASSWORD", "password")

        try:
            self.driver = GraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password),
                max_connection_lifetime=3600,
                max_connection_pool_size=50,
                connection_acquisition_timeout=120,
            )
            # Test connection
            with self.driver.session() as session:
                session.run("RETURN 1")
            logger.info(f"[NEO4J] ✓ Connected to {self.uri}")
            logger.info(f"[NEO4J] ✓ Using label: {self.label} (domain: {self.domain})")

            # Create constraints and indexes
            self._create_constraints()

        except (ServiceUnavailable, AuthError) as e:
            logger.warning(f"[NEO4J] Connection failed: {e}. Running in fallback mode.")
            self.driver = None
        except Exception as e:
            logger.error(f"[NEO4J] Unexpected error: {e}")
            self.driver = None

    def _create_constraints(self):
        """Create database constraints and indexes for performance (domain-specific)"""
        if not self.driver:
            return

        # Domain-specific constraints using the label
        label = self.label
        constraints = [
            # Unique constraint on URL per domain
            f"CREATE CONSTRAINT {self.domain}_post_url_unique IF NOT EXISTS FOR (p:{label}) REQUIRE p.url IS UNIQUE",
            # Unique constraint on content hash per domain
            f"CREATE CONSTRAINT {self.domain}_post_hash_unique IF NOT EXISTS FOR (p:{label}) REQUIRE p.content_hash IS UNIQUE",
            # Index on timestamp for faster queries
            f"CREATE INDEX {self.domain}_post_timestamp IF NOT EXISTS FOR (p:{label}) ON (p.timestamp)",
            # Index on platform
            f"CREATE INDEX {self.domain}_post_platform IF NOT EXISTS FOR (p:{label}) ON (p.platform)",
            # Index on domain for cross-domain queries
            f"CREATE INDEX {self.domain}_post_domain IF NOT EXISTS FOR (p:{label}) ON (p.domain)",
        ]

        try:
            with self.driver.session() as session:
                for constraint in constraints:
                    try:
                        session.run(constraint)
                    except Exception as e:
                        # Constraint might already exist
                        logger.debug(f"[NEO4J] Constraint/Index note: {e}")
            logger.info("[NEO4J] ✓ Constraints and indexes verified")
        except Exception as e:
            logger.warning(f"[NEO4J] Could not create constraints: {e}")

    def is_duplicate(self, post_url: str, content_hash: str) -> bool:
        """
        Check if post already exists by URL or content hash within this domain
        Returns True if duplicate, False if unique
        """
        if not self.driver:
            return False  # Allow storage if Neo4j unavailable

        try:
            with self.driver.session() as session:
                # Check within domain-specific label
                query = f"""
                    MATCH (p:{self.label})
                    WHERE p.url = $url OR p.content_hash = $hash
                    RETURN COUNT(p) as count
                    """
                result = session.run(query, url=post_url, hash=content_hash)
                record = result.single()
                count = record["count"] if record else 0
                return count > 0
        except Exception as e:
            logger.error(f"[NEO4J] Error checking duplicate: {e}")
            return False  # Allow storage on error

    def store_post(self, post_data: Dict[str, Any]) -> bool:
        """
        Store a unique post in Neo4j with domain-specific label and metadata
        Returns True if stored successfully, False otherwise
        """
        if not self.driver:
            logger.warning("[NEO4J] Driver not available, skipping storage")
            return False

        try:
            with self.driver.session() as session:
                # Create or update post node with domain-specific label
                query = f"""
                    MERGE (p:{self.label} {{url: $url}})
                    SET p.content_hash = $content_hash,
                        p.timestamp = $timestamp,
                        p.platform = $platform,
                        p.category = $category,
                        p.district = $district,
                        p.poster = $poster,
                        p.title = $title,
                        p.text = $text,
                        p.engagement = $engagement,
                        p.source_tool = $source_tool,
                        p.domain = $domain,
                        p.updated_at = datetime()
                    """
                session.run(
                    query,
                    url=post_data.get("post_url", ""),
                    content_hash=post_data.get("content_hash", ""),
                    timestamp=post_data.get("timestamp", ""),
                    platform=post_data.get("platform", ""),
                    category=post_data.get("category", ""),
                    district=post_data.get("district", ""),
                    poster=post_data.get("poster", ""),
                    title=post_data.get("title", "")[:500],  # Limit length
                    text=post_data.get("text", "")[:2000],  # Limit length
                    engagement=json.dumps(post_data.get("engagement", {})),
                    source_tool=post_data.get("source_tool", ""),
                    domain=self.domain,
                )

                # Create relationships if district exists
                if post_data.get("district"):
                    district_query = f"""
                        MATCH (p:{self.label} {{url: $url}})
                        MERGE (d:District {{name: $district}})
                        MERGE (p)-[:LOCATED_IN]->(d)
                        """
                    session.run(
                        district_query,
                        url=post_data.get("post_url"),
                        district=post_data.get("district"),
                    )

                return True

        except Exception as e:
            logger.error(f"[NEO4J] Error storing post: {e}")
            return False

    def get_post_count(self) -> int:
        """Get total number of posts in database for this domain"""
        if not self.driver:
            return 0

        try:
            with self.driver.session() as session:
                query = f"MATCH (p:{self.label}) RETURN COUNT(p) as count"
                result = session.run(query)
                record = result.single()
                return record["count"] if record else 0
        except Exception as e:
            logger.error(f"[NEO4J] Error getting post count: {e}")
            return 0

    def close(self):
        """Close Neo4j connection"""
        if self.driver:
            self.driver.close()
            logger.info("[NEO4J] Connection closed")


class ChromaDBManager:
    """
    Production-grade ChromaDB manager for vector storage.
    Uses shared collection for all domains with metadata filtering.
    Handles:
    - Persistent vector storage for RAG
    - Document chunking and embeddings
    - Collection management
    - Domain-based filtering
    """

    def __init__(
        self,
        collection_name: str = "Roger_feeds",  # Shared collection
        persist_directory: Optional[str] = None,
        embedding_function=None,
        domain: str = "political",
    ):
        """Initialize ChromaDB with persistent storage and text splitter"""
        if not CHROMA_AVAILABLE:
            logger.warning(
                "[CHROMADB] chromadb/langchain-chroma not installed. Install with: pip install chromadb langchain-chroma"
            )
            self.client = None
            self.collection = None
            return

        self.domain = domain.lower()
        self.collection_name = collection_name  # Shared collection for all domains
        self.persist_directory = persist_directory or os.getenv(
            "CHROMADB_PATH", "./data/chromadb"
        )

        # Create directory if it doesn't exist
        os.makedirs(self.persist_directory, exist_ok=True)

        try:
            # Initialize ChromaDB client with persistence
            self.client = chromadb.PersistentClient(
                path=self.persist_directory,
                settings=Settings(anonymized_telemetry=False, allow_reset=True),
            )

            # Get or create shared collection for all domains
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={
                    "description": "Multi-domain feeds for RAG chatbot (Political, Economic, Weather, Social)"
                },
            )

            # Initialize Text Splitter
            try:
                from langchain_text_splitters import RecursiveCharacterTextSplitter

                self.text_splitter = RecursiveCharacterTextSplitter(
                    chunk_size=1000,
                    chunk_overlap=200,
                    separators=["\n\n", "\n", ". ", " ", ""],
                )
                logger.info("[CHROMADB] ✓ Text splitter initialized (1000/200)")
            except ImportError:
                logger.warning(
                    "[CHROMADB] langchain-text-splitters not found. Using simple fallback."
                )
                self.text_splitter = None

            logger.info(
                f"[CHROMADB] ✓ Connected to collection '{self.collection_name}'"
            )
            logger.info(f"[CHROMADB] ✓ Domain: {self.domain}")
            logger.info(f"[CHROMADB] ✓ Persist directory: {self.persist_directory}")
            logger.info(
                f"[CHROMADB] ✓ Current document count: {self.collection.count()}"
            )

        except Exception as e:
            logger.error(f"[CHROMADB] Initialization error: {e}")
            self.client = None
            self.collection = None

    def add_document(self, post_data: Dict[str, Any]) -> bool:
        """
        Add a post as a document to ChromaDB.
        Splits long text into chunks for better RAG performance.
        Returns True if added successfully, False otherwise.
        """
        if not self.collection:
            logger.warning("[CHROMADB] Collection not available, skipping storage")
            return False

        try:
            # Prepare content
            title = post_data.get("title", "N/A")
            text = post_data.get("text", "")

            # Combine title and text for context
            full_content = f"Title: {title}\n\n{text}"

            # Split text into chunks
            chunks = []
            if self.text_splitter and len(full_content) > 1200:
                chunks = self.text_splitter.split_text(full_content)
            else:
                chunks = [full_content]

            # Prepare batch data
            ids = []
            documents = []
            metadatas = []

            base_id = post_data.get("post_id", post_data.get("content_hash", ""))

            for i, chunk in enumerate(chunks):
                # Unique ID for each chunk
                chunk_id = f"{base_id}_chunk_{i}"

                # Metadata (duplicated for each chunk for filtering)
                meta = {
                    "post_id": base_id,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "domain": self.domain,  # Add domain for filtering
                    "timestamp": post_data.get("timestamp", ""),
                    "platform": post_data.get("platform", ""),
                    "category": post_data.get("category", ""),
                    "district": post_data.get("district", ""),
                    "poster": post_data.get("poster", ""),
                    "post_url": post_data.get("post_url", ""),
                    "source_tool": post_data.get("source_tool", ""),
                }

                ids.append(chunk_id)
                documents.append(chunk)
                metadatas.append(meta)

            # Add to ChromaDB
            self.collection.add(documents=documents, metadatas=metadatas, ids=ids)

            logger.debug(f"[CHROMADB] Added {len(chunks)} chunks for post {base_id}")
            return True

        except Exception as e:
            logger.error(f"[CHROMADB] Error adding document: {e}")
            return False

    def get_document_count(self) -> int:
        """Get total number of documents in collection"""
        if not self.collection:
            return 0

        try:
            return self.collection.count()
        except Exception as e:
            logger.error(f"[CHROMADB] Error getting document count: {e}")
            return 0

    def search(self, query: str, n_results: int = 5) -> List[Dict[str, Any]]:
        """Search for similar documents"""
        if not self.collection:
            return []

        try:
            results = self.collection.query(query_texts=[query], n_results=n_results)
            return results
        except Exception as e:
            logger.error(f"[CHROMADB] Error searching: {e}")
            return []


def generate_content_hash(poster: str, text: str) -> str:
    """
    Generate SHA256 hash from poster + text for uniqueness checking
    """
    content = f"{poster}|{text}".strip()
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def extract_post_data(
    raw_post: Dict[str, Any], category: str, platform: str, source_tool: str
) -> Optional[Dict[str, Any]]:
    """
    Extract and normalize post data from raw feed item
    Returns None if post data is invalid
    """
    try:
        # Extract fields with fallbacks
        poster = (
            raw_post.get("author")
            or raw_post.get("poster")
            or raw_post.get("username")
            or "unknown"
        )
        text = (
            raw_post.get("text")
            or raw_post.get("selftext")
            or raw_post.get("snippet")
            or raw_post.get("description")
            or ""
        )

        # ENHANCED: Handle gazette extracted_content field (PDF text)
        # This ensures PDF content flows into RAG for proper indexing
        extracted_content = raw_post.get("extracted_content", [])
        if extracted_content and isinstance(extracted_content, list):
            # Combine all extracted PDF content
            pdf_texts = []
            for item in extracted_content:
                if isinstance(item, dict) and item.get("content"):
                    content = item.get("content", "")
                    if content and not content.startswith("["):  # Skip error messages
                        pdf_texts.append(content)

            if pdf_texts:
                # Prepend PDF content to text for better RAG search
                combined_pdf = "\n\n".join(pdf_texts)
                if text:
                    text = f"{combined_pdf}\n\n{text}"
                else:
                    text = combined_pdf

        # Also check for summary field (gazette entries have this)
        if not text and raw_post.get("summary"):
            text = raw_post.get("summary", "")
        title = raw_post.get("title") or raw_post.get("headline") or ""
        post_url = (
            raw_post.get("url")
            or raw_post.get("link")
            or raw_post.get("permalink")
            or ""
        )

        # Skip if no meaningful content
        if not text and not title:
            return None

        if not post_url:
            # Generate a pseudo-URL if none exists
            post_url = f"no-url://{platform}/{category}/{generate_content_hash(poster, text)[:16]}"

        # Generate content hash for uniqueness
        content_hash = generate_content_hash(poster, text + title)

        # Extract engagement metrics
        engagement = {
            "score": raw_post.get("score", 0),
            "likes": raw_post.get("likes", 0),
            "shares": raw_post.get("shares", 0),
            "comments": raw_post.get("num_comments", 0) or raw_post.get("comments", 0),
        }

        # Build normalized post data
        post_data = {
            "post_id": raw_post.get("id", content_hash[:16]),
            "timestamp": raw_post.get("timestamp")
            or raw_post.get("created_utc")
            or datetime.utcnow().isoformat(),
            "platform": platform,
            "category": category,
            "district": raw_post.get("district", ""),
            "poster": poster[:200],  # Limit length
            "post_url": post_url,
            "title": title[:500],  # Limit length
            "text": text,  # Full text - ChromaDB splitter handles chunking
            "content_hash": content_hash,
            "engagement": engagement,
            "source_tool": source_tool,
        }

        return post_data

    except Exception as e:
        logger.error(f"[EXTRACT] Error extracting post data: {e}")
        return None
