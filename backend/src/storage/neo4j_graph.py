"""
src/storage/neo4j_graph.py
Knowledge graph for event relationships and entity tracking
"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("neo4j_graph")

try:
    from neo4j import GraphDatabase

    NEO4J_AVAILABLE = True
except ImportError:
    NEO4J_AVAILABLE = False
    logger.warning("[Neo4j] Package not installed. Knowledge graph disabled.")

from .config import config


class Neo4jGraph:
    """
    Knowledge graph for tracking:
    - Event nodes with properties
    - Entity nodes (companies, politicians, locations)
    - Relationships (SIMILAR_TO, FOLLOWS, MENTIONS)
    """

    def __init__(self):
        self.driver = None

        if not NEO4J_AVAILABLE or not config.NEO4J_ENABLED:
            logger.info("[Neo4j] Disabled (set NEO4J_ENABLED=true to enable)")
            return

        try:
            self._init_driver()
            self._create_indexes()
            logger.info(f"[Neo4j] Connected to {config.NEO4J_URI}")
        except Exception as e:
            logger.error(f"[Neo4j] Connection failed: {e}")
            self.driver = None

    def _init_driver(self):
        """Initialize Neo4j driver"""
        self.driver = GraphDatabase.driver(
            config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD)
        )

        # Test connection
        self.driver.verify_connectivity()

    def _create_indexes(self):
        """Create indexes for faster queries"""
        if not self.driver:
            return

        with self.driver.session() as session:
            # Index on Event ID
            session.run(
                "CREATE INDEX event_id_index IF NOT EXISTS FOR (e:Event) ON (e.event_id)"
            )

            # Index on Entity name
            session.run(
                "CREATE INDEX entity_name_index IF NOT EXISTS FOR (ent:Entity) ON (ent.name)"
            )

            # Index on Domain
            session.run(
                "CREATE INDEX domain_index IF NOT EXISTS FOR (d:Domain) ON (d.name)"
            )

    def add_event(
        self,
        event_id: str,
        domain: str,
        summary: str,
        severity: str,
        impact_type: str,
        confidence_score: float,
        timestamp: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Add event node to knowledge graph"""
        if not self.driver:
            return

        with self.driver.session() as session:
            query = """
            MERGE (e:Event {event_id: $event_id})
            SET e.domain = $domain,
                e.summary = $summary,
                e.severity = $severity,
                e.impact_type = $impact_type,
                e.confidence_score = $confidence_score,
                e.timestamp = $timestamp,
                e.created_at = datetime()
            
            MERGE (d:Domain {name: $domain})
            MERGE (e)-[:BELONGS_TO]->(d)
            
            RETURN e.event_id as created_id
            """

            result = session.run(
                query,
                event_id=event_id,
                domain=domain,
                summary=summary[:2000],  # Store full summary (was 500)
                severity=severity,
                impact_type=impact_type,
                confidence_score=confidence_score,
                timestamp=timestamp,
            )

            created = result.single()
            if created:
                logger.debug(f"[Neo4j] Created event: {event_id[:8]}...")

    def link_similar_events(self, event_id_1: str, event_id_2: str, similarity: float):
        """Create SIMILAR_TO relationship between events"""
        if not self.driver:
            return

        with self.driver.session() as session:
            query = """
            MATCH (e1:Event {event_id: $id1})
            MATCH (e2:Event {event_id: $id2})
            MERGE (e1)-[r:SIMILAR_TO]-(e2)
            SET r.similarity = $similarity,
                r.created_at = datetime()
            """

            session.run(query, id1=event_id_1, id2=event_id_2, similarity=similarity)
            logger.debug(
                f"[Neo4j] Linked similar events: {event_id_1[:8]}... <-> {event_id_2[:8]}..."
            )

    def link_temporal_sequence(self, earlier_event_id: str, later_event_id: str):
        """Create FOLLOWS relationship for temporal sequence"""
        if not self.driver:
            return

        with self.driver.session() as session:
            query = """
            MATCH (e1:Event {event_id: $earlier_id})
            MATCH (e2:Event {event_id: $later_id})
            WHERE datetime(e2.timestamp) > datetime(e1.timestamp)
            MERGE (e1)-[r:FOLLOWS]->(e2)
            SET r.created_at = datetime()
            """

            session.run(query, earlier_id=earlier_event_id, later_id=later_event_id)

    def get_event_clusters(self, min_cluster_size: int = 2) -> List[Dict[str, Any]]:
        """Find clusters of similar events"""
        if not self.driver:
            return []

        with self.driver.session() as session:
            query = """
            MATCH (e1:Event)-[:SIMILAR_TO]-(e2:Event)
            WITH e1, COLLECT(e2) as similar_events
            WHERE SIZE(similar_events) >= $min_size
            RETURN e1.event_id as event_id,
                   e1.summary as summary,
                   SIZE(similar_events) as cluster_size
            ORDER BY cluster_size DESC
            LIMIT 10
            """

            results = session.run(query, min_size=min_cluster_size)

            clusters = []
            for record in results:
                clusters.append(
                    {
                        "event_id": record["event_id"],
                        "summary": record["summary"],
                        "cluster_size": record["cluster_size"],
                    }
                )

            return clusters

    def get_domain_stats(self) -> List[Dict[str, Any]]:
        """Get event count by domain"""
        if not self.driver:
            return []

        with self.driver.session() as session:
            query = """
            MATCH (e:Event)-[:BELONGS_TO]->(d:Domain)
            RETURN d.name as domain,
                   COUNT(e) as event_count
            ORDER BY event_count DESC
            """

            results = session.run(query)

            stats = []
            for record in results:
                stats.append(
                    {"domain": record["domain"], "event_count": record["event_count"]}
                )

            return stats

    def get_stats(self) -> Dict[str, Any]:
        """Get graph statistics"""
        if not self.driver:
            return {"status": "disabled"}

        try:
            with self.driver.session() as session:
                # Count nodes
                event_count = session.run(
                    "MATCH (e:Event) RETURN COUNT(e) as count"
                ).single()["count"]
                domain_count = session.run(
                    "MATCH (d:Domain) RETURN COUNT(d) as count"
                ).single()["count"]

                # Count relationships
                similar_count = session.run(
                    "MATCH ()-[r:SIMILAR_TO]-() RETURN COUNT(r) as count"
                ).single()["count"]

                return {
                    "status": "active",
                    "total_events": event_count,
                    "total_domains": domain_count,
                    "similarity_links": similar_count,
                    "uri": config.NEO4J_URI,
                }
        except Exception as e:
            logger.error(f"[Neo4j] Stats error: {e}")
            return {"status": "error", "error": str(e)}

    def close(self):
        """Close Neo4j driver connection"""
        if self.driver:
            self.driver.close()
            logger.info("[Neo4j] Connection closed")
