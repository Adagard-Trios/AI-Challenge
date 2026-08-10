"""
src/blackboard/store.py
Reading and writing the board.

DESIGN NOTES THAT MATTER
------------------------
Every method degrades to a no-op or an empty result when there is no database.
That is not defensiveness for its own sake: the board is an ENRICHMENT during
the shadow stages, and a board that cannot be written must never take down the
collection cycle that feeds it. StoryTracker already sets this precedent, and
also demonstrates its risk -- it degrades so quietly that "no database" and
"nothing happened" look identical. So every failure here logs, and
`available()` exists so callers can report the difference rather than infer it.

Writes are upsert-by-event_id rather than insert. The aggregator can see the
same event twice in one cycle (the LLM filter batches, the poller re-reads), and
a board that accumulated duplicates would be reporting confidence it does not
have -- corroborations would count re-processing rather than sources.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger("Roger.blackboard.store")


def _new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BoardStore:
    """Repository over the board tables. Stateless; construct freely."""

    # -- plumbing ----------------------------------------------------------

    def _sessions(self):
        try:
            from auth.db import session_scope

            return session_scope
        except Exception as exc:  # noqa: BLE001
            logger.debug("[board] no database: %s", exc)
            return None

    def available(self) -> bool:
        """
        Whether the board can actually be used.

        Exists so a caller can say "the board is off" rather than "the board is
        empty". Those are different facts and this codebase has been bitten
        repeatedly by code that reports the second when it means the first.
        """
        try:
            from .models import BoardEntry

            factory = self._sessions()
            if factory is None:
                return False

            with factory() as session:
                session.query(BoardEntry).limit(1).all()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.debug("[board] unavailable: %s", exc)
            return False

    # -- writing -----------------------------------------------------------

    def record_event(
        self,
        *,
        event_id: str,
        summary: str,
        domain: Optional[str] = None,
        severity: Optional[str] = None,
        impact_type: Optional[str] = None,
        confidence: Optional[float] = None,
        entity_keys: Optional[Iterable[str]] = None,
        story_id: Optional[str] = None,
        source_ks: str = "aggregator",
        payload: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Put an event on the board, or reinforce it if it is already there.

        Reinforcement is the important half. Today a semantic duplicate is
        DROPPED and its corroboration computed, used once for a confidence
        bump, and forgotten -- so six outlets reporting one flood are worth
        exactly as much as one tweet. Here a repeat raises salience and
        increments a count, which is what makes corroborated things harder to
        evict.
        """
        if not event_id:
            return None

        from .decay import decayed_salience, expiry_for
        from .models import BoardEntry

        try:
            # Inside the try, deliberately. _sessions() catches its own
            # failures today, but calling it outside meant that if it ever
            # raised for a reason it did not anticipate, the exception would
            # escape into the agent cycle -- breaking the exact guarantee this
            # method's docstring makes.
            factory = self._sessions()
            if factory is None:
                return None

            with factory() as session:
                existing = (
                    session.query(BoardEntry)
                    .filter(BoardEntry.event_id == event_id,
                            BoardEntry.level == "event")
                    .one_or_none()
                )

                if existing is not None:
                    existing.corroborations = (existing.corroborations or 0) + 1
                    existing.last_reinforced = utcnow()
                    existing.salience = decayed_salience(
                        existing.base_salience,
                        existing.severity,
                        existing.last_reinforced,
                        corroborations=existing.corroborations,
                    )
                    return existing.id

                base = _base_salience_for(severity, confidence)
                entry = BoardEntry(
                    id=_new_id(),
                    level="event",
                    kind="insight",
                    domain=domain,
                    event_id=event_id,
                    summary=(summary or "")[:4000],
                    severity=severity,
                    impact_type=impact_type,
                    confidence=confidence,
                    base_salience=base,
                    salience=base,
                    corroborations=0,
                    entity_keys=list(entity_keys) if entity_keys else [],
                    story_id=story_id,
                    source_ks=source_ks,
                    payload=payload or {},
                    created_at=utcnow(),
                    last_reinforced=utcnow(),
                    expires_at=expiry_for(severity),
                )
                session.add(entry)
                return entry.id
        except Exception as exc:  # noqa: BLE001
            # Never let the board take down the cycle that feeds it.
            logger.warning("[board] could not record %s: %s", event_id, exc)
            return None

    def record_assessment(
        self, *, snapshot: Dict[str, Any], source_ks: str = "data_refresher"
    ) -> Optional[str]:
        """
        The current risk picture, as a board entry.

        Superseding rather than updating: keeping the series is what lets a
        later stage show how an index MOVED, which a single mutable row cannot.
        Old ones are evicted by the decay pass like anything else.
        """
        if not snapshot:
            return None

        from .models import BoardEntry

        try:
            factory = self._sessions()
            if factory is None:
                return None

            with factory() as session:
                entry = BoardEntry(
                    id=_new_id(),
                    level="assessment",
                    kind="risk_snapshot",
                    domain=None,
                    summary="risk snapshot",
                    # Assessments are current-or-nothing: a fifteen-minute-old
                    # index is not evidence, it is history.
                    base_salience=1.0,
                    salience=1.0,
                    source_ks=source_ks,
                    payload=snapshot,
                    created_at=utcnow(),
                    last_reinforced=utcnow(),
                )
                session.add(entry)
                return entry.id
        except Exception as exc:  # noqa: BLE001
            logger.warning("[board] could not record assessment: %s", exc)
            return None

    # -- reading -----------------------------------------------------------

    def latest_assessment(self) -> Optional[Dict[str, Any]]:
        from .models import BoardEntry

        try:
            factory = self._sessions()
            if factory is None:
                return None
            with factory() as session:
                row = (
                    session.query(BoardEntry)
                    .filter(BoardEntry.level == "assessment")
                    .order_by(BoardEntry.created_at.desc())
                    .first()
                )
                return dict(row.payload) if row and row.payload else None
        except Exception as exc:  # noqa: BLE001
            logger.debug("[board] could not read assessment: %s", exc)
            return None

    def top_entries(
        self, *, limit: int = 20, domain: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Most salient events, for the digest a controller will read."""
        from .models import BoardEntry

        try:
            factory = self._sessions()
            if factory is None:
                return []
            with factory() as session:
                query = session.query(BoardEntry).filter(
                    BoardEntry.level == "event")
                if domain:
                    query = query.filter(BoardEntry.domain == domain)
                rows = query.order_by(BoardEntry.salience.desc()).limit(limit).all()
                return [_entry_to_dict(r) for r in rows]
        except Exception as exc:  # noqa: BLE001
            logger.debug("[board] could not read entries: %s", exc)
            return []

    def counts(self) -> Dict[str, int]:
        """Cheap totals, so growth can be watched rather than assumed."""
        from .models import BoardEntry, BoardFocus, KSActivation

        try:
            factory = self._sessions()
            if factory is None:
                return {}
            with factory() as session:
                return {
                    "events": session.query(BoardEntry).filter(
                        BoardEntry.level == "event").count(),
                    "assessments": session.query(BoardEntry).filter(
                        BoardEntry.level == "assessment").count(),
                    "foci": session.query(BoardFocus).count(),
                    "activations": session.query(KSActivation).count(),
                }
        except Exception as exc:  # noqa: BLE001
            logger.debug("[board] could not count: %s", exc)
            return {}


def _base_salience_for(
    severity: Optional[str], confidence: Optional[float]
) -> float:
    """
    Where an entry starts on the board.

    Severity dominates and confidence only modulates, because an uncertain
    report of something critical still deserves attention -- discounting it
    heavily by confidence is how a system misses the thing it half-saw.
    """
    base = {
        "critical": 0.95,
        "high": 0.75,
        "medium": 0.5,
        "low": 0.3,
    }.get((severity or "").lower(), 0.4)

    if confidence is None:
        return base
    # +/-15% at most.
    return max(0.05, min(1.0, base * (0.85 + 0.3 * float(confidence))))


def _entry_to_dict(row) -> Dict[str, Any]:
    return {
        "id": row.id,
        "event_id": row.event_id,
        "domain": row.domain,
        "summary": row.summary,
        "severity": row.severity,
        "impact_type": row.impact_type,
        "confidence": row.confidence,
        "salience": row.salience,
        "corroborations": row.corroborations,
        "entity_keys": row.entity_keys or [],
        "story_id": row.story_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
