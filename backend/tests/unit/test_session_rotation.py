"""
Session rotation: refreshed cookies must be written back.

Nothing in the original codebase read the session after a scrape, so every
rotated ct0 / lidc / sessionid was discarded and the stored session drifted
stale until it stopped working. The plan called this the single
highest-leverage change for session longevity, so it gets its own tests.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent.parent
BACKEND = REPO_ROOT / "backend"
for p in (str(REPO_ROOT), str(BACKEND)):
    if p not in sys.path:
        sys.path.insert(0, p)

from src.scrapers.base import ScrapeResult  # noqa: E402
from src.scrapers.credentials import SocialCredential  # noqa: E402


def test_rotated_state_is_excluded_from_the_serialised_payload():
    """
    rotated_state is credential material. as_dict() feeds tool output, which
    reaches logs and an LLM's context -- it must never carry cookies.
    """
    result = ScrapeResult(
        posts=[{"source": "Twitter", "poster": "@a", "text": "hi"}],
        platform="twitter",
        rotated_state={"cookies": [{"name": "ct0", "value": "ROTATED-SECRET"}]},
    )
    payload = result.as_dict()

    assert "rotated_state" not in payload
    assert "ROTATED-SECRET" not in repr(payload)


def test_rotated_state_is_not_in_the_repr():
    """Tracebacks print dataclass reprs; a cookie must not ride along."""
    result = ScrapeResult(
        platform="twitter",
        rotated_state={"cookies": [{"name": "ct0", "value": "ROTATED-SECRET"}]},
    )
    assert "ROTATED-SECRET" not in repr(result)


def test_run_scrape_captures_the_post_run_session(monkeypatch):
    """run_scrape must read the session back, not just the posts."""
    from src.scrapers import base

    rotated = {"cookies": [{"name": "ct0", "value": "NEW"}], "origins": []}

    class FakeCtx:
        def persist_state(self):
            return rotated

    class FakeSession:
        def __enter__(self):
            return FakeCtx()

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(base, "browser_session", lambda *a, **k: FakeSession())

    cred = SocialCredential("twitter", {"cookies": []})
    result = base.run_scrape(cred, lambda ctx: ScrapeResult(posts=[]))

    assert result.rotated_state == rotated


def test_connector_persists_rotated_cookies(tmp_path, monkeypatch):
    """The end-to-end property: a run leaves the stored session updated."""
    from connector.storage import KeyStore, SessionStore

    monkeypatch.setattr(KeyStore, "_keyring", lambda self: None)
    store = SessionStore(tmp_path)

    original = {"cookies": [
        {"name": "auth_token", "value": "OLD", "domain": ".x.com", "expires": 1800000000.0},
        {"name": "ct0", "value": "OLD-CSRF", "domain": ".x.com", "expires": 1800000000.0},
    ], "origins": []}
    store.save("twitter", original)

    rotated = {"cookies": [
        {"name": "auth_token", "value": "OLD", "domain": ".x.com", "expires": 1800000000.0},
        {"name": "ct0", "value": "NEW-CSRF", "domain": ".x.com", "expires": 1900000000.0},
    ], "origins": []}
    store.save("twitter", rotated)

    reloaded = store.load("twitter")["storage_state"]
    ct0 = next(c for c in reloaded["cookies"] if c["name"] == "ct0")
    assert ct0["value"] == "NEW-CSRF", "rotated cookie was not written back"


def test_challenge_does_not_overwrite_a_good_session():
    """
    Whatever a platform hands back mid-challenge is not a session worth
    keeping, and overwriting a working one with it would be destructive.
    """
    source = (REPO_ROOT / "connector" / "collect.py").read_text(encoding="utf-8")
    assert 'result.status != "challenged"' in source, (
        "connector must skip persistence on a challenge"
    )


def test_persist_state_is_actually_called():
    """
    Regression guard. persist_state() existed but was never invoked -- defining
    it without calling it fixes nothing, and that is easy to reintroduce.
    """
    base_src = (BACKEND / "src" / "scrapers" / "base.py").read_text(encoding="utf-8")
    conn_src = (REPO_ROOT / "connector" / "collect.py").read_text(encoding="utf-8")

    assert "ctx.persist_state()" in base_src, "run_scrape must capture the session"
    assert "result.rotated_state" in conn_src, "connector must write it back"
