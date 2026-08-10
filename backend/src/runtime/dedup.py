"""
src/runtime/dedup.py
"Have we already broadcast this event?"

WHAT WAS WRONG
--------------
main.py kept `seen_event_ids: Set[str] = set()`, added to on every poll and
never pruned. Two problems, one of which bites today:

  - It grows for the lifetime of the process. A long-running instance
    accumulates every event id it has ever seen. Small per entry, unbounded in
    aggregate, and invisible until it is not.

  - It is per-process. Every replica keeps its own, so each one independently
    decides an event is new and broadcasts it to ITS OWN WebSocket clients.
    Whether a user sees a duplicate depends on which replica they happened to
    connect to, which is the kind of bug that cannot be reproduced on request.

A restart also empties it, so the poller re-broadcasts everything it finds --
which is why a reconnecting dashboard sometimes replays old events.

Redis solves all three with one command: SET NX EX. Atomic, shared, and
self-expiring, so nothing has to remember to prune.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Optional

logger = logging.getLogger("Roger.runtime.dedup")

# An event older than this is not going to arrive "newly" again. Matches the
# SQLITE_RETENTION_HOURS window the dedup cache already uses, so the two agree
# about how long the past is.
SEEN_TTL_SECONDS = 24 * 3600

# Bound for the in-process fallback. The set it replaces had no bound at all.
LOCAL_MAX = 50_000

_local: "OrderedDict[str, None]" = OrderedDict()


_WARNED_NO_REDIS = False


def _shared():
    global _WARNED_NO_REDIS
    try:
        from src.runtime.redis_client import configured, get_client

        return get_client() if configured() else None
    except Exception:  # noqa: BLE001
        # Falling back to per-process is correct; doing it silently is
        # not. Without Redis there is no cross-replica deduplication, so
        # the same event can be emitted once per replica -- and the only
        # symptom is behaviour that reads as a different bug entirely.
        # Warned once, because this sits on a hot path.
        if not _WARNED_NO_REDIS:
            _WARNED_NO_REDIS = True
            logger.warning(
                "[dedup] Redis unavailable; using per-process fallback. "
                "With more than one replica, the same event can be emitted once per replica.",
                exc_info=True,
            )
        return None


def mark_if_new(event_id: Optional[str]) -> bool:
    """
    True the FIRST time an id is seen, False afterwards.

    Deliberately one call rather than a `seen()` / `add()` pair: the two-step
    form is a race across replicas, where both check, both find it absent, and
    both broadcast. SET NX is atomic.

    An empty id is treated as new, because it cannot be deduplicated and
    silently dropping it would lose the event entirely.
    """
    if not event_id:
        return True

    client = _shared()
    if client is not None:
        try:
            # None when the key already existed, True when we created it.
            return bool(client.set(f"roger:seen:{event_id}", "1",
                                   nx=True, ex=SEEN_TTL_SECONDS))
        except Exception as exc:  # noqa: BLE001
            # Fall through to the local set. Duplicates are a cosmetic failure;
            # dropping events is not, so this never fails closed.
            logger.warning("[dedup] shared set unavailable (%s); using the "
                           "in-process set", exc)

    if event_id in _local:
        return False
    _local[event_id] = None
    while len(_local) > LOCAL_MAX:
        _local.popitem(last=False)     # oldest out first
    return True


def clear() -> None:
    """Tests."""
    _local.clear()


def local_size() -> int:
    return len(_local)
