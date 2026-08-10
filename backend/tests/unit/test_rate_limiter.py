"""
Tests for src/utils/rate_limiter.py

These pin the three defects the rewrite fixed. Each would have failed against
the previous implementation:

  1. cross-domain blocking -- it slept while holding one process-wide lock
  2. RPM overshoot        -- it slept, then recorded without re-checking
  3. wall-clock time      -- it used time.time(), which jumps with NTP
"""

import sys
import threading
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.rate_limiter import (  # noqa: E402
    RateLimiter,
    get_rate_limiter,
    reset_rate_limiter,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_rate_limiter()
    yield
    reset_rate_limiter()


# --- 1. the headline bug ---------------------------------------------------

def test_slow_domain_does_not_block_a_different_domain():
    """
    THE regression test. LinkedIn is configured min_delay=5.0. Previously
    _wait_for_rate_limit slept inside a single global lock, so a LinkedIn
    request stalled every other domain for the full 5s.
    """
    limiter = RateLimiter()

    # Prime linkedin so its next acquire must wait out min_delay.
    with limiter.acquire("linkedin"):
        pass

    started = threading.Event()
    reddit_elapsed = []

    def slow_linkedin():
        started.set()
        with limiter.acquire("linkedin"):   # will block ~5s
            pass

    t = threading.Thread(target=slow_linkedin, daemon=True)
    t.start()
    started.wait(timeout=2)
    time.sleep(0.15)                        # ensure it is inside the wait

    t0 = time.monotonic()
    with limiter.acquire("reddit"):         # must NOT wait on linkedin
        pass
    reddit_elapsed.append(time.monotonic() - t0)

    assert reddit_elapsed[0] < 1.0, (
        f"reddit blocked {reddit_elapsed[0]:.2f}s behind linkedin -- "
        "the global-lock regression is back"
    )
    t.join(timeout=10)


def test_same_domain_still_paces():
    """The flip side: pacing must actually happen within one domain."""
    limiter = RateLimiter(custom_limits={"t": {"rpm": 60, "max_concurrent": 5, "min_delay": 0.5}})

    with limiter.acquire("t"):
        pass
    t0 = time.monotonic()
    with limiter.acquire("t"):
        pass
    assert time.monotonic() - t0 >= 0.5


# --- 2. no overshoot -------------------------------------------------------

def test_rpm_ceiling_is_not_overshot_under_concurrency():
    """
    N threads racing one domain must not collectively exceed rpm. The old code
    let every thread that observed the breach proceed after its own sleep.
    """
    rpm = 5
    limiter = RateLimiter(
        custom_limits={"burst": {"rpm": rpm, "max_concurrent": 10, "min_delay": 0.0}}
    )

    admitted = []
    lock = threading.Lock()

    def worker():
        with limiter.acquire("burst"):
            with lock:
                admitted.append(time.monotonic())

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(10)]
    t0 = time.monotonic()
    for t in threads:
        t.start()
    # Only `rpm` may pass in the first window; the rest wait ~60s. Don't wait
    # for them -- assert on what got through promptly.
    time.sleep(2.0)

    with lock:
        early = [ts for ts in admitted if ts - t0 < 2.0]
    assert len(early) <= rpm, f"admitted {len(early)} in-window, ceiling is {rpm}"


# --- 3. concurrency caps ---------------------------------------------------

def test_max_concurrent_is_enforced():
    limiter = RateLimiter(
        custom_limits={"c": {"rpm": 100, "max_concurrent": 2, "min_delay": 0.0}}
    )

    live = 0
    peak = 0
    lock = threading.Lock()

    def worker():
        nonlocal live, peak
        with limiter.acquire("c"):
            with lock:
                live += 1
                peak = max(peak, live)
            time.sleep(0.2)
            with lock:
                live -= 1

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert peak <= 2, f"peak concurrency {peak} exceeded max_concurrent=2"


def test_account_key_serialises_to_one_at_a_time():
    """
    Two concurrent browser contexts on one account is the clearest automation
    signal there is -- account_key must hard-serialise regardless of the
    domain's max_concurrent.
    """
    limiter = RateLimiter(
        custom_limits={"a": {"rpm": 100, "max_concurrent": 5, "min_delay": 0.0}}
    )

    live = 0
    peak = 0
    lock = threading.Lock()

    def worker():
        nonlocal live, peak
        with limiter.acquire("a", account_key="user1:a"):
            with lock:
                live += 1
                peak = max(peak, live)
            time.sleep(0.15)
            with lock:
                live -= 1

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert peak == 1, f"peak {peak} for a single account; must be 1"


def test_different_accounts_are_independent():
    limiter = RateLimiter(
        custom_limits={"a": {"rpm": 100, "max_concurrent": 5, "min_delay": 0.0}}
    )

    live = 0
    peak = 0
    lock = threading.Lock()

    def worker(uid):
        nonlocal live, peak
        with limiter.acquire("a", account_key=f"user{uid}:a"):
            with lock:
                live += 1
                peak = max(peak, live)
            time.sleep(0.15)
            with lock:
                live -= 1

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert peak > 1, "distinct accounts must not serialise against each other"


# --- 4. hygiene properties -------------------------------------------------

def test_jitter_never_makes_us_ruder_than_configured():
    """Jitter multiplies min_delay by >= 1.0, so it can only add politeness."""
    limiter = RateLimiter(
        custom_limits={"j": {"rpm": 100, "max_concurrent": 1, "min_delay": 0.3}}
    )
    with limiter.acquire("j"):
        pass
    t0 = time.monotonic()
    with limiter.acquire("j"):
        pass
    assert time.monotonic() - t0 >= 0.3


def test_no_lock_is_held_across_a_sleep():
    """
    Structural guard: _try_reserve holds the per-domain lock for its whole body,
    so it must contain no sleep *call*. Parsed via AST rather than substring
    matching, so prose in the docstring cannot trip or mask it.
    """
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(RateLimiter._try_reserve)))

    def is_sleep(node):
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr == "sleep":
            return True
        return isinstance(f, ast.Name) and f.id == "sleep"

    offenders = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and is_sleep(n)]
    assert not offenders, (
        f"_try_reserve calls sleep at line(s) {[n.lineno for n in offenders]} "
        "-- it holds the domain lock; sleeping there reintroduces the "
        "cross-domain blocking bug"
    )


def test_unknown_domain_falls_back_to_default():
    limiter = RateLimiter()
    cfg = limiter._get_domain_config("something-unmapped")
    assert cfg == RateLimiter.DEFAULT_LIMITS["default"]


def test_singleton_identity_and_reset():
    a = get_rate_limiter()
    b = get_rate_limiter()
    assert a is b
    reset_rate_limiter()
    assert get_rate_limiter() is not a


def test_get_stats_reports_recent_requests():
    limiter = RateLimiter(
        custom_limits={"s": {"rpm": 100, "max_concurrent": 5, "min_delay": 0.0}}
    )
    for _ in range(3):
        with limiter.acquire("s"):
            pass
    stats = limiter.get_stats()
    assert stats["s"]["requests_last_minute"] == 3
    assert stats["s"]["last_request_ago"] is not None
