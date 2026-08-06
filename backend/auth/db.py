"""
auth/db.py
Engine and session management.

pool_pre_ping is not optional here. Neon autosuspends after ~5 minutes idle and
Render free spins the service down after ~15, so the first request after a quiet
period reliably lands on a dead connection. Without pre-ping that surfaces as an
OperationalError on login -- intermittently, and only in production.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .models import Base

logger = logging.getLogger("Roger.auth.db")

_engine: Engine | None = None
_SessionFactory: sessionmaker | None = None


def engine() -> Engine:
    global _engine, _SessionFactory
    if _engine is not None:
        return _engine

    cfg = settings()
    kwargs: dict = {"pool_pre_ping": True, "future": True}

    if cfg.is_sqlite:
        # check_same_thread=False: the agent loop runs in a background thread and
        # opens its own session.
        kwargs["connect_args"] = {"check_same_thread": False}

    elif cfg.behind_transaction_pooler:
        # Supabase's transaction pooler (PgBouncer, port 6543) multiplexes many
        # clients onto few server connections. Two consequences, both of which
        # produce confusing intermittent errors rather than clean failures:
        #
        # 1. Prepared statements do not survive, because a statement prepared on
        #    one server connection is not there on the next. psycopg3 prepares
        #    automatically after a few executions, so this surfaces as
        #    "prepared statement _pg3_0 already exists" once traffic warms up --
        #    not at startup, which makes it look random.
        #    prepare_threshold=None disables that.
        #
        # 2. Pooling on top of a pooler is worse than not pooling: SQLAlchemy
        #    holds connections PgBouncer wants to reuse. NullPool hands each
        #    checkout straight through.
        from sqlalchemy.pool import NullPool
        kwargs["poolclass"] = NullPool
        kwargs["connect_args"] = {"prepare_threshold": None}
        kwargs.pop("pool_pre_ping", None)   # meaningless without a pool
        logger.info("[auth.db] transaction pooler detected: NullPool, no prepared statements")

    else:
        # Direct Postgres. Small pool -- a 512 MB instance cannot afford many,
        # and managed free tiers cap connections tightly.
        kwargs.update(pool_size=3, max_overflow=2, pool_recycle=280)

    _engine = create_engine(cfg.database_url, **kwargs)

    if cfg.is_sqlite:
        @event.listens_for(_engine, "connect")
        def _sqlite_pragmas(conn, _record):    # pragma: no cover
            cur = conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")    # concurrent read + write
            cur.execute("PRAGMA foreign_keys=ON")     # OFF by default in SQLite
            cur.close()

    _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    logger.info("[auth.db] engine ready (%s)", "sqlite" if cfg.is_sqlite else "postgres")
    return _engine


def session_factory() -> sessionmaker:
    if _SessionFactory is None:
        engine()
    assert _SessionFactory is not None
    return _SessionFactory


def init_db() -> None:
    """
    Create tables if absent.

    Deliberately not Alembic yet: a handful of tables and one deployment.
    Alembic is a discipline rather than a library, and adding it before the
    first destructive schema change is ceremony. Introduce it when that lands.
    """
    # Imported for the side effect of registering on Base.metadata. Without
    # this, entities/event_entities/exposure_profiles are never created and
    # every entity write fails against a missing table -- at runtime, in
    # production, with the feature looking implemented.
    from src.intelligence import models as _intelligence_models  # noqa: F401
    from src.intelligence import commands as _connector_commands  # noqa: F401

    Base.metadata.create_all(bind=engine())
    logger.info("[auth.db] schema ready (%d tables)", len(Base.metadata.tables))


@contextmanager
def session_scope() -> Iterator[Session]:
    """
    For background work -- the agent loop, the connector poller.

    Never share a Session across a thread boundary; open one per unit of work.
    """
    db = session_factory()()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    db = session_factory()()
    try:
        yield db
    finally:
        db.close()


def reset_engine() -> None:
    """Tests."""
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionFactory = None
