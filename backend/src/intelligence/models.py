"""
src/intelligence/models.py
Entities, and what a business is exposed to.

Shares auth's declarative Base so `Base.metadata.create_all` in auth/db.py
creates these too -- this project has no Alembic, and adding a migration tool
for three tables is not the trade to make here.

Why these tables exist: the platform served an identical feed to every user.
Everstream's whole value is surfacing the threats relevant to a particular
organisation's own suppliers and trade lanes, and that requires knowing two
things the system never modelled -- what an event is about, and what the reader
depends on. Entity/EventEntity is the first; ExposureProfile is the second.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Index, JSON, String, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from auth.models import Base, new_id, utcnow


class Entity(Base):
    """
    A real-world thing events can be about: a district, a port, a sector, a
    company.

    `canonical_name` is the output of taxonomy.canonicalise(), never a raw
    surface form. "Colombo Port", "Port of Colombo" and "CMB" are one row --
    without that, a relevance join silently under-matches and the failure looks
    like a quiet news day.
    """

    __tablename__ = "entities"
    __table_args__ = (
        UniqueConstraint("entity_type", "canonical_name", name="uq_entity_identity"),
        Index("ix_entity_lookup", "entity_type", "canonical_name"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    entity_type: Mapped[str] = mapped_column(String(20))  # PLACE|ORG|SECTOR|...
    canonical_name: Mapped[str] = mapped_column(String(200))

    # False for anything outside the seed vocabulary -- typically a company.
    # Kept, but scored with less confidence than a known district or port.
    is_known: Mapped[bool] = mapped_column(Boolean, default=False)

    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class EventEntity(Base):
    """What a given event is about."""

    __tablename__ = "event_entities"
    __table_args__ = (
        UniqueConstraint("event_id", "entity_id", name="uq_event_entity"),
        Index("ix_event_entities_event", "event_id"),
        Index("ix_event_entities_entity", "entity_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    # Not a FK: events live in SQLite/Chroma, not Postgres. Deliberate -- the
    # feed store and the entity graph have different lifetimes and the feed is
    # pruned on a retention window.
    event_id: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("entities.id", ondelete="CASCADE")
    )

    # affected | actor | mentioned. "affected" is what relevance weights most:
    # your district flooding is not the same as your district's council
    # passing a bylaw.
    role: Mapped[str] = mapped_column(String(20), default="mentioned")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    entity: Mapped["Entity"] = relationship()


class ExposureProfile(Base):
    """
    What one user's business depends on.

    Per user, not global. The existing intel_config.json is a single shared
    file; conflating the two would give every account the same exposure and
    defeat the point.

    Lists are JSON rather than child tables on purpose: they are small, always
    read whole, never queried across users, and the alternative is five join
    tables to store what is effectively one form.
    """

    __tablename__ = "exposure_profiles"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )

    # Where the business physically is -- canonical district names.
    districts: Mapped[list] = mapped_column(JSON, default=list)
    # Ports, airports, expressways it depends on -- canonical infrastructure.
    infrastructure: Mapped[list] = mapped_column(JSON, default=list)
    # Named trade routes/corridors, free text.
    lanes: Mapped[list] = mapped_column(JSON, default=list)
    # Canonical sector names.
    sectors: Mapped[list] = mapped_column(JSON, default=list)
    # Named suppliers and counterparties. Highest-weight match.
    suppliers: Mapped[list] = mapped_column(JSON, default=list)
    # Anything the taxonomy does not model.
    keywords: Mapped[list] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    def is_empty(self) -> bool:
        """
        A user who has declared nothing gets the unranked feed.

        The caller must check this rather than scoring against an empty profile,
        which would mark every event irrelevant and quietly empty the feed for
        anyone who has not filled the form in.
        """
        return not any((
            self.districts, self.infrastructure, self.lanes,
            self.sectors, self.suppliers, self.keywords,
        ))

    def as_dict(self) -> dict:
        return {
            "districts": self.districts or [],
            "infrastructure": self.infrastructure or [],
            "lanes": self.lanes or [],
            "sectors": self.sectors or [],
            "suppliers": self.suppliers or [],
            "keywords": self.keywords or [],
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
