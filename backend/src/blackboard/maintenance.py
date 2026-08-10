"""
src/blackboard/maintenance.py
Ageing the board, and deleting what has stopped describing the present.

THE GAPS THIS CLOSES
--------------------
Three things in this system grow without bound today, all verified:

  ChromaDB          has NO delete method at all -- only clear_collection().
                    The semantic dedup corpus therefore grows forever. It is
                    also the largest thing on disk, so this is the one that
                    eventually costs real money or a full volume.

  trending_detector cleanup_old_data(days=7) is DEFINED AND NEVER CALLED. The
                    only caller of that name anywhere is StorageManager's own
                    method, which prunes SQLite and not this.

  ks_activations    ~1,500 rows an hour at a 60s tick across ~25 sources. An
                    audit table that grows forever is the same bug it exists
                    to help find.

REGRESSION HAZARD, GUARDED
--------------------------
Eviction must never remove a dedup entry younger than SQLITE_RETENTION_HOURS.
If it did, an evicted event would look new on the next scrape and be re-emitted
-- resurrecting the "same events every cycle forever" bug that dedup_key exists
to prevent. So this deletes BOARD rows and their ChromaDB vectors; it does not
touch the SQLite dedup window, which has its own retention and its own cleanup.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict

logger = logging.getLogger("Roger.blackboard.maintenance")

# Audit rows are for diagnosing the last day or two, not for history.
ACTIVATION_RETENTION_HOURS = 48

# Bound the work per cycle. A first run against a large board should not stall
# the agent loop; what it does not finish, the next cycle picks up.
MAX_EVICTIONS_PER_PASS = 500


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def run(now: datetime = None) -> Dict[str, int]:
    """
    One maintenance pass. Returns what it did, so it can be logged and watched
    rather than trusted.
    """
    now = now or utcnow()
    stats = {"aged": 0, "evicted": 0, "foci_expired": 0, "activations_pruned": 0}

    try:
        from auth.db import session_scope
    except Exception as exc:  # noqa: BLE001
        logger.debug("[board] no database; skipping maintenance: %s", exc)
        return stats

    from .decay import decayed_salience, focus_urgency, should_evict
    from .models import BoardEntry, BoardFocus, KSActivation

    evicted_event_ids = []

    try:
        with session_scope() as session:
            # -- age events ------------------------------------------------
            #
            # Materialised rather than computed on read: eviction then becomes
            # an index scan on salience instead of an exponential evaluated per
            # row per query.
            for entry in session.query(BoardEntry).filter(
                    BoardEntry.level == "event").all():
                entry.salience = decayed_salience(
                    entry.base_salience,
                    entry.severity,
                    entry.last_reinforced,
                    now=now,
                    corroborations=entry.corroborations or 0,
                )
                stats["aged"] += 1

                if should_evict(entry.salience, entry.story_id,
                                created_at=entry.created_at, now=now):
                    if len(evicted_event_ids) < MAX_EVICTIONS_PER_PASS:
                        if entry.event_id:
                            evicted_event_ids.append(entry.event_id)
                        session.delete(entry)
                        stats["evicted"] += 1

            # -- supersede old assessments ---------------------------------
            #
            # Keep a day of them for a trend line; an index from last week is
            # not evidence, it is history.
            cutoff = now - timedelta(hours=24)
            stats["evicted"] += (
                session.query(BoardEntry)
                .filter(BoardEntry.level == "assessment",
                        BoardEntry.created_at < cutoff)
                .delete(synchronize_session=False)
            )

            # -- expire foci -----------------------------------------------
            for focus in session.query(BoardFocus).all():
                focus.urgency = focus_urgency(focus.urgency,
                                              focus.last_reinforced, now=now)
                expired = focus.expires_at is not None and _aware(
                    focus.expires_at) < now
                if focus.urgency < 0.05 or expired:
                    session.delete(focus)
                    stats["foci_expired"] += 1

            # -- prune the audit table -------------------------------------
            stats["activations_pruned"] = (
                session.query(KSActivation)
                .filter(KSActivation.decided_at
                        < now - timedelta(hours=ACTIVATION_RETENTION_HOURS))
                .delete(synchronize_session=False)
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[board] maintenance pass failed: %s", exc)
        return stats

    # Vectors last, and outside the transaction: ChromaDB is a separate store
    # with no shared transaction, so doing it inside would let a database
    # rollback leave vectors deleted for rows that still exist.
    if evicted_event_ids:
        _drop_vectors(evicted_event_ids)

    _prune_trending()

    if any(stats.values()):
        logger.info(
            "[board] maintenance: aged %d, evicted %d, foci expired %d, "
            "activations pruned %d",
            stats["aged"], stats["evicted"], stats["foci_expired"],
            stats["activations_pruned"],
        )
    return stats


def _aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes even for aware columns."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _drop_vectors(event_ids) -> None:
    """
    Remove evicted events from the semantic corpus.

    Without this, "the board keeps only the present" is false at the layer
    that actually consumes disk -- the rows would go and the vectors would
    stay forever.
    """
    try:
        from src.storage.storage_manager import StorageManager

        chroma = getattr(StorageManager(), "chromadb", None)
        deleter = getattr(chroma, "delete_events", None)
        if deleter is None:
            logger.debug("[board] chromadb has no delete_events; vectors kept")
            return
        deleter(event_ids)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[board] could not drop vectors: %s", exc)


def _prune_trending() -> None:
    """
    Call the trending cleanup that has always existed and never been called.

    trending_detector.cleanup_old_data(days=7) is defined; the only caller of
    that NAME anywhere is StorageManager's own method, which prunes SQLite
    instead. So the trending tables have been growing since they were added.
    """
    try:
        from src.utils.trending_detector import get_trending_detector

        detector = get_trending_detector()
        cleanup = getattr(detector, "cleanup_old_data", None)
        if callable(cleanup):
            cleanup(days=7)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[board] could not prune trending data: %s", exc)
