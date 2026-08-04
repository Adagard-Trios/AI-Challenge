"""
Tests for src/scrapers/credentials.py

Fixtures mirror the shape of real Playwright storage_state captures. Cookie
*values* are dummies -- never put real session material in a test file.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.scrapers.credentials import (  # noqa: E402
    CredentialError,
    FileCredentialStore,
    NullCredentialStore,
    SocialCredential,
    derive_expiry,
    filter_first_party,
    get_credential_store,
    missing_required,
    set_credential_store,
    validate,
)

# Epochs used below (UTC)
MAR_2026 = 1772409600.0   # ~2026-03-02
DEC_2026 = 1797120000.0   # ~2026-12-11
JAN_2027 = 1800000000.0   # ~2027-01-15


def cookie(name, value="dummy", domain=".x.com", expires=JAN_2027):
    return {
        "name": name, "value": value, "domain": domain, "path": "/",
        "expires": expires, "httpOnly": True, "secure": True, "sameSite": "None",
    }


@pytest.fixture(autouse=True)
def _reset_store():
    set_credential_store(None)
    yield
    set_credential_store(None)


# --- first-party filtering -------------------------------------------------

def test_third_party_cookies_are_dropped():
    """Trackers ride along in a real capture; we have no reason to store them."""
    state = {
        "cookies": [
            cookie("auth_token"),
            cookie("ct0"),
            cookie("IDE", domain=".doubleclick.net"),
            cookie("demdex", domain=".demdex.net"),
        ],
        "origins": [
            {"origin": "https://x.com", "localStorage": []},
            {"origin": "https://doubleclick.net", "localStorage": []},
        ],
    }
    out = filter_first_party(state, "twitter")
    names = {c["name"] for c in out["cookies"]}
    assert names == {"auth_token", "ct0"}
    assert len(out["origins"]) == 1


def test_linkedin_keeps_both_first_party_domain_forms():
    state = {"cookies": [
        cookie("li_at", domain=".linkedin.com"),
        cookie("JSESSIONID", domain=".www.linkedin.com"),
        cookie("_px3", domain=".protechts.net"),
    ], "origins": []}
    out = filter_first_party(state, "linkedin")
    assert {c["name"] for c in out["cookies"]} == {"li_at", "JSESSIONID"}


# --- required cookies ------------------------------------------------------

def test_ct0_is_required_for_twitter():
    """
    X validates ct0 against the x-csrf-token header on every authenticated XHR.
    Dropping it fails silently and looks like an unexplained session expiry --
    so a capture without it must be rejected at the door.
    """
    state = {"cookies": [cookie("auth_token")], "origins": []}
    assert missing_required(state, "twitter") == ["ct0"]
    with pytest.raises(CredentialError, match="ct0"):
        validate(state, "twitter")


def test_complete_twitter_state_validates():
    state = {"cookies": [cookie("auth_token"), cookie("ct0")], "origins": []}
    validate(state, "twitter")   # must not raise


@pytest.mark.parametrize("platform,names", [
    ("facebook", ["c_user", "xs"]),
    ("instagram", ["sessionid"]),
    ("linkedin", ["li_at", "JSESSIONID"]),
])
def test_each_platform_required_set(platform, names):
    state = {"cookies": [cookie(n, domain="") for n in names], "origins": []}
    assert missing_required(state, platform) == []


# --- expiry derivation -----------------------------------------------------

def test_expiry_is_the_earliest_required_cookie():
    """
    LinkedIn's real ceiling is JSESSIONID (~3 months), not li_at (~12). Reporting
    li_at's expiry would promise the user four times the session life they have.
    """
    state = {"cookies": [
        cookie("li_at", domain=".linkedin.com", expires=DEC_2026),
        cookie("JSESSIONID", domain=".linkedin.com", expires=MAR_2026),
        cookie("lidc", domain=".linkedin.com", expires=JAN_2027),
    ], "origins": []}
    got = derive_expiry(state, "linkedin")
    assert got == datetime.fromtimestamp(MAR_2026, tz=timezone.utc)


def test_non_required_cookies_do_not_shorten_expiry():
    """A short-lived tracker must not make us report the session as dying."""
    state = {"cookies": [
        cookie("auth_token", expires=JAN_2027),
        cookie("ct0", expires=JAN_2027),
        cookie("guest_id", expires=MAR_2026),   # not required
    ], "origins": []}
    assert derive_expiry(state, "twitter") == datetime.fromtimestamp(JAN_2027, tz=timezone.utc)


def test_session_cookies_report_no_expiry():
    """expires <= 0 means a session cookie -- there is no date to report."""
    state = {"cookies": [cookie("sessionid", domain=".instagram.com", expires=-1)],
             "origins": []}
    assert derive_expiry(state, "instagram") is None


def test_is_expired_flag():
    past = SocialCredential("twitter", {"cookies": []},
                            expires_at=datetime(2020, 1, 1, tzinfo=timezone.utc))
    future = SocialCredential("twitter", {"cookies": []},
                              expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc))
    none = SocialCredential("twitter", {"cookies": []})
    assert past.is_expired and not future.is_expired and not none.is_expired


# --- validation ------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    "not a dict",
    {"no_cookies_key": []},
    {"cookies": "not a list"},
])
def test_malformed_state_rejected(bad):
    with pytest.raises(CredentialError):
        validate(bad, "twitter")


# --- secrets never leak ----------------------------------------------------

def test_repr_never_exposes_cookie_values():
    """
    A SocialCredential ends up in tracebacks and log lines. Its repr must never
    carry session material.
    """
    cred = SocialCredential(
        "twitter",
        {"cookies": [cookie("auth_token", value="SUPERSECRETVALUE")]},
        handle="@someone",
    )
    text = repr(cred)
    assert "SUPERSECRETVALUE" not in text
    assert "redacted" in text
    assert "@someone" in text          # non-sensitive fields still useful


# --- stores ----------------------------------------------------------------

def test_null_store_is_the_default():
    """
    The server must never hand out social credentials: collection happens in
    the user's connector.
    """
    store = get_credential_store()
    assert isinstance(store, NullCredentialStore)
    assert store.get("twitter") is None
    assert store.available() == []
    with pytest.raises(CredentialError):
        store.put("twitter", {"cookies": []})


def test_file_store_roundtrip(tmp_path):
    store = FileCredentialStore(tmp_path)
    assert store.get("twitter") is None

    store.put("twitter", {"cookies": [cookie("auth_token"), cookie("ct0")], "origins": []})
    cred = store.get("twitter")

    assert cred is not None
    assert cred.platform == "twitter"
    assert {c["name"] for c in cred.storage_state["cookies"]} == {"auth_token", "ct0"}
    assert store.available() == ["twitter"]


def test_file_store_treats_incomplete_session_as_absent(tmp_path):
    """A file missing ct0 is unusable; better to report 'not connected'."""
    path = tmp_path / "twitter_storage_state.json"
    path.write_text(json.dumps({"cookies": [cookie("auth_token")], "origins": []}))
    assert FileCredentialStore(tmp_path).get("twitter") is None


def test_file_store_survives_corrupt_json(tmp_path):
    (tmp_path / "twitter_storage_state.json").write_text("{not json")
    assert FileCredentialStore(tmp_path).get("twitter") is None


def test_file_store_filters_on_read(tmp_path):
    """Third-party cookies in an existing file are dropped on load, not just write."""
    path = tmp_path / "linkedin_storage_state.json"
    path.write_text(json.dumps({"cookies": [
        cookie("li_at", domain=".linkedin.com"),
        cookie("JSESSIONID", domain=".linkedin.com"),
        cookie("IDE", domain=".doubleclick.net"),
    ], "origins": []}))
    cred = FileCredentialStore(tmp_path).get("linkedin")
    assert {c["name"] for c in cred.storage_state["cookies"]} == {"li_at", "JSESSIONID"}
