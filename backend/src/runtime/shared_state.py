"""
src/runtime/shared_state.py
The live dashboard state, shared between the worker that produces it and the
API replicas that serve it.

WHAT THIS REPLACES
------------------
main.py held `current_state: Dict[str, Any]` at module level: the ranked feed,
the risk snapshot, the run count and the status. One process wrote it and the
same process served it, so it worked.

With more than one replica it stops working in a way that is easy to miss.
Only the WORKER runs the agent loop and the storage poller, so only the worker
ever writes. Every API replica would serve its own untouched copy -- an empty
feed and a "initializing" status, forever, while the worker quietly collected
into a dict nobody could read. Not a crash; just a dashboard that is
permanently empty on two pods out of three.

SHAPE
-----
One JSON document in Redis under a single key. That is unusual enough to
justify:

  - It is written by exactly ONE process, so there is no write contention and
    no need for per-field atomicity. The worker is a singleton by design.
  - It is read whole. /api/status, /api/dashboard, /api/feed and the WebSocket
    handshake all want a coherent view; assembling it from separate keys would
    let a reader see a new feed beside a stale snapshot.
  - It is small and bounded: the feed is capped at 100 events by the poller.

READS ARE CACHED, DELIBERATELY
------------------------------
Every API request would otherwise be a Redis round trip, and several routes
read it more than once. A one-second cache makes the cost per replica constant
regardless of traffic, and one second of staleness is meaningless for a
dashboard whose data refreshes every sixty.
"""

from __future__ import annotations

import copy
import json
import logging
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("Roger.runtime.state")

STATE_KEY = "roger:state"

# How long a replica may serve its cached copy. Chosen against the agent loop's
# 60s cadence and the poller's 2s: at one second the dashboard is never more
# than a tick behind, and Redis sees one read per second per replica rather
# than one per request.
CACHE_TTL_SECONDS = 1.0

# Redis holds no state before the worker's first write, and an API replica that
# starts first must still answer. These are the same defaults main.py used.
_DEFAULTS: Dict[str, Any] = {
    "final_ranked_feed": [],
    "risk_dashboard_snapshot": {},
    "run_count": 0,
    "status": "initializing",
    "last_update": None,
    "first_run_complete": False,
}

_local: Dict[str, Any] = copy.deepcopy(_DEFAULTS)
_cache: Optional[Dict[str, Any]] = None
_cache_at: float = 0.0
_lock = threading.Lock()


def _shared():
    try:
        from src.runtime.redis_client import configured, get_client

        return get_client() if configured() else None
    except Exception:  # noqa: BLE001
        return None


def install_defaults(state: Dict[str, Any]) -> None:
    """
    Seed the process-local view. Does NOT write to Redis: a starting API
    replica must not overwrite a running worker's state with its own blank
    initial values, which is exactly the race that would blank the dashboard on
    every deploy.
    """
    global _local
    with _lock:
        _local = copy.deepcopy(state)


def snapshot() -> Dict[str, Any]:
    """
    The current state, whole. Never returns None and never raises.

    Callers mutate what they get back (main.py does), so this hands out a copy;
    sharing the cached object would let a request's edits leak into what the
    next request sees.
    """
    global _cache, _cache_at

    client = _shared()
    if client is None:
        with _lock:
            return copy.deepcopy(_local)

    now = time.monotonic()
    with _lock:
        if _cache is not None and (now - _cache_at) < CACHE_TTL_SECONDS:
            return copy.deepcopy(_cache)

    try:
        raw = client.get(STATE_KEY)
        state = json.loads(raw) if raw else copy.deepcopy(_DEFAULTS)
    except Exception as exc:  # noqa: BLE001
        # Serving a slightly stale dashboard beats serving an error. The feed
        # is not a correctness surface the way the pacing gate is, so this
        # fails OPEN on purpose.
        logger.warning("[state] could not read shared state (%s); serving the "
                       "last known copy", exc)
        with _lock:
            return copy.deepcopy(_cache if _cache is not None else _local)

    with _lock:
        _cache = state
        _cache_at = now
        return copy.deepcopy(state)


def update(fields: Dict[str, Any]) -> None:
    """
    Merge fields into the shared state. Called only by the worker.

    Read-modify-write, which is safe here only because there is exactly one
    writer. If a second writer ever appears this must become a Lua script or a
    WATCH/MULTI, and the assumption is stated here so that is a deliberate
    change rather than a surprise.
    """
    global _cache, _cache_at

    client = _shared()
    if client is None:
        with _lock:
            _local.update(fields)
        return

    try:
        raw = client.get(STATE_KEY)
        state = json.loads(raw) if raw else copy.deepcopy(_DEFAULTS)
        state.update(fields)
        # No expiry. This is the current view of the world, not a cache entry:
        # a TTL would blank the dashboard during any quiet period.
        client.set(STATE_KEY, json.dumps(state, default=str))
        with _lock:
            _cache = state
            _cache_at = time.monotonic()
            _local.update(fields)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[state] could not write shared state (%s); this "
                       "replica's view is now local only", exc)
        with _lock:
            _local.update(fields)


def get(key: str, default: Any = None) -> Any:
    """Single field, for the many call sites that want exactly one."""
    return snapshot().get(key, default)


def reset() -> None:
    """Tests."""
    global _local, _cache, _cache_at
    with _lock:
        _local = copy.deepcopy(_DEFAULTS)
        _cache = None
        _cache_at = 0.0
