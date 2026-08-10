"""
src/intelligence/entity_store.py
Where entities and their links to events live.

One interface, one Postgres implementation today. The interface exists because
Neo4j is a plausible future home for this -- the codebase already carries the
driver and a graph schema -- but `render.yaml` sets NEO4J_ENABLED=false, so
building on it now would ship a flagship feature that never runs. That is the
exact failure this project keeps producing, and it is not worth repeating for a
query that is one join.

When multi-hop questions actually arrive ("which of my suppliers depend on a
port that is congested"), add a Neo4j implementation behind the same interface.
Until then, Postgres is provisioned, already holds users, and answers the
question being asked.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Protocol

logger = logging.getLogger("entity_store")


class EntityStore(Protocol):
    """The seam. A backend swap should not touch a caller."""

    def link_event(self, event_id: str, entities: Iterable[dict]) -> int:
        """Attach canonical entities to an event. Returns how many were linked."""
        ...

    def entities_for(self, event_ids: Iterable[str]) -> Dict[str, List[dict]]:
        """{event_id: [entity, ...]} for a batch of events."""
        ...


class NullEntityStore:
    """
    Used when no database is configured -- local runs, tests, the connector.

    Reports what it dropped rather than pretending to have stored it. A silent
    no-op store would make relevance scoring return nothing with no explanation,
    which is precisely the class of bug this codebase has spent two audits
    removing.
    """

    def __init__(self):
        self.dropped = 0

    def link_event(self, event_id: str, entities: Iterable[dict]) -> int:
        n = len(list(entities or []))
        if n:
            self.dropped += n
            logger.debug(
                "[entity_store] no database configured; dropped %d entities for %s",
                n, event_id,
            )
        return 0

    def entities_for(self, event_ids: Iterable[str]) -> Dict[str, List[dict]]:
        return {}


class PostgresEntityStore:
    """
    SQLAlchemy-backed store, sharing the session factory the auth package
    already uses against Supabase.
    """

    def __init__(self, session_factory=None):
        if session_factory is None:
            # auth.db exposes session_factory() -- a function returning the
            # sessionmaker -- not a SessionLocal binding. Importing the wrong
            # name raised, get_entity_store() caught it, and every write went
            # to NullEntityStore: the feature would have looked implemented and
            # stored nothing. Caught by the end-to-end check, not by a unit test.
            from auth.db import session_factory as _factory

            session_factory = _factory()
        self._session_factory = session_factory

    def link_event(self, event_id: str, entities: Iterable[dict]) -> int:
        from src.intelligence.models import Entity, EventEntity

        entities = [e for e in (entities or []) if e.get("name")]
        if not event_id or not entities:
            return 0

        linked = 0
        try:
            with self._session_factory() as session:
                for item in entities:
                    entity = (
                        session.query(Entity)
                        .filter_by(
                            entity_type=item["type"], canonical_name=item["name"]
                        )
                        .one_or_none()
                    )
                    if entity is None:
                        entity = Entity(
                            entity_type=item["type"],
                            canonical_name=item["name"],
                            is_known=bool(item.get("known")),
                        )
                        session.add(entity)
                        session.flush()

                    # An event mentioning the same entity twice is one link.
                    exists = (
                        session.query(EventEntity)
                        .filter_by(event_id=event_id, entity_id=entity.id)
                        .one_or_none()
                    )
                    if exists is None:
                        session.add(
                            EventEntity(
                                event_id=event_id,
                                entity_id=entity.id,
                                role=item.get("role", "mentioned"),
                            )
                        )
                        linked += 1

                session.commit()
        except Exception as exc:
            # Loud, and does not take the cycle down with it. Relevance degrades
            # to "no entities" for this event, which the caller can see.
            logger.error("[entity_store] link failed for %s: %s", event_id, exc)
            return 0

        return linked

    def entities_for(self, event_ids: Iterable[str]) -> Dict[str, List[dict]]:
        from src.intelligence.models import Entity, EventEntity

        ids = [i for i in (event_ids or []) if i]
        if not ids:
            return {}

        out: Dict[str, List[dict]] = {}
        try:
            with self._session_factory() as session:
                rows = (
                    session.query(EventEntity, Entity)
                    .join(Entity, Entity.id == EventEntity.entity_id)
                    .filter(EventEntity.event_id.in_(ids))
                    .all()
                )
                for link, entity in rows:
                    out.setdefault(link.event_id, []).append({
                        "type": entity.entity_type,
                        "name": entity.canonical_name,
                        "role": link.role,
                        "known": entity.is_known,
                    })
        except Exception as exc:
            logger.error("[entity_store] lookup failed: %s", exc)
            return {}

        return out


_store: Optional[Any] = None


def get_entity_store():
    """
    The configured store.

    Falls back to NullEntityStore when no database is reachable, so a local run
    or a test never fails on this -- but the fallback counts what it drops
    rather than silently swallowing it.
    """
    global _store
    if _store is None:
        try:
            _store = PostgresEntityStore()
            logger.info("[entity_store] using Postgres")
        except Exception as exc:
            logger.warning(
                "[entity_store] no database available (%s); entities will not "
                "be stored and relevance scoring will have nothing to join on",
                exc,
            )
            _store = NullEntityStore()
    return _store


def set_entity_store(store) -> None:
    """Tests."""
    global _store
    _store = store
