"""
src/blackboard/models.py
Board tables, on the same SQLAlchemy Base as everything else.

WHY POSTGRES AND NOT REDIS OR A DICT
------------------------------------
A dict fails the moment there is a second replica, which is the situation this
project is now in. Redis would work but buys nothing here -- a few hundred
writes an hour, and the board must be QUERIED (ordered by salience, filtered by
domain, joined to stories), which is a database's job. And auth/db.py already
owns an engine that handles Neon autosuspend and the Supabase pooler, while
auth/schema_sync.py already does additive migrations. Adding a second store
would mean two things to configure, two to back up, and two to be down.

SQLite still has to work, because that is what the test suite and a laptop run
on. Nothing here uses a Postgres-only type.

WHAT IS DELIBERATELY NOT A TABLE
--------------------------------
Situations. A "story" is exactly a thread of related events with a regenerated
brief and a derived state, and src/intelligence/stories.py already implements
that, including escalation tracking and the developing/quiet/resolved
derivation. Duplicating it here would create two answers to "what is going on",
and the wrong one would be the one with the newer code.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Float, Index, Integer, String, Text,
)
from sqlalchemy.types import JSON

from auth.models import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BoardEntry(Base):
    """
    One thing the board currently believes.

    `level` separates an EVENT (something happened) from an ASSESSMENT (what
    the situation adds up to). They live in one table because they share every
    lifecycle concern -- salience, decay, eviction, provenance -- and splitting
    them would duplicate all of it to express a distinction that one column
    already makes.
    """

    __tablename__ = "board_entries"

    id = Column(String(32), primary_key=True)
    level = Column(String(12), nullable=False)      # event | assessment
    kind = Column(String(32), nullable=False, default="insight")
    domain = Column(String(24), nullable=True)

    # Join key into SQLite/Chroma/the entity store. NOT a foreign key, for the
    # same reason EventEntity.event_id is not: those rows have different
    # lifetimes and are pruned on different schedules, so a constraint would
    # make one subsystem's cleanup fail another's writes.
    event_id = Column(String(64), nullable=True, index=True)

    summary = Column(Text, nullable=True)
    severity = Column(String(12), nullable=True)
    impact_type = Column(String(16), nullable=True)
    confidence = Column(Float, nullable=True)

    # Salience at creation, before any decay. Kept so decay is recomputable
    # from first principles rather than being a lossy running product -- a
    # value that can only be multiplied down cannot be audited or corrected.
    base_salience = Column(Float, nullable=False, default=0.5)

    # Materialised by the decay pass so eviction is an index scan rather than
    # an exponential evaluated per row per query.
    salience = Column(Float, nullable=False, default=0.5)

    # How many independent sources have said this. Today a semantic duplicate
    # is DROPPED and the corroboration count is computed, used once for a
    # confidence bump, and forgotten. Six outlets reporting one flood should be
    # harder to evict than one tweet, not identical to it.
    corroborations = Column(Integer, nullable=False, default=0)

    # Canonical entity names, via taxonomy.canonicalise_many. The focus join
    # key: matching only works if "Ratnapura" and "Ratnapura District" are one
    # thing.
    entity_keys = Column(JSON, nullable=True)

    story_id = Column(String(32), nullable=True, index=True)

    # Which knowledge source wrote this. Non-negotiable: a board without
    # provenance cannot explain why it believes anything, and this codebase
    # already treats an unexplained score as a number with authority and no
    # accountability.
    source_ks = Column(String(64), nullable=True)

    payload = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    last_reinforced = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    # A hard floor independent of salience. Without it a heavily reinforced
    # entry could outlive its own relevance indefinitely, which is how a board
    # stops describing the present.
    expires_at = Column(DateTime(timezone=True), nullable=True)


Index("idx_board_level_salience", BoardEntry.level, BoardEntry.salience)
Index("idx_board_domain_created", BoardEntry.domain, BoardEntry.created_at)
Index("idx_board_expires", BoardEntry.expires_at)


class BoardFocus(Base):
    """
    "Look here." The control object that makes scheduling opportunistic rather
    than fixed.

    focus_key is unique and reinforced on conflict, which is what stops this
    table growing: three flood alerts in Ratnapura are ONE focus with rising
    urgency, not three rows competing for the same attention.
    """

    __tablename__ = "board_foci"

    id = Column(String(32), primary_key=True)
    focus_key = Column(String(160), nullable=False, unique=True)
    kind = Column(String(24), nullable=False)     # district|sector|entity|topic|story
    value = Column(String(120), nullable=False)
    urgency = Column(Float, nullable=False, default=0.5)

    # Always populated, and human-readable: "rivernet: Kelani at DANGER".
    # A focus that cannot say why it exists cannot be argued with, and the
    # first question about any scheduling decision is "why did it do that".
    reason = Column(Text, nullable=True)

    source_ks = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    last_reinforced = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    satisfied_at = Column(DateTime(timezone=True), nullable=True)


Index("idx_focus_urgency", BoardFocus.urgency)
Index("idx_focus_expires", BoardFocus.expires_at)


class KSActivation(Base):
    """
    The agenda ledger.

    One table doing four jobs on purpose: the shared last-run clock for
    starvation avoidance across replicas, the claim record that stops two
    replicas running one knowledge source, the audit trail for why something
    was skipped, and the substrate for shadow mode -- where the controller
    records what it WOULD have done while the existing fan-out still runs, so
    its judgement can be checked before it is trusted.

    It must itself be pruned. At ~25 sources against a 60-second tick this is
    ~1,500 rows an hour, and an audit table that grows forever is the same bug
    it exists to help find.
    """

    __tablename__ = "ks_activations"

    id = Column(String(32), primary_key=True)
    ks_name = Column(String(64), nullable=False)
    tick_id = Column(String(32), nullable=True, index=True)

    decided_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    executed = Column(Boolean, nullable=False, default=False)
    skipped_reason = Column(String(64), nullable=True)

    priority = Column(Float, nullable=True)
    trigger_reason = Column(Text, nullable=True)

    # Estimated BEFORE the call and actual after, because the estimate is what
    # the budget gate decides on and the gap between them is the only way to
    # know whether the gate is calibrated.
    est_tokens = Column(Integer, nullable=True)
    actual_tokens = Column(Integer, nullable=True)

    duration_ms = Column(Integer, nullable=True)
    entries_written = Column(Integer, nullable=True)

    claimed_by = Column(String(64), nullable=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)


Index("idx_ks_name_decided", KSActivation.ks_name, KSActivation.decided_at)
Index("idx_ks_decided", KSActivation.decided_at)
