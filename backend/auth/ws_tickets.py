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

In-process storage is sound here *only* because there is exactly one worker:
scripts/start_backend.sh runs `uvicorn main:app` with no --workers flag. Adding
workers later would silently break this -- assert_single_worker() exists to make
that failure loud rather than mysterious.
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


def issue(user_id: str) -> str:
    now = time.monotonic()
    ticket = secrets.token_urlsafe(24)
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
    workers = os.getenv("WEB_CONCURRENCY") or os.getenv("UVICORN_WORKERS")
    if workers and workers.strip() not in ("", "1"):
        logger.error(
            "[auth.ws] %s workers configured, but WebSocket tickets are stored "
            "in-process. Tickets issued by one worker will be rejected by "
            "another. Move them to Redis or run a single worker.",
            workers,
        )
