"""
src/utils/rate_limiter.py
Domain-Specific Rate Limiter for Concurrent Web Scraping

Provides thread-safe rate limiting to prevent anti-bot detection when
multiple agents scrape the same domains concurrently.

Usage:
    from src.utils.rate_limiter import RateLimiter, get_rate_limiter

    # Global singleton
    limiter = get_rate_limiter()

    # Acquire before making request
    with limiter.acquire("twitter"):
        # Make request to Twitter
        pass
"""

import threading
import time
import logging
from typing import Dict, Optional
from contextlib import contextmanager
from collections import defaultdict

logger = logging.getLogger("Roger.rate_limiter")


class RateLimiter:
    """
    Thread-safe rate limiter with domain-specific limits.

    Implements a token bucket algorithm with configurable:
    - Requests per minute per domain
    - Maximum concurrent requests per domain
    - Minimum delay between requests to same domain
    """

    # Default configuration per domain (requests_per_minute, max_concurrent, min_delay_seconds)
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
        """
        Initialize rate limiter with optional custom limits.

        Args:
            custom_limits: Optional dict to override default limits per domain
        """
        self._limits = {**self.DEFAULT_LIMITS}
        if custom_limits:
            self._limits.update(custom_limits)

        # Per-domain semaphores for concurrent request limiting
        self._semaphores: Dict[str, threading.Semaphore] = {}

        # Per-domain last request timestamps
        self._last_request: Dict[str, float] = defaultdict(float)

        # Per-domain request counts (for RPM tracking)
        self._request_counts: Dict[str, list] = defaultdict(list)

        # Lock for thread-safe access to shared state
        self._lock = threading.Lock()

        logger.info(
            f"[RateLimiter] Initialized with {len(self._limits)} domain configurations"
        )

    def _get_domain_config(self, domain: str) -> Dict:
        """Get configuration for a domain, falling back to default."""
        return self._limits.get(domain.lower(), self._limits["default"])

    def _get_semaphore(self, domain: str) -> threading.Semaphore:
        """Get or create semaphore for a domain."""
        domain = domain.lower()
        with self._lock:
            if domain not in self._semaphores:
                config = self._get_domain_config(domain)
                self._semaphores[domain] = threading.Semaphore(config["max_concurrent"])
            return self._semaphores[domain]

    def _wait_for_rate_limit(self, domain: str) -> None:
        """Wait if necessary to respect rate limits."""
        domain = domain.lower()
        config = self._get_domain_config(domain)

        with self._lock:
            now = time.time()

            # Enforce minimum delay between requests
            last = self._last_request[domain]
            if last > 0:
                elapsed = now - last
                min_delay = config["min_delay"]
                if elapsed < min_delay:
                    wait_time = min_delay - elapsed
                    logger.debug(
                        f"[RateLimiter] {domain}: waiting {wait_time:.2f}s for min_delay"
                    )
                    time.sleep(wait_time)

            # Clean old request timestamps (older than 60 seconds)
            self._request_counts[domain] = [
                ts for ts in self._request_counts[domain] if now - ts < 60
            ]

            # Check RPM limit
            rpm_limit = config["rpm"]
            if len(self._request_counts[domain]) >= rpm_limit:
                oldest = self._request_counts[domain][0]
                wait_time = 60 - (now - oldest) + 0.1
                if wait_time > 0:
                    logger.warning(
                        f"[RateLimiter] {domain}: RPM limit ({rpm_limit}) reached, waiting {wait_time:.2f}s"
                    )
                    time.sleep(wait_time)

            # Record this request
            self._last_request[domain] = time.time()
            self._request_counts[domain].append(time.time())

    @contextmanager
    def acquire(self, domain: str):
        """
        Context manager to acquire rate limit slot for a domain.

        Usage:
            with limiter.acquire("twitter"):
                # Make request
                pass
        """
        domain = domain.lower()
        semaphore = self._get_semaphore(domain)

        logger.debug(f"[RateLimiter] {domain}: acquiring slot...")
        semaphore.acquire()

        try:
            self._wait_for_rate_limit(domain)
            logger.debug(f"[RateLimiter] {domain}: slot acquired")
            yield
        finally:
            semaphore.release()
            logger.debug(f"[RateLimiter] {domain}: slot released")

    def get_stats(self) -> Dict:
        """Get current rate limiter statistics."""
        with self._lock:
            now = time.time()
            stats = {}
            for domain in self._request_counts:
                recent = [ts for ts in self._request_counts[domain] if now - ts < 60]
                stats[domain] = {
                    "requests_last_minute": len(recent),
                    "last_request_ago": (
                        now - self._last_request[domain]
                        if self._last_request[domain]
                        else None
                    ),
                }
            return stats


# Global singleton instance
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
    """Reset the global rate limiter (useful for testing)."""
    global _rate_limiter

    with _rate_limiter_lock:
        _rate_limiter = None
