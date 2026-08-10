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

from .config import settings
from .db import session_scope
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


def _lookup_user(user_id, expected_version):
    """
    Resolve the token's user on a SHORT-LIVED session.

    This used to take `db: Session = Depends(get_db)`, which pins a pooled
    connection for the ENTIRE request -- FastAPI resolves dependencies before
    the endpoint body runs, and the session is only released when the response
    is finished.

    That is fine for a fast handler and ruinous for the 37 routes that carry
    this dependency and then do a slow network scrape. /api/commodities fetches
    from data.humdata.org while holding a connection; the frontend polls it;
    the pool is 15; and once those are held every other route fails with
    "QueuePool limit of size 5 overflow 10 reached" -- an error naming the pool
    rather than the endpoint that exhausted it, on requests that are themselves
    innocent.

    The lookup needs a connection for microseconds. Taking and returning it
    immediately means a slow endpoint holds nothing while it waits on I/O.
    """
    try:
        with session_scope() as session:
            user = session.get(User, user_id)
            if user is None or not user.is_active:
                return None
            if expected_version != user.token_version:
                return None
            # Detached after the session closes, so read what callers need now.
            session.expunge(user)
            return user
    except Exception:  # noqa: BLE001
        logger.exception("[auth] user lookup failed")
        return None


def optional_user(
    authorization: Optional[str] = Header(None),
) -> Optional[User]:
    """Resolve a user if a valid token is present; never raise."""
    token = _bearer(authorization)
    if not token:
        return None
    try:
        claims = decode_access_token(token)
    except (TokenError, TokenExpired):
        return None

    # A token issued before a forced logout carries a stale version, which
    # _lookup_user rejects.
    return _lookup_user(claims.get("sub"), claims.get("ver"))


def require_user(
    authorization: Optional[str] = Header(None),
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

    user = _lookup_user(claims.get("sub"), claims.get("ver"))
    if user is None:
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
) -> ConnectorDevice:
    """
    Authenticate a connector by its device token.

    Always enforced, regardless of AUTH_ENFORCED: /api/ingest writes to the feed,
    so an unauthenticated version of it would be an open write endpoint.

    Short-lived session for the same reason as _lookup_user: a dependency is
    resolved before the endpoint body runs, so a request-scoped one would pin a
    pooled connection for the whole request.
    """
    token = _bearer(authorization)
    if not token:
        raise UNAUTHENTICATED

    try:
        with session_scope() as session:
            device = session.query(ConnectorDevice).filter(
                ConnectorDevice.token_hash == hash_secret(token),
                ConnectorDevice.revoked_at.is_(None),
            ).first()

            if device is not None:
                device.last_seen_at = utcnow()
                session.flush()
                # Read the attributes callers need while still attached, then
                # detach -- expire_on_commit is off, so these stay readable.
                session.expunge(device)
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("[auth] device lookup failed")
        raise UNAUTHENTICATED

    if device is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown or revoked device token"
        )

    return device
