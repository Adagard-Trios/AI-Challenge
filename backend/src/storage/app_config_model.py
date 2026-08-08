"""
src/storage/app_config_model.py
Application configuration that users edit at runtime.

WHY THIS MOVED OFF DISK
-----------------------
intel_config -- the watched profiles, keywords and products that shape what the
agents scrape -- was read from and written to

    backend/src/config/intel_config.json

which is INSIDE THE SOURCE TREE, and therefore inside the container image. Two
consequences, both silent:

  - Every edit is lost on the next deploy or restart, because an image layer is
    not writable state. A user sets their watchlist, it works, and it is gone
    the next time the pod restarts.
  - With more than one replica each holds its own copy, so which keywords the
    agents use depends on which pod served the PUT.

It is also a read-modify-write of a file that decides what gets collected, so
two concurrent edits silently lose one.

One row, because it is one document. A schema per field would be tidier and
would mean a migration every time the frontend adds a checkbox; the shape is
owned by the UI and this table is a place to keep it.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.types import JSON

from auth.models import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AppConfig(Base):
    """A named JSON document. Currently one row: "intel"."""

    __tablename__ = "app_config"

    key = Column(String(64), primary_key=True)
    doc = Column(JSON, nullable=False, default=dict)
    updated_at = Column(DateTime(timezone=True), nullable=False,
                        default=utcnow, onupdate=utcnow)
    # Bumped on every write. Not used for locking yet, but it is the difference
    # between "we could detect a lost update" and "we would have to add a
    # column first".
    revision = Column(Integer, nullable=False, default=1)
