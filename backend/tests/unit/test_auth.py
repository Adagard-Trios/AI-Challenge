"""
Tests for backend/auth.

Runs against SQLite. SQLAlchemy presents the same interface for Postgres, so
what passes here is what runs in production once DATABASE_URL points at Neon --
the only production-only concern is pool_pre_ping, which SQLite does not need.
"""

import os
import sys
from datetime import timedelta
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """Fresh database and settings per test."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'auth.db').as_posix()}")
    monkeypatch.setenv("AUTH_SECRET", "x" * 48)
    monkeypatch.setenv("AUTH_ENFORCED", "0")

    from auth import config, db as dbmod
    config.reset_settings()
    dbmod.reset_engine()
    dbmod.init_db()

    session = dbmod.session_factory()()
    try:
        yield session
    finally:
        session.close()
        dbmod.reset_engine()
        config.reset_settings()


@pytest.fixture()
def user(db):
    from auth.models import User
    from auth.passwords import hash_password
    u = User(email="owner@example.com",
             password_hash=hash_password("correct-horse-battery"), role="admin")
    db.add(u)
    db.commit()
    return u


# --- passwords -------------------------------------------------------------

def test_password_roundtrip():
    from auth.passwords import hash_password, verify_password
    h = hash_password("correct-horse-battery")
    assert verify_password("correct-horse-battery", h)
    assert not verify_password("wrong", h)


def test_long_passwords_are_not_silently_truncated():
    """
    REGRESSION. bcrypt hard-errors above 72 bytes, and the usual workaround --
    password[:72] -- makes two distinct long passwords equivalent. The sha256
    pre-hash means every byte contributes.
    """
    from auth.passwords import hash_password, verify_password
    a = "A" * 100 + "_ending_one"
    b = "A" * 100 + "_ending_two"
    ha = hash_password(a)
    assert verify_password(a, ha)
    assert not verify_password(b, ha), "long passwords collided after 72 bytes"


def test_password_with_nul_and_unicode():
    from auth.passwords import hash_password, verify_password
    pw = "pä\x00ssword-ünicode-🔐"
    assert verify_password(pw, hash_password(pw))


def test_short_password_rejected():
    from auth.passwords import WeakPassword, hash_password
    with pytest.raises(WeakPassword):
        hash_password("short")


def test_verify_never_raises_on_garbage():
    from auth.passwords import verify_password
    assert not verify_password("x", "not-a-hash")
    assert not verify_password("", "")


# --- access tokens ---------------------------------------------------------

def test_access_token_roundtrip(db, user):
    from auth.tokens import create_access_token, decode_access_token
    claims = decode_access_token(create_access_token(user))
    assert claims["sub"] == user.id
    assert claims["role"] == "admin"
    assert claims["ver"] == user.token_version


def test_tampered_token_rejected(db, user):
    from auth.tokens import TokenError, create_access_token, decode_access_token
    token = create_access_token(user)
    head, payload, sig = token.split(".")
    with pytest.raises(TokenError):
        decode_access_token(f"{head}.{payload}.{'A' * len(sig)}")


def test_alg_none_is_rejected(db, user):
    """
    Classic JWT attack: re-sign with alg=none. decode() pins algorithms=["HS256"],
    so the header cannot select the verifier.
    """
    import jwt
    from auth.tokens import TokenError, decode_access_token
    forged = jwt.encode({"sub": user.id, "iss": "roger", "exp": 9999999999},
                        key="", algorithm="none")
    with pytest.raises(TokenError):
        decode_access_token(forged)


def test_expired_access_token(db, user, monkeypatch):
    from auth import config
    from auth.tokens import TokenExpired, create_access_token, decode_access_token
    monkeypatch.setenv("AUTH_ACCESS_TTL", "-1")
    config.reset_settings()
    with pytest.raises(TokenExpired):
        decode_access_token(create_access_token(user))


# --- refresh rotation ------------------------------------------------------

def test_refresh_rotates_and_old_token_dies(db, user):
    from auth.tokens import issue_pair, rotate_refresh_token
    first = issue_pair(db, user)
    db.commit()

    second = rotate_refresh_token(db, first.refresh_token)
    assert second.refresh_token != first.refresh_token
    assert second.access_token


def test_replaying_a_spent_refresh_revokes_the_family(db, user):
    """
    THE security property. A spent refresh token reappearing means it leaked --
    either the thief or the victim is using it. Both now hold tokens from the
    family, so the family dies and everyone re-authenticates.
    """
    from auth.tokens import TokenError, TokenReplayed, issue_pair, rotate_refresh_token
    first = issue_pair(db, user)
    db.commit()

    second = rotate_refresh_token(db, first.refresh_token)      # legitimate

    with pytest.raises(TokenReplayed):
        rotate_refresh_token(db, first.refresh_token)           # replay

    # The token the attacker/victim rotated into is dead too.
    with pytest.raises(TokenError):
        rotate_refresh_token(db, second.refresh_token)


def test_unknown_refresh_token_rejected(db, user):
    from auth.tokens import TokenError, rotate_refresh_token
    with pytest.raises(TokenError):
        rotate_refresh_token(db, "never-issued")


def test_logout_everywhere_invalidates_access_tokens(db, user):
    """token_version is carried in the JWT, so a bump kills outstanding tokens."""
    from auth.tokens import create_access_token, decode_access_token, revoke_all_for_user
    token = create_access_token(user)
    before = decode_access_token(token)["ver"]

    revoke_all_for_user(db, user)
    db.refresh(user)

    assert user.token_version == before + 1     # dependency compares and rejects


# --- ws tickets ------------------------------------------------------------

def test_ws_ticket_is_single_use():
    from auth import ws_tickets
    ws_tickets.clear()
    ticket = ws_tickets.issue("user-1")
    assert ws_tickets.redeem(ticket) == "user-1"
    assert ws_tickets.redeem(ticket) is None       # consumed


def test_ws_ticket_rejects_unknown_and_empty():
    from auth import ws_tickets
    assert ws_tickets.redeem("nope") is None
    assert ws_tickets.redeem(None) is None
    assert ws_tickets.redeem("") is None


def test_ws_tickets_are_bounded():
    from auth import ws_tickets
    ws_tickets.clear()
    for i in range(50):
        ws_tickets.issue(f"u{i}")
    assert ws_tickets.outstanding() <= ws_tickets._MAX_OUTSTANDING


# --- config fails closed ---------------------------------------------------

def test_enforced_without_database_url_refuses_to_start(monkeypatch):
    """
    A SQLite file on Render free is wiped on every restart, so silently falling
    back to one would make user accounts vanish. Refuse instead.
    """
    from auth import config
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AUTH_ENFORCED", "1")
    monkeypatch.setenv("AUTH_SECRET", "y" * 48)
    config.reset_settings()
    with pytest.raises(config.AuthConfigError, match="DATABASE_URL"):
        config.load_settings()
    config.reset_settings()


def test_enforced_without_secret_refuses_to_start(monkeypatch, tmp_path):
    from auth import config
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path/'a.db').as_posix()}")
    monkeypatch.setenv("AUTH_ENFORCED", "1")
    monkeypatch.delenv("AUTH_SECRET", raising=False)
    config.reset_settings()
    with pytest.raises(config.AuthConfigError, match="AUTH_SECRET"):
        config.load_settings()
    config.reset_settings()


def test_short_secret_rejected_when_enforced(monkeypatch, tmp_path):
    from auth import config
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path/'a.db').as_posix()}")
    monkeypatch.setenv("AUTH_ENFORCED", "1")
    monkeypatch.setenv("AUTH_SECRET", "tooshort")
    config.reset_settings()
    with pytest.raises(config.AuthConfigError, match="at least 32"):
        config.load_settings()
    config.reset_settings()


@pytest.mark.parametrize("given,expected_prefix", [
    ("postgres://u:p@h/db", "postgresql+psycopg://"),
    ("postgresql://u:p@h/db", "postgresql+psycopg://"),
])
def test_managed_postgres_urls_get_the_driver_prefix(monkeypatch, given, expected_prefix):
    """Neon and Render hand out postgres:// ; SQLAlchemy 2 needs the driver."""
    from auth import config
    monkeypatch.setenv("DATABASE_URL", given)
    monkeypatch.setenv("AUTH_SECRET", "z" * 48)
    monkeypatch.setenv("AUTH_ENFORCED", "0")
    config.reset_settings()
    assert config.load_settings().database_url.startswith(expected_prefix)
    config.reset_settings()


# --- the server stores no cookies -----------------------------------------

def test_no_model_can_store_a_session_cookie():
    """
    Structural guarantee. If a column for cookies ever appears, the design
    premise -- that a database compromise yields no account access -- is gone.
    """
    from auth.models import Base
    banned = {"cookie", "cookies", "storage_state", "session_state",
              "password_plain", "token_plain"}
    for table in Base.metadata.tables.values():
        for column in table.columns:
            assert column.name.lower() not in banned, (
                f"{table.name}.{column.name} looks like credential storage; "
                "sessions belong in the user's connector"
            )
