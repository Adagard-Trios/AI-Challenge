"""
src/utils/rate_limiter.py
Domain-specific pacing for concurrent scraping.

Enforces, per domain:
  - a minimum gap between requests (jittered, so it is not a metronome)
  - a requests-per-minute ceiling over a sliding 60s window
  - a cap on concurrent in-flight requests

and optionally, per connected account:
  - a hard concurrency of 1, because two simultaneous browser contexts
    signed into the same account is the clearest automation signal there is.

Usage:
    from src.utils.rate_limiter import get_rate_limiter

    limiter = get_rate_limiter()
    with limiter.acquire("twitter", account_key="user123:twitter"):
        ...

Design notes — the previous implementation had three defects this one fixes:

1. It called ``time.sleep()`` while holding a single process-wide lock, so a
   LinkedIn ``min_delay`` of 5s blocked a Reddit request that had nothing to do
   with LinkedIn. Locks are now per-domain, and *all* sleeping happens outside
   them: reserve-or-report-wait under the lock, sleep unlocked, retry.
2. The RPM branch slept and then recorded the request without re-checking, so N
   threads that all observed the limit breached all proceeded after their sleeps.
   Reservation is now atomic with the check, and the caller loops.
3. It used ``time.time()``, which jumps with NTP/DST. Now ``time.monotonic()``.

Also switched the sliding window to a ``deque`` so eviction is O(1) amortised
rather than rebuilding the whole list on every call.
"""

import logging
import random
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from typing import Deque, Dict, Optional

logger = logging.getLogger("Roger.rate_limiter")

# Longest single uninterrupted sleep. Waking early to re-check keeps us from
# overshooting when another thread's window rolls over while we sleep.
_MAX_SLEEP_SLICE = 5.0

# Multiplicative jitter on min_delay. Never below 1.0 -- jitter may make us
# politer than configured, never ruder.
_JITTER_LO, _JITTER_HI = 1.0, 1.6


class RateLimiter:
    """Thread-safe, per-domain request pacing."""

    # rpm = requests per rolling 60s; max_concurrent = simultaneous in-flight;
    # min_delay = floor on the gap between consecutive requests, in seconds.
    DEFAULT_LIMITS = {
        "twitter": {"rpm": 15, "max_concurrent": 2, "min_delay": 2.0},
        "facebook": {"rpm": 10, "max_concurrent": 2, "min_delay": 3.0},
        "linkedin": {"rpm": 10, "max_concurrent": 1, "min_delay": 5.0},
        "instagram": {"rpm": 10, "max_concurrent": 2, "min_delay": 3.0},
        "reddit": {"rpm": 30, "max_concurrent": 3, "min_delay": 1.0},
        "news": {"rpm": 60, "max_concurrent": 5, "min_delay": 0.5},
        "government": {"rpm": 30, "max_concurrent": 3, "min_delay": 1.0},
        "default": {"rpm": 30, "max_concurrent": 3, "min_delay": 1.0},
    }

    def __init__(self, custom_limits: Optional[Dict] = None):
        self._limits = {**self.DEFAULT_LIMITS}
        if custom_limits:
            self._limits.update(custom_limits)

        # Guards creation of the per-domain structures below -- and nothing else.
        # Never held across a sleep.
        self._meta = threading.Lock()

        self._domain_locks: Dict[str, threading.Lock] = {}
        self._semaphores: Dict[str, threading.Semaphore] = {}
        self._account_locks: Dict[str, threading.Lock] = {}

        self._last_request: Dict[str, float] = defaultdict(float)
        self._request_counts: Dict[str, Deque[float]] = defaultdict(deque)

        logger.info(
            f"[RateLimiter] Initialized with {len(self._limits)} domain configurations"
        )

    # -- internals ---------------------------------------------------------

    def _get_domain_config(self, domain: str) -> Dict:
        return self._limits.get(domain.lower(), self._limits["default"])

    def _domain_lock(self, domain: str) -> threading.Lock:
        with self._meta:
            return self._domain_locks.setdefault(domain, threading.Lock())

    def _get_semaphore(self, domain: str) -> threading.Semaphore:
        with self._meta:
            sem = self._semaphores.get(domain)
            if sem is None:
                sem = threading.Semaphore(self._get_domain_config(domain)["max_concurrent"])
                self._semaphores[domain] = sem
            return sem

    def _account_lock(self, account_key: str) -> threading.Lock:
        with self._meta:
            return self._account_locks.setdefault(account_key, threading.Lock())

    def _try_reserve(self, domain: str, jitter: bool = True) -> float:
        """
        Atomically reserve a request slot, or report how long to wait.

        Returns 0.0 when the slot is taken (caller proceeds immediately), or a
        positive number of seconds the caller should sleep before retrying.
        Never sleeps itself, and never holds a lock across a sleep.
        """
        cfg = self._get_domain_config(domain)

        with self._domain_lock(domain):
            now = time.monotonic()

            window = self._request_counts[domain]
            cutoff = now - 60.0
            while window and window[0] < cutoff:
                window.popleft()

            min_delay = cfg["min_delay"]
            if jitter:
                min_delay *= random.uniform(_JITTER_LO, _JITTER_HI)

            wait = 0.0

            last = self._last_request.get(domain, 0.0)
            if last and (now - last) < min_delay:
                wait = min_delay - (now - last)

            if len(window) >= cfg["rpm"]:
                # Wait for the oldest request to age out of the window.
                wait = max(wait, window[0] + 60.0 - now + 0.05)

            if wait <= 0.0:
                self._last_request[domain] = now
                window.append(now)
                return 0.0

            return wait

    def _wait_for_rate_limit(self, domain: str) -> None:
        domain = domain.lower()
        while True:
            wait = self._try_reserve(domain)
            if wait <= 0.0:
                return
            logger.debug(f"[RateLimiter] {domain}: waiting {wait:.2f}s")
            time.sleep(min(wait, _MAX_SLEEP_SLICE))

    # -- public API --------------------------------------------------------

    @contextmanager
    def acquire(self, domain: str, account_key: Optional[str] = None):
        """
        Reserve a paced request slot for ``domain``.

        ``account_key`` (e.g. ``"<user_id>:twitter"``) additionally serialises
        all requests for one connected account to strictly one at a time.

        Lock order is always account-then-domain. Consistent ordering is what
        keeps this deadlock-free; do not reverse it.
        """
        domain = domain.lower()

        acct = self._account_lock(account_key) if account_key else None
        if acct is not None:
            acct.acquire()

        try:
            semaphore = self._get_semaphore(domain)
            semaphore.acquire()
            try:
                self._wait_for_rate_limit(domain)
                yield
            finally:
                semaphore.release()
        finally:
            if acct is not None:
                acct.release()

    def get_stats(self) -> Dict:
        """Snapshot of recent activity per domain."""
        stats = {}
        now = time.monotonic()
        for domain in list(self._request_counts.keys()):
            with self._domain_lock(domain):
                window = self._request_counts[domain]
                recent = sum(1 for ts in window if now - ts < 60)
                last = self._last_request.get(domain, 0.0)
                stats[domain] = {
                    "requests_last_minute": recent,
                    "last_request_ago": (now - last) if last else None,
                }
        return stats


# Global singleton
_rate_limiter: Optional[RateLimiter] = None
_rate_limiter_lock = threading.Lock()


def get_rate_limiter() -> RateLimiter:
    """Get the global rate limiter singleton."""
    global _rate_limiter
    with _rate_limiter_lock:
        if _rate_limiter is None:
            _rate_limiter = RateLimiter()
        return _rate_limiter


def reset_rate_limiter() -> None:
    """Reset the global rate limiter (tests)."""
    global _rate_limiter
    with _rate_limiter_lock:
        _rate_limiter = None
