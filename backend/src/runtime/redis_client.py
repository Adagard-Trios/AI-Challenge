"""
src/runtime/redis_client.py
One Redis connection, and an honest answer about whether there is one.

WHY THIS EXISTS
---------------
Several things in this system are correct only because there is exactly one
process. The social pacing gate is a dict of deadlines behind a threading.Lock;
the daily request budget is a module-level dict whose own docstring says "if
collection ever moves somewhere multi-process, this needs to become a shared
counter". Collection already moved into the backend. Running two API replicas
would silently double the rate at which a personal social account is touched.

Redis is how those become shared. This module is deliberately thin: get a
client, or None. Everything that uses it must work when it returns None,
because the laptop path -- one process, no Redis -- has to keep working exactly
as it does today.

WHAT IT DOES NOT DO
-------------------
It does not retry, and it does not hide failures behind a cache. A caller that
needs Redis and cannot reach it has to decide what that means for ITS OWN
correctness, and the answers differ: a missing cache entry is harmless, while a
missing pacing deadline means "collect now" to every replica at once. Making
that decision here, once, for everyone, would get one of them wrong.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

logger = logging.getLogger("Roger.runtime.redis")

_client: Any = None
_resolved = False
_lock = threading.Lock()

# Short by design. Every call site has a fallback, and a caller blocking for
# 30 seconds on an unreachable Redis is worse than being told "no" immediately
# -- especially inside the agent cycle, which has a wall-clock budget.
CONNECT_TIMEOUT_SECONDS = 3.0


def redis_url() -> str:
    return (os.getenv("REDIS_URL") or "").strip()


def configured() -> bool:
    """Whether shared state is even meant to be in play."""
    return bool(redis_url())


def get_client():
    """
    The shared client, or None when Redis is not configured or not reachable.

    Resolved once. A process that started without Redis does not silently
    acquire it mid-run, and one that lost it does not reconnect on the hot
    path -- both would make behaviour depend on timing, which is precisely what
    makes the single-process assumptions above so hard to see.
    """
    global _client, _resolved

    if _resolved:
        return _client

    with _lock:
        if _resolved:
            return _client
        _resolved = True

        url = redis_url()
        if not url:
            logger.info(
                "[redis] REDIS_URL is unset; using in-process state. Correct "
                "for a single process, unsafe for more than one."
            )
            _client = None
            return None

        try:
            import redis as _redis

            client = _redis.Redis.from_url(
                url,
                socket_connect_timeout=CONNECT_TIMEOUT_SECONDS,
                socket_timeout=CONNECT_TIMEOUT_SECONDS,
                decode_responses=True,
            )
            client.ping()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[redis] REDIS_URL is set but Redis is unreachable (%s). "
                "Callers that require it will fail closed.", exc,
            )
            _client = None
            return None

        logger.info("[redis] connected; shared state is active")
        _client = client
        return client


def reset() -> None:
    """Tests only. Forces the next get_client() to resolve again."""
    global _client, _resolved
    _client = None
    _resolved = False
