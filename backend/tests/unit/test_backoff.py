"""
Tests for connector/backoff.py

The property that matters: backoff SURVIVES A RESTART. An in-memory counter is
reset by exactly the thing that follows repeated failures -- someone restarting
the connector -- which turns "back off for six hours" into "retry immediately,
again". That is the behaviour most likely to escalate a soft block.
"""

import json
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent.parent
PROJECT_ROOT = Path(__file__).parent.parent.parent
for p in (str(REPO_ROOT), str(REPO_ROOT / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

from src.social.backoff import (  # noqa: E402
    BASE_DELAY_SECONDS, CHALLENGE_COOLDOWN_SECONDS, MAX_DELAY_SECONDS,
    BackoffStore,
)


@pytest.fixture()
def store(tmp_path):
    return BackoffStore(tmp_path)


# --- the headline property -------------------------------------------------

def test_backoff_survives_a_restart(tmp_path):
    """THE reason this is persisted rather than in-memory."""
    first = BackoffStore(tmp_path)
    first.record_failure("linkedin", "timeout")
    assert not first.ready("linkedin")

    reborn = BackoffStore(tmp_path)          # simulates a connector restart
    assert not reborn.ready("linkedin"), "restart cleared the backoff"
    assert reborn.wait_seconds("linkedin") > 0


def test_challenge_survives_a_restart(tmp_path):
    BackoffStore(tmp_path).record_challenge("twitter", "checkpoint")
    assert BackoffStore(tmp_path).is_challenged("twitter")


# --- growth ----------------------------------------------------------------

def test_delay_grows_exponentially(store):
    delays = [store.record_failure("x") for _ in range(4)]
    for earlier, later in zip(delays, delays[1:]):
        assert later > earlier
    # 15m base, +/-20% jitter
    assert BASE_DELAY_SECONDS * 0.8 <= delays[0] <= BASE_DELAY_SECONDS * 1.2


def test_delay_is_capped(store):
    for _ in range(20):
        delay = store.record_failure("x")
    assert delay <= MAX_DELAY_SECONDS * 1.2


def test_jitter_prevents_synchronised_retries(tmp_path):
    """
    Without jitter every account that failed together would retry together --
    a burst is exactly the shape that looks automated.
    """
    seen = set()
    for i in range(12):
        s = BackoffStore(tmp_path / f"d{i}")
        seen.add(round(s.record_failure("x"), 3))
    assert len(seen) > 1, "no jitter applied"


# --- recovery --------------------------------------------------------------

def test_success_clears_backoff(store):
    store.record_failure("linkedin")
    assert not store.ready("linkedin")
    store.record_success("linkedin")
    assert store.ready("linkedin")
    assert store.wait_seconds("linkedin") == 0


def test_challenge_is_not_cleared_by_time_alone(store, monkeypatch):
    """
    A challenge needs a human. Letting the cooldown lapse and resuming
    automatically is how a temporary block becomes permanent.
    """
    store.record_challenge("instagram", "checkpoint")
    assert store.is_challenged("instagram")

    # Even with the cooldown fully elapsed, the flag stands.
    monkeypatch.setattr(time, "time", lambda: time.monotonic() + CHALLENGE_COOLDOWN_SECONDS * 2)
    assert store.is_challenged("instagram")


def test_resume_clears_a_challenge(store):
    store.record_challenge("instagram", "checkpoint")
    store.resume("instagram")
    assert not store.is_challenged("instagram")
    assert store.ready("instagram")


# --- isolation & robustness ------------------------------------------------

def test_platforms_are_independent(store):
    store.record_failure("linkedin")
    assert not store.ready("linkedin")
    assert store.ready("twitter")


def test_unknown_platform_is_ready(store):
    assert store.ready("never-seen")
    assert store.describe("never-seen") == "ready"


def test_corrupt_state_does_not_stop_collection(tmp_path):
    """Failing open is right here: we pace, we do not skip."""
    (tmp_path / "backoff.json").write_text("{not json")
    assert BackoffStore(tmp_path).ready("linkedin")


def test_state_file_holds_no_credentials(store, tmp_path):
    store.record_failure("linkedin", "some error")
    store.record_challenge("twitter", "checkpoint")
    raw = (tmp_path / "backoff.json").read_text()
    data = json.loads(raw)
    for entry in data.values():
        assert set(entry) <= {"failures", "next_attempt_at", "last_error", "challenged"}
    for banned in ("cookie", "li_at", "auth_token", "sessionid", "storage_state"):
        assert banned not in raw


def test_describe_is_human_readable(store):
    assert store.describe("x") == "ready"
    store.record_failure("x")
    assert "backing off" in store.describe("x")
    store.record_challenge("x")
    assert "resume manually" in store.describe("x")


# --- wiring ----------------------------------------------------------------

def test_collection_consults_backoff_before_scraping():
    """
    A store nothing checks is decoration.

    REGRESSION: this broke when collection moved out of the connector into
    src/social. The service scraped without consulting the store at all, so a
    challenged account would be retried on the very next cycle -- the behaviour
    most likely to turn a recoverable challenge into a lasting restriction.
    """
    src = (PROJECT_ROOT / "src" / "social" / "service.py").read_text(encoding="utf-8")
    assert "self.backoff.is_challenged(platform)" in src
    assert "self.backoff.ready(platform)" in src
    assert "self.backoff.record_challenge(" in src
    assert "self.backoff.record_success(" in src
    assert "self.backoff.record_failure(" in src
