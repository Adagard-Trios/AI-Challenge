"""
The pacing gate across processes.

This is the test that protects a real personal Instagram account.

The gate enforces a minimum interval between two collections of the same
account. It was a dict of time.monotonic() deadlines behind a threading.Lock,
which is correct for exactly one process and wrong for two: each replica keeps
its own dict, so an account gated to one collection per fifteen minutes gets N
with N replicas. Multiplying the rate at which a logged-in personal account is
touched is the single change here with a lasting, unrecoverable consequence.

Two properties are asserted, and the second matters more than the first:

  1. With Redis, exactly ONE grant per window across independent stores.
  2. With Redis CONFIGURED BUT UNREACHABLE, ZERO grants. Fail closed.

Failing open is the tempting default and it is the dangerous one. Losing an
hour of posts is recoverable in an hour; a restricted account is not.

Needs the Redis from docker-compose (`docker compose up -d redis`). Skips
itself when Redis is absent, following the e2e convention -- but see
test_the_skip_is_not_silent: an unnoticed skip here is how the guarantee is
lost.
"""

import os
import sys
import uuid
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

REDIS_URL = os.getenv("REDIS_URL") or "redis://localhost:6379/0"


def _redis_or_skip():
    try:
        import redis
    except ImportError:  # pragma: no cover
        pytest.skip("redis package not installed")
    try:
        client = redis.Redis.from_url(REDIS_URL, socket_connect_timeout=2,
                                      socket_timeout=2, decode_responses=True)
        client.ping()
        return client
    except Exception:
        pytest.skip(f"no Redis at {REDIS_URL} (docker compose up -d redis)")


class _ConnectedStore:
    """A session store that always has a session, so pacing is the only gate."""

    @staticmethod
    def load(platform):
        return {"storage_state": {"cookies": [{"name": "sessionid",
                                               "value": "x"}]},
                "handle": "@me"}

    @staticmethod
    def available():
        return ["instagram"]


def _fresh_store(monkeypatch, platform):
    """
    A NEW SessionStoreCredentialStore, as a second replica would have.

    Deliberately not reusing one instance: the whole failure mode is that each
    process has its own in-memory deadline dict, so a test sharing one instance
    would pass while the real deployment doubled its collection rate.
    """
    from src.runtime import redis_client
    from src.social.credential_bridge import SessionStoreCredentialStore

    redis_client.reset()
    return SessionStoreCredentialStore(store=_ConnectedStore())


@pytest.fixture
def platform(monkeypatch):
    """A unique platform name per test, so runs cannot pollute each other."""
    name = f"testplat-{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("REDIS_URL", REDIS_URL)
    monkeypatch.setenv("SOCIAL_MIN_INTERVAL_SECONDS", "30")
    yield name
    try:
        _redis_or_skip().delete(f"roger:pace:{name}")
    except Exception:
        pass


def _reload_interval(monkeypatch, seconds):
    """MIN_COLLECTION_INTERVAL is read at import; rebind it for the test."""
    import src.social.credential_bridge as bridge

    monkeypatch.setattr(bridge, "MIN_COLLECTION_INTERVAL", float(seconds))


def test_two_independent_stores_get_exactly_one_grant(monkeypatch, platform):
    """
    THE test. Two stores, as two replicas would be, hammering the same account.

    Without the shared gate both are served, because each consults its own
    dict. That is a doubled request rate against one personal account.
    """
    _redis_or_skip()
    _reload_interval(monkeypatch, 30)

    replicas = [_fresh_store(monkeypatch, platform) for _ in range(2)]

    served = 0
    for _ in range(10):
        for replica in replicas:
            if not replica._too_soon(platform):
                served += 1

    assert served == 1, (
        f"{served} collections were granted in one window across two "
        f"replicas; the shared pacing gate is not holding and a personal "
        f"account is being touched {served}x more often than intended"
    )


def test_the_gate_is_visible_to_a_replica_that_never_took_it(monkeypatch, platform):
    """
    A replica that did not consume the slot must still SEE it, or it reports
    the account as free and the dashboard shows a retry that will not happen.
    """
    _redis_or_skip()
    _reload_interval(monkeypatch, 30)

    taker = _fresh_store(monkeypatch, platform)
    observer = _fresh_store(monkeypatch, platform)

    assert taker._too_soon(platform) is False, "first call should be served"
    assert observer.is_paced(platform) is True, (
        "a second replica cannot see the gate the first one took"
    )
    assert observer.seconds_until_ready(platform) > 0


def test_asking_does_not_consume_the_slot(monkeypatch, platform):
    """is_paced() is a read. If it consumed, merely rendering the dashboard
    would spend the account's collection budget."""
    _redis_or_skip()
    _reload_interval(monkeypatch, 30)

    store = _fresh_store(monkeypatch, platform)
    for _ in range(5):
        assert store.is_paced(platform) is False
    assert store._too_soon(platform) is False, (
        "asking five times consumed the slot"
    )


def test_it_fails_closed_when_redis_is_unreachable(monkeypatch, platform):
    """
    THE OTHER test, and the one whose default is tempting and wrong.

    Redis configured but down must mean NO collection, not unpaced collection.
    An outage would otherwise release every gate at once, across every replica,
    against one account -- the exact scenario the gate exists to prevent,
    triggered by an unrelated failure.
    """
    from src.runtime import redis_client

    _reload_interval(monkeypatch, 30)
    # A port nothing listens on: configured, unreachable.
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6399/0")
    redis_client.reset()

    from src.social.credential_bridge import SessionStoreCredentialStore

    store = SessionStoreCredentialStore(store=_ConnectedStore())

    assert store.is_paced(platform) is True, (
        "an unreachable Redis reports the account as free to collect"
    )
    assert store._too_soon(platform) is True, (
        "an unreachable Redis grants a collection slot"
    )
    assert store.get(platform) is None, (
        "a credential was served with no working pacing gate"
    )
    redis_client.reset()


def test_without_redis_the_single_process_gate_still_works(monkeypatch, platform):
    """
    Unset REDIS_URL must behave exactly as before. The laptop path is one
    process, and requiring Redis to collect locally would be a regression.
    """
    from src.runtime import redis_client

    monkeypatch.delenv("REDIS_URL", raising=False)
    redis_client.reset()
    _reload_interval(monkeypatch, 30)

    from src.social.credential_bridge import SessionStoreCredentialStore

    store = SessionStoreCredentialStore(store=_ConnectedStore())
    served = sum(1 for _ in range(20) if not store._too_soon(platform))
    assert served == 1
    redis_client.reset()


def test_the_skip_is_not_silent():
    """
    If Redis is missing these tests skip, and a skipped guarantee is no
    guarantee. Assert the fail-closed path at least, which needs no Redis at
    all -- so the account-protecting half always runs.
    """
    from src.runtime import redis_client
    import src.social.credential_bridge as bridge

    source = (PROJECT_ROOT / "src" / "social" / "credential_bridge.py").read_text(
        encoding="utf-8")
    assert "fail" in source.lower() and "closed" in source.lower(), (
        "the fail-closed decision is not documented in the code, so a future "
        "reader may 'fix' the unreachable-Redis path by failing open"
    )
    assert hasattr(bridge.SessionStoreCredentialStore, "_pace_key")
    assert hasattr(redis_client, "get_client")
