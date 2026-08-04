"""
Tests for the connector's local session storage.

The premise of the whole design is that credentials stay on the user's machine
and are unreadable at rest. These check that is actually true, rather than
merely intended.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent.parent
BACKEND = REPO_ROOT / "backend"
for p in (str(REPO_ROOT), str(BACKEND)):
    if p not in sys.path:
        sys.path.insert(0, p)

from connector.storage import DeviceConfig, KeyStore, SessionStore  # noqa: E402


def _state(name="li_at", extra=None):
    cookies = [
        {"name": name, "value": "SECRET-SESSION-VALUE", "domain": ".linkedin.com",
         "path": "/", "expires": 1800000000.0, "httpOnly": True,
         "secure": True, "sameSite": "None"},
        {"name": "JSESSIONID", "value": "ajax:123", "domain": ".linkedin.com",
         "path": "/", "expires": 1790000000.0, "httpOnly": True,
         "secure": True, "sameSite": "None"},
    ]
    if extra:
        cookies.extend(extra)
    return {"cookies": cookies, "origins": []}


@pytest.fixture()
def store(tmp_path, monkeypatch):
    # Force the key-file path so the test never touches the developer's real
    # OS keychain.
    monkeypatch.setattr(KeyStore, "_keyring", lambda self: None)
    return SessionStore(tmp_path)


# --- encryption at rest ----------------------------------------------------

def test_roundtrip(store):
    store.save("linkedin", _state(), handle="@me")
    loaded = store.load("linkedin")
    assert loaded["handle"] == "@me"
    names = {c["name"] for c in loaded["storage_state"]["cookies"]}
    assert names == {"li_at", "JSESSIONID"}


def test_cookie_values_are_not_readable_on_disk(store, tmp_path):
    """
    THE property. If the plaintext value appears in the file, everything else
    here is decoration.
    """
    store.save("linkedin", _state())
    blob = (tmp_path / "linkedin.session").read_bytes()

    assert b"SECRET-SESSION-VALUE" not in blob
    assert b"li_at" not in blob
    assert b"linkedin.com" not in blob
    with pytest.raises(UnicodeDecodeError):
        blob.decode("utf-8")          # ciphertext, not JSON


def test_renaming_a_session_file_fails_to_decrypt(store, tmp_path):
    """
    The platform name is bound in as AAD, so linkedin.session copied over
    twitter.session must fail rather than silently load the wrong credential.
    """
    store.save("linkedin", _state())
    (tmp_path / "twitter.session").write_bytes((tmp_path / "linkedin.session").read_bytes())
    assert store.load("twitter") is None


def test_tampered_ciphertext_is_rejected(store, tmp_path):
    """GCM is authenticated: a flipped bit must fail, not decrypt to garbage."""
    store.save("linkedin", _state())
    path = tmp_path / "linkedin.session"
    blob = bytearray(path.read_bytes())
    blob[-1] ^= 0xFF
    path.write_bytes(bytes(blob))
    assert store.load("linkedin") is None


def test_wrong_key_yields_nothing(store, tmp_path, monkeypatch):
    store.save("linkedin", _state())
    (tmp_path / "session.key").write_bytes(b"\x01" * 32)
    fresh = SessionStore(tmp_path)
    monkeypatch.setattr(KeyStore, "_keyring", lambda self: None)
    assert fresh.load("linkedin") is None


def test_each_save_uses_a_fresh_nonce(store, tmp_path):
    """Nonce reuse under one key breaks GCM outright."""
    store.save("linkedin", _state())
    first = (tmp_path / "linkedin.session").read_bytes()[:12]
    store.save("linkedin", _state())
    second = (tmp_path / "linkedin.session").read_bytes()[:12]
    assert first != second


def test_oversized_payload_rejected(store):
    huge = {"cookies": [{"name": "x", "value": "A" * 600_000, "domain": ".linkedin.com"}],
            "origins": []}
    with pytest.raises(ValueError, match="does not look like a session"):
        store.save("linkedin", huge)


# --- lifecycle -------------------------------------------------------------

def test_missing_session_is_none_not_an_error(store):
    assert store.load("facebook") is None


def test_delete_removes_the_file(store, tmp_path):
    store.save("linkedin", _state())
    assert store.delete("linkedin") is True
    assert not (tmp_path / "linkedin.session").exists()
    assert store.load("linkedin") is None
    assert store.delete("linkedin") is False


def test_available_lists_connected_platforms(store):
    assert store.available() == []
    store.save("linkedin", _state())
    store.save("twitter", {"cookies": [
        {"name": "auth_token", "value": "v", "domain": ".x.com", "expires": 1800000000.0},
        {"name": "ct0", "value": "v", "domain": ".x.com", "expires": 1800000000.0},
    ], "origins": []})
    assert store.available() == ["linkedin", "twitter"]


def test_save_is_atomic(store, tmp_path):
    """A crash mid-write must not leave a half-written session."""
    store.save("linkedin", _state())
    assert not list(tmp_path.glob("*.tmp"))


# --- device config ---------------------------------------------------------

def test_device_config_roundtrip(tmp_path):
    cfg = DeviceConfig(tmp_path)
    assert cfg.is_paired is False
    cfg.save(server_url="https://example.com", device_token="tok", user_id="u1")
    assert cfg.is_paired is True
    assert cfg.load()["device_token"] == "tok"
    cfg.clear()
    assert cfg.is_paired is False


def test_device_config_survives_corruption(tmp_path):
    (tmp_path / "device.json").write_text("{not json")
    assert DeviceConfig(tmp_path).load() == {}


# --- CLI wiring ------------------------------------------------------------

def test_cli_parser_exposes_the_documented_commands():
    from connector.__main__ import build_parser
    parser = build_parser()
    for argv in (
        ["pair", "1-2-3", "--server", "https://x"],
        ["connect", "linkedin"],
        ["disconnect", "twitter"],
        ["status"],
        ["collect", "query"],
        ["run", "query"],
    ):
        assert parser.parse_args(argv).command == argv[0]


def test_connect_rejects_an_unknown_platform():
    from connector.__main__ import build_parser
    with pytest.raises(SystemExit):
        build_parser().parse_args(["connect", "myspace"])
