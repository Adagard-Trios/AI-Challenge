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
It does not decide what a failure MEANS. A caller that needs Redis and cannot
reach it has to decide what that implies for ITS OWN correctness, and the
answers differ: a missing cache entry is harmless, while a missing pacing
deadline means "collect now" to every replica at once. Making that decision
here, once, for everyone, would get one of them wrong.

It does retry the CONNECTION, on a cooldown -- see get_client(). This paragraph
used to say it did not, and that was true until the first real cluster
deployment showed why it could not stay true: pods start in an order nobody
controls, and a replica that lost the race with Redis kept its "no" forever.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger("Roger.runtime.redis")

_client: Any = None
_resolved = False
_lock = threading.Lock()
_last_attempt = 0.0

# Short by design. Every call site has a fallback, and a caller blocking for
# 30 seconds on an unreachable Redis is worse than being told "no" immediately
# -- especially inside the agent cycle, which has a wall-clock budget.
CONNECT_TIMEOUT_SECONDS = 3.0

# How long to wait before retrying a FAILED connection. Long enough that a
# genuinely-down Redis costs one attempt every 10s per process rather than one
# per call; short enough that a pod which lost the race with redis-0 at startup
# recovers within a few dashboard refreshes instead of never.
RETRY_AFTER_SECONDS = 10.0


def redis_url() -> str:
    return (os.getenv("REDIS_URL") or "").strip()


def configured() -> bool:
    """Whether shared state is even meant to be in play."""
    return bool(redis_url())


def get_client():
    """
    The shared client, or None when Redis is not configured or not reachable.

    RESOLVED ONCE PER OUTCOME, NOT ONCE PER PROCESS.

    This used to resolve exactly once and cache the result forever, reasoning
    that a process which started without Redis should not silently acquire it
    mid-run. That is defensible for one long-lived process on a laptop. In a
    cluster it is wrong, and it failed on the first real deployment:

    The API pods started before redis-0 was ready, cached None, and then served
    PER-PROCESS state forever while reporting healthy. Verified in kind -- the
    worker wrote run_count=42, the key was present in Redis, a fresh process in
    the same pod read it back correctly, and the running uvicorn kept answering
    run_count=0. Nothing errored; the dashboard was simply permanently stale on
    every replica.

    Pod start order is not controllable, and Redis restarts. So a SUCCESSFUL
    client is still cached forever -- there is no reconnect-per-call on the hot
    path, which was the real point of the original design -- but a FAILURE is
    retried after a cooldown. Bounded, so a Redis that is genuinely down costs
    one connection attempt every RETRY_AFTER_SECONDS rather than one per call.
    """
    global _client, _resolved, _last_attempt

    if _resolved and _client is not None:
        return _client

    # A previous attempt failed. Retry, but not on every call.
    if _resolved and _client is None:
        if not redis_url():
            return None          # not configured; nothing to retry
        if (time.monotonic() - _last_attempt) < RETRY_AFTER_SECONDS:
            return None

    with _lock:
        if _resolved and _client is not None:
            return _client
        _resolved = True
        _last_attempt = time.monotonic()

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
    global _client, _resolved, _last_attempt
    _client = None
    _resolved = False
    _last_attempt = 0.0
