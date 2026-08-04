"""
auth/tokens.py
Access tokens (JWT) and refresh tokens (opaque, rotating).

Why bearer tokens rather than cookies: both vercel.app and onrender.com are on
the Public Suffix List, so every frontend<->backend pairing here is cross-site.
Cookies would need SameSite=None, which mobile Safari has blocked by default
since 13.1 -- and mobile support is a requirement. Bearer tokens behave
identically on every browser.

The refresh token has to live in client storage, so it is treated as
compromisable: single-use, rotated on every refresh, and a replay revokes the
whole rotation family.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import RefreshToken, User, new_id, utcnow


class TokenError(Exception):
    pass


class TokenExpired(TokenError):
    pass


class TokenReplayed(TokenError):
    """A spent refresh token was presented again -- treat as theft."""


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "bearer"

    def as_dict(self) -> dict:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_type": self.token_type,
            "expires_in": self.expires_in,
        }


# --- access tokens ---------------------------------------------------------

def create_access_token(user: User) -> str:
    cfg = settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user.id,
        "email": user.email,
        "role": user.role,
        "ver": user.token_version,     # bump to invalidate all outstanding tokens
        "iss": cfg.issuer,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=cfg.access_ttl_seconds)).timestamp()),
        "jti": new_id(),
    }
    return jwt.encode(payload, cfg.secret, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    cfg = settings()
    try:
        return jwt.decode(
            token,
            cfg.secret,
            algorithms=["HS256"],          # pinned: never trust the header's alg
            issuer=cfg.issuer,
            options={"require": ["exp", "sub", "iss"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpired("access token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError(f"invalid access token: {exc}") from exc


# --- refresh tokens --------------------------------------------------------

def issue_refresh_token(db: Session, user: User, *, family_id: Optional[str] = None) -> str:
    cfg = settings()
    raw = secrets.token_urlsafe(32)
    db.add(RefreshToken(
        user_id=user.id,
        token_hash=_sha256(raw),
        family_id=family_id or new_id(),
        expires_at=utcnow() + timedelta(seconds=cfg.refresh_ttl_seconds),
    ))
    return raw


def issue_pair(db: Session, user: User) -> TokenPair:
    return TokenPair(
        access_token=create_access_token(user),
        refresh_token=issue_refresh_token(db, user),
        expires_in=settings().access_ttl_seconds,
    )


def rotate_refresh_token(db: Session, raw_token: str) -> TokenPair:
    """
    Exchange a refresh token for a new pair.

    Replay handling is the important part. If a token that has already been
    spent is presented again, the plausible explanations are (a) it was stolen
    and the thief is using it, or (b) it was stolen and the legitimate user is.
    Either way both parties now hold tokens from that family, so the whole
    family is revoked and everyone re-authenticates.
    """
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == _sha256(raw_token)))
    if row is None:
        raise TokenError("unknown refresh token")

    if row.used_at is not None:
        db.query(RefreshToken).filter(
            RefreshToken.family_id == row.family_id,
            RefreshToken.revoked_at.is_(None),
        ).update({"revoked_at": utcnow()}, synchronize_session=False)
        db.commit()
        raise TokenReplayed(
            "refresh token reuse detected; the token family has been revoked"
        )

    if not row.is_usable:
        raise TokenExpired("refresh token expired or revoked")

    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise TokenError("user is inactive")

    row.used_at = utcnow()
    new_raw = issue_refresh_token(db, user, family_id=row.family_id)
    db.commit()

    return TokenPair(
        access_token=create_access_token(user),
        refresh_token=new_raw,
        expires_in=settings().access_ttl_seconds,
    )


def revoke_family(db: Session, raw_token: str) -> None:
    """Logout: revoke this token's whole rotation family."""
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == _sha256(raw_token)))
    if row is None:
        return
    db.query(RefreshToken).filter(
        RefreshToken.family_id == row.family_id,
        RefreshToken.revoked_at.is_(None),
    ).update({"revoked_at": utcnow()}, synchronize_session=False)
    db.commit()


def revoke_all_for_user(db: Session, user: User) -> None:
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user.id,
        RefreshToken.revoked_at.is_(None),
    ).update({"revoked_at": utcnow()}, synchronize_session=False)
    user.token_version += 1          # kills outstanding access tokens too
    db.commit()


# --- opaque secrets (invites, device tokens, pair codes) -------------------

def new_secret(nbytes: int = 32) -> tuple[str, str]:
    """Return (raw, sha256). Only the hash is ever stored."""
    raw = secrets.token_urlsafe(nbytes)
    return raw, _sha256(raw)


def hash_secret(raw: str) -> str:
    return _sha256(raw)


def new_pair_code() -> tuple[str, str]:
    """
    Short, human-typeable pairing code.

    Digits only and grouped, because it is read off a phone and typed into a
    desktop terminal. Ambiguous characters (O/0, I/1) are avoided by using
    digits exclusively.
    """
    code = "-".join(
        "".join(secrets.choice("0123456789") for _ in range(3)) for _ in range(3)
    )
    return code, _sha256(code)
