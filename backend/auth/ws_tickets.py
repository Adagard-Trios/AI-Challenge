"""
auth/ws_tickets.py
Single-use tickets for authenticating the WebSocket.

Browsers cannot set headers on ``new WebSocket()``, so the bearer token cannot
travel the normal way. Putting the JWT in the query string would work, but query
strings land in Render's access logs and in any proxy in between -- a 15-minute
credential written to disk in plaintext.

Instead: the client asks an authenticated REST endpoint for a ticket, then
connects with ``?ticket=...``. The ticket is single-use, expires in 30 seconds,
and grants nothing on its own.

In-process storage is sound *only* because there is exactly one worker:
scripts/start_backend.sh runs `uvicorn main:app` with no --workers flag.

That assumption has now been lifted rather than merely asserted. When REDIS_URL
is set, tickets live in Redis, because the two halves of this handshake do not
land on the same process:

    POST /api/auth/ws-ticket   ->  api-1     (an ordinary HTTP request)
    new WebSocket(...?ticket=) ->  api-3     (a separate connection)

With N replicas and in-process storage, roughly (N-1)/N of connections are
rejected with code 1008 -- which presents as "the dashboard is flaky" rather
than as an auth bug, and costs a day to find. assert_single_worker() below
predicted this and said "Move them to Redis"; this is that move.

Unset REDIS_URL keeps the in-process dict, which remains correct for one
process and is what the laptop runs.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional

logger = logging.getLogger("Roger.auth.ws")

TICKET_TTL_SECONDS = 30
_MAX_OUTSTANDING = 10_000       # bound the dict; tickets are tiny but not free


@dataclass(frozen=True)
class _Ticket:
    user_id: str
    expires_at: float


_tickets: Dict[str, _Ticket] = {}
_lock = threading.Lock()


def _purge_locked(now: float) -> None:
    expired = [k for k, t in _tickets.items() if t.expires_at <= now]
    for k in expired:
        _tickets.pop(k, None)


_WARNED_NO_REDIS = False


def _shared():
    """The Redis client when shared tickets are in play, else None."""
    global _WARNED_NO_REDIS
    try:
        from src.runtime.redis_client import configured, get_client

        return get_client() if configured() else None
    except Exception:  # noqa: BLE001
        # Falling back to per-process is correct; doing it silently is
        # not. Without Redis there is no shared WebSocket tickets, so
        # a ticket issued by one replica is rejected by another -- and the only
        # symptom is behaviour that reads as a different bug entirely.
        # Warned once, because this sits on a hot path.
        if not _WARNED_NO_REDIS:
            _WARNED_NO_REDIS = True
            logger.warning(
                "[ws_tickets] Redis unavailable; using per-process fallback. "
                "With more than one replica, a ticket issued by one replica is rejected by another.",
                exc_info=True,
            )
        return None


def _key(ticket: str) -> str:
    return f"roger:wst:{ticket}"


def issue(user_id: str) -> str:
    ticket = secrets.token_urlsafe(24)

    client = _shared()
    if client is not None:
        try:
            # Redis owns the TTL, so no clock is compared across processes --
            # the same reason the pacing gate stores an expiry rather than a
            # monotonic deadline.
            client.set(_key(ticket), user_id, ex=TICKET_TTL_SECONDS)
            return ticket
        except Exception as exc:  # noqa: BLE001
            # Falling back to the local dict is safe: the worst case is that
            # this ticket only works if the WebSocket lands on this same
            # replica, which is exactly today's behaviour. Nothing is granted
            # that should not be.
            logger.warning("[auth.ws] could not store ticket in Redis (%s); "
                           "falling back to this process", exc)

    now = time.monotonic()
    with _lock:
        _purge_locked(now)
        if len(_tickets) >= _MAX_OUTSTANDING:
            # Shed the oldest rather than growing without bound.
            oldest = min(_tickets, key=lambda k: _tickets[k].expires_at)
            _tickets.pop(oldest, None)
        _tickets[ticket] = _Ticket(user_id=user_id, expires_at=now + TICKET_TTL_SECONDS)
    return ticket


def redeem(ticket: Optional[str]) -> Optional[str]:
    """Consume a ticket, returning its user_id. Returns None if invalid."""
    if not ticket:
        return None

    client = _shared()
    if client is not None:
        try:
            # GETDEL is the single-use guarantee, and it must be ATOMIC: GET
            # then DELETE lets two connections racing the same ticket both read
            # it before either deletes, and both authenticate.
            user_id = client.getdel(_key(ticket))
            if user_id:
                return user_id
            # Fall through: a ticket issued before Redis was configured may
            # still be in the local dict.
        except Exception as exc:  # noqa: BLE001
            logger.warning("[auth.ws] could not redeem via Redis (%s); "
                           "checking local tickets", exc)

    now = time.monotonic()
    with _lock:
        _purge_locked(now)
        entry = _tickets.pop(ticket, None)     # pop == single use
    if entry is None or entry.expires_at <= now:
        return None
    return entry.user_id


def outstanding() -> int:
    with _lock:
        return len(_tickets)


def clear() -> None:
    with _lock:
        _tickets.clear()


def assert_single_worker() -> None:
    """
    Warn loudly if the process looks multi-worker.

    Tickets issued by worker A are invisible to worker B, so WebSocket auth
    would fail for a fraction of connections -- the kind of bug that presents as
    "the dashboard is flaky" and costs a day.
    """
    import os

    if _shared() is not None:
        return  # tickets are shared; workers and replicas are both fine

    workers = os.getenv("WEB_CONCURRENCY") or os.getenv("UVICORN_WORKERS")
    if workers and workers.strip() not in ("", "1"):
        logger.error(
            "[auth.ws] %s workers configured, but WebSocket tickets are stored "
            "in-process. Tickets issued by one worker will be rejected by "
            "another. Set REDIS_URL, or run a single worker.",
            workers,
        )
