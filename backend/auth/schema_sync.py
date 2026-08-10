"""
auth/schema_sync.py
Add columns that the models grew after a database was created.

WHY THIS EXISTS
---------------
init_db() calls Base.metadata.create_all, which creates missing TABLES and
does nothing at all to existing ones. Add a column to a model and every
install created before that change keeps the old table -- and then every query
touching it fails with "no such column", at runtime, on a database that looks
present and healthy.

That is not hypothetical. Adding the budget_* columns to SocialConnection broke
`/api/connections` and any delete cascading through it on every database
created before that commit, with no migration and no warning.

WHY NOT ALEMBIC
---------------
Alembic is the right answer and remains the plan; it is a discipline rather
than a library, and introducing it properly means a baseline revision plus a
migration for every past change. This closes the immediate hole without
pretending to be that.

WHAT THIS DELIBERATELY WILL NOT DO
----------------------------------
Only ADD nullable columns. It never drops, renames, retypes or backfills --
those are destructive, they need a human decision about the data, and a
best-effort guess is how you lose a column's worth of history. Anything beyond
an additive change is reported and left alone.
"""

from __future__ import annotations

import logging
from typing import List

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger("Roger.auth.schema")


def _column_sql(column) -> str | None:
    """
    The type, rendered for ALTER TABLE ADD COLUMN.

    Returns None for anything that cannot be added safely -- a NOT NULL column
    with no default cannot be added to a table with rows.
    """
    if not column.nullable and column.default is None and column.server_default is None:
        return None

    try:
        from sqlalchemy.schema import CreateColumn

        return str(CreateColumn(column).compile()).strip()
    except Exception:  # noqa: BLE001
        return None


def sync(engine: Engine, *, dry_run: bool = False) -> List[str]:
    """
    Add any missing nullable columns. Returns what it did (or would do).

    Safe to call on every startup: inspecting is cheap and the common case is
    an empty list.
    """
    from .models import Base

    applied: List[str] = []
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # create_all handles whole tables

        on_disk = {c["name"] for c in inspector.get_columns(table.name)}
        missing = [c for c in table.columns if c.name not in on_disk]
        if not missing:
            continue

        for column in missing:
            ddl = _column_sql(column)
            if ddl is None:
                # Loud, because the alternative is a runtime failure later on a
                # query that looks unrelated.
                logger.error(
                    "[schema] %s.%s is missing and cannot be added automatically "
                    "(NOT NULL with no default). This needs a migration.",
                    table.name, column.name,
                )
                continue

            statement = f"ALTER TABLE {table.name} ADD COLUMN {ddl}"
            applied.append(f"{table.name}.{column.name}")
            if dry_run:
                continue

            try:
                with engine.begin() as conn:
                    conn.execute(text(statement))
                logger.warning("[schema] added %s.%s", table.name, column.name)
            except Exception as exc:  # noqa: BLE001
                # A concurrent worker may have added it already; re-inspecting
                # is cheaper than locking.
                if "duplicate column" in str(exc).lower():
                    applied.remove(f"{table.name}.{column.name}")
                    continue
                logger.error("[schema] could not add %s.%s: %s",
                             table.name, column.name, exc)
                applied.remove(f"{table.name}.{column.name}")

    if applied:
        logger.warning(
            "[schema] brought %d column(s) up to date: %s",
            len(applied), ", ".join(applied),
        )
    return applied
