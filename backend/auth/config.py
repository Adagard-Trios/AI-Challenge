"""
auth/config.py
Auth settings. Fails closed.

main.py never calls load_dotenv() -- the .env file reaches os.getenv only as a
side effect of an import chain that is itself wrapped in try/except ImportError
(main.py -> combinedAgentGraph -> langsmith_config). If that import ever fails,
every os.getenv silently returns None and CORS_ALLOW_ORIGINS quietly becomes "*".

That is survivable for a feature flag. It is not survivable for a signing key,
so this module loads .env itself and refuses to start rather than defaulting.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    load_dotenv()  # also honour a repo-root .env
except ImportError:  # pragma: no cover
    pass


class AuthConfigError(RuntimeError):
    """Missing or unusable auth configuration. Never defaulted around."""


def _flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class AuthSettings:
    database_url: str
    secret: str
    enforced: bool
    access_ttl_seconds: int = 900              # 15 min
    refresh_ttl_seconds: int = 14 * 24 * 3600  # 14 days
    ws_ticket_ttl_seconds: int = 30
    bcrypt_rounds: int = 12
    issuer: str = "roger"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


def _default_sqlite_url() -> str:
    """
    Local-dev fallback only.

    Render's free tier has no persistent disk, so a SQLite file there is wiped
    on every deploy, restart and spin-down -- every user account would vanish.
    Production must set DATABASE_URL to a real Postgres (Neon's free tier is the
    cheapest option that does not expire; Render's own free Postgres is DELETED
    after 30 days).
    """
    data_dir = Path(__file__).resolve().parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(data_dir / 'auth.db').as_posix()}"


def load_settings(*, require_secret: bool = True) -> AuthSettings:
    enforced = _flag("AUTH_ENFORCED")

    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        if enforced:
            raise AuthConfigError(
                "AUTH_ENFORCED=1 but DATABASE_URL is unset. Refusing to start: a "
                "SQLite file on Render free is wiped on every restart, so user "
                "accounts would silently disappear. Set DATABASE_URL to Postgres."
            )
        database_url = _default_sqlite_url()

    # SQLAlchemy 2.x needs the postgresql+psycopg driver prefix; managed
    # providers hand out postgres:// or postgresql:// URLs.
    if database_url.startswith("postgres://"):
        database_url = "postgresql+psycopg://" + database_url[len("postgres://"):]
    elif database_url.startswith("postgresql://"):
        database_url = "postgresql+psycopg://" + database_url[len("postgresql://"):]

    secret = os.getenv("AUTH_SECRET", "").strip()
    if not secret:
        if require_secret and enforced:
            raise AuthConfigError(
                "AUTH_ENFORCED=1 but AUTH_SECRET is unset. Generate one with:\n"
                "  python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
        # Ephemeral key for local dev. Every restart invalidates all tokens,
        # which is the correct behaviour for a key nobody configured.
        secret = secrets.token_urlsafe(48)

    if enforced and len(secret) < 32:
        raise AuthConfigError(
            f"AUTH_SECRET is {len(secret)} chars; needs at least 32 for HS256."
        )

    return AuthSettings(
        database_url=database_url,
        secret=secret,
        enforced=enforced,
        access_ttl_seconds=int(os.getenv("AUTH_ACCESS_TTL", "900")),
        refresh_ttl_seconds=int(os.getenv("AUTH_REFRESH_TTL", str(14 * 24 * 3600))),
    )


_settings: AuthSettings | None = None


def settings() -> AuthSettings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def reset_settings() -> None:
    """Tests."""
    global _settings
    _settings = None
