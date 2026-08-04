"""
auth/bootstrap.py
Idempotent startup: create tables, seed the first admin.
"""

from __future__ import annotations

import logging
import os

from sqlalchemy import select

from .config import AuthConfigError, settings
from .db import init_db, session_scope
from .models import User
from .passwords import WeakPassword, hash_password

logger = logging.getLogger("Roger.auth.bootstrap")


def _seed_admin() -> None:
    """
    Create the owner account from env, but only when there are no users at all.

    Guarding on an empty table rather than on the email means a later change to
    BOOTSTRAP_ADMIN_EMAIL cannot quietly mint a second admin.
    """
    email = (os.getenv("BOOTSTRAP_ADMIN_EMAIL") or "").strip().lower()
    password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD") or ""

    if not email or not password:
        return

    with session_scope() as db:
        if db.scalar(select(User.id).limit(1)) is not None:
            return  # already bootstrapped

        try:
            pw_hash = hash_password(password, rounds=settings().bcrypt_rounds)
        except WeakPassword as exc:
            logger.error("[auth] BOOTSTRAP_ADMIN_PASSWORD rejected: %s", exc)
            return

        db.add(User(email=email, password_hash=pw_hash, role="admin", display_name="Owner"))
        logger.warning(
            "[auth] Seeded initial admin %s from BOOTSTRAP_ADMIN_* -- "
            "change the password and clear those env vars.", email
        )


def init() -> bool:
    """
    Prepare auth. Returns False when it could not start.

    Never raises on the non-enforced path: with AUTH_ENFORCED unset the platform
    must keep serving exactly as before, so an auth problem degrades to "auth
    unavailable" rather than taking the whole service down. With enforcement on,
    a failure here is fatal by design -- a half-initialised auth layer is worse
    than no service.
    """
    try:
        cfg = settings()
    except AuthConfigError:
        logger.exception("[auth] configuration invalid")
        raise

    try:
        init_db()
        _seed_admin()
    except Exception:
        logger.exception("[auth] initialisation failed")
        if cfg.enforced:
            raise
        logger.error("[auth] continuing without auth (AUTH_ENFORCED is off)")
        return False

    from . import ws_tickets
    ws_tickets.assert_single_worker()

    logger.info(
        "[auth] ready | enforced=%s | store=%s",
        cfg.enforced, "sqlite" if cfg.is_sqlite else "postgres",
    )
    if not cfg.enforced:
        logger.warning(
            "[auth] AUTH_ENFORCED is off -- every API route is publicly "
            "readable and writable. Set it to 1 once the frontend sends tokens."
        )
    return True
