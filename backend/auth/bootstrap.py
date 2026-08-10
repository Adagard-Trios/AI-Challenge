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


def _normalise_roles() -> None:
    """
    Lift every pre-existing account to the single role.

    Accounts created before the viewer/admin split was retired still carry
    "viewer" or "member", and is_admin compares against one string -- so without
    this they would sign in successfully and then be refused their own social
    accounts, which is precisely the dead end this change set out to remove.

    Idempotent, and silent when there is nothing to do, so it costs an indexed
    UPDATE returning zero rows on every subsequent boot.
    """
    from .models import DEFAULT_ROLE, User

    with session_scope() as db:
        stale = db.query(User).filter(User.role != DEFAULT_ROLE).all()
        if not stale:
            return
        for user in stale:
            user.role = DEFAULT_ROLE
        db.commit()
        logger.info(
            "[auth] lifted %d account(s) to the single role; the viewer tier is retired",
            len(stale),
        )


def _seed_admin() -> None:
    """
    Create the owner account from env, but only when there are no users at all.

    Guarding on an empty table rather than on the email means a later change to
    BOOTSTRAP_ADMIN_EMAIL cannot quietly mint a second admin.
    """
    email = (os.getenv("BOOTSTRAP_ADMIN_EMAIL") or "").strip().lower()
    password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD") or ""

    if not email or not password:
        # Only worth saying when neither exists yet; otherwise it is noise on
        # every boot of a working install.
        return

    with session_scope() as db:
        if db.scalar(select(User.id).limit(1)) is not None:
            # Not an error, but worth stating: this is why editing
            # BOOTSTRAP_ADMIN_PASSWORD and restarting appears to do nothing.
            # The seed guards on an EMPTY table so a later edit cannot quietly
            # mint a second admin -- which also means it cannot change the
            # first one's password.
            logger.info(
                "[auth] users already exist; BOOTSTRAP_ADMIN_* is ignored. "
                "To change a password: python scripts/create_admin.py "
                "--email %s --force", email,
            )
            return

        try:
            pw_hash = hash_password(password, rounds=settings().bcrypt_rounds)
        except WeakPassword as exc:
            # This used to log once and return, leaving an empty user table, a
            # correctly-set pair of env vars, and no way to log in. Someone
            # then edits .env, restarts, and nothing changes -- with the only
            # clue a single line lost in startup output.
            logger.error(
                "[auth] ================================================\n"
                "[auth] NO ADMIN WAS CREATED. BOOTSTRAP_ADMIN_PASSWORD is "
                "rejected: %s\n"
                "[auth] The user table is empty, so NOBODY CAN LOG IN and "
                "every authenticated route will return 401.\n"
                "[auth] Fix the password in .env and restart, or run:\n"
                "[auth]     python scripts/create_admin.py\n"
                "[auth] ================================================",
                exc,
            )
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
        _normalise_roles()
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
