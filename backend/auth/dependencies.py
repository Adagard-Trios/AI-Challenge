"""
auth/dependencies.py
FastAPI dependencies for route protection.

AUTH_ENFORCED gates the whole thing. With it off (the default), require_user
resolves a user when a valid token is present and returns None otherwise, so
every pre-existing route keeps working while the frontend migrates. Flipping it
on is a one-env-var cutover, instantly revertible.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import ConnectorDevice, User, utcnow
from .tokens import TokenError, TokenExpired, decode_access_token, hash_secret

logger = logging.getLogger("Roger.auth.deps")

UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def _bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


def optional_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Resolve a user if a valid token is present; never raise."""
    token = _bearer(authorization)
    if not token:
        return None
    try:
        claims = decode_access_token(token)
    except (TokenError, TokenExpired):
        return None

    user = db.get(User, claims.get("sub"))
    if user is None or not user.is_active:
        return None
    # A token issued before a forced logout carries a stale version.
    if claims.get("ver") != user.token_version:
        return None
    return user


def require_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """
    Require a user when AUTH_ENFORCED=1.

    With enforcement off this behaves exactly like optional_user, which is what
    lets the 39 existing routes carry the dependency before the frontend can
    send tokens.
    """
    token = _bearer(authorization)
    enforced = settings().enforced

    if not token:
        if enforced:
            raise UNAUTHENTICATED
        return None

    try:
        claims = decode_access_token(token)
    except TokenExpired:
        if enforced:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Access token expired",
                headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
            )
        return None
    except TokenError:
        if enforced:
            raise UNAUTHENTICATED
        return None

    user = db.get(User, claims.get("sub"))
    if user is None or not user.is_active or claims.get("ver") != user.token_version:
        if enforced:
            raise UNAUTHENTICATED
        return None
    return user


def require_admin(user: Optional[User] = Depends(require_user)) -> Optional[User]:
    if not settings().enforced:
        return user
    if user is None:
        raise UNAUTHENTICATED
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required"
        )
    return user


def require_device(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> ConnectorDevice:
    """
    Authenticate a connector by its device token.

    Always enforced, regardless of AUTH_ENFORCED: /api/ingest writes to the feed,
    so an unauthenticated version of it would be an open write endpoint.
    """
    token = _bearer(authorization)
    if not token:
        raise UNAUTHENTICATED

    device = db.query(ConnectorDevice).filter(
        ConnectorDevice.token_hash == hash_secret(token),
        ConnectorDevice.revoked_at.is_(None),
    ).first()

    if device is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown or revoked device token"
        )

    device.last_seen_at = utcnow()
    db.commit()
    return device
