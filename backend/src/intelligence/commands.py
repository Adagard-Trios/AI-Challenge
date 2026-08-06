"""
src/intelligence/commands.py
Letting the web dashboard drive the connector on the user's machine.

Connecting an account has to happen locally -- the password and the session
cookie must never reach this server -- but that meant the only way to do it was
a terminal, while the dashboard could show account status and nothing else.

This closes that gap without moving any secret. The dashboard queues an
INSTRUCTION ("connect linkedin"); the connector, already polling on its collect
loop, picks it up and does the work on the user's own machine using the
credentials in its own local vault. What crosses the wire is a verb and a
platform name. Never a credential.

Two properties this is built around:

**A closed vocabulary.** ACTIONS is a fixed tuple and the platform is validated
against the taxonomy. A command is not a script. Even a fully compromised server
can only ask a connector to do one of three things it was already willing to do,
to an account the user already connected.

**Queued is not done.** A command sits pending until a connector claims it. If
no connector is running, it stays pending and the dashboard says so, rather than
showing a button that appeared to work. That distinction is the whole reason
the model carries separate picked_up_at and completed_at timestamps.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from auth.models import Base, new_id, utcnow

logger = logging.getLogger("connector_commands")

# What the dashboard may ask a connector to do. Deliberately tiny.
ACTIONS = ("connect", "collect", "disconnect")

# A connector that has not polled in this long is treated as not running, so
# the dashboard can say "start the connector" instead of leaving a queued
# command looking like a working button.
CONNECTOR_ALIVE_WINDOW = timedelta(minutes=5)

# A command nobody claimed is not worth running an hour later -- the user has
# moved on, and a browser window opening unprompted is alarming.
COMMAND_TTL = timedelta(minutes=15)


class ConnectorCommand(Base):
    """One instruction, queued for a user's connector."""

    __tablename__ = "connector_commands"
    __table_args__ = (
        Index("ix_commands_pending", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    action: Mapped[str] = mapped_column(String(20))
    platform: Mapped[str] = mapped_column(String(20))

    # pending -> running -> done | failed | expired
    status: Mapped[str] = mapped_column(String(20), default="pending")
    result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    picked_up_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "action": self.action,
            "platform": self.platform,
            "status": self.status,
            "result": self.result,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "picked_up_at": (
                self.picked_up_at.isoformat() if self.picked_up_at else None
            ),
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
        }


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    """Rows written before the tz-aware default would compare as naive."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def connector_is_running(db, user_id: str) -> bool:
    """
    Has any of this user's connectors polled recently?

    Drives the honest message in the dashboard. Queuing a command against a
    connector that is not running is allowed -- it will run when one starts --
    but the user has to be told that is what happened.
    """
    from auth.models import ConnectorDevice

    cutoff = datetime.now(timezone.utc) - CONNECTOR_ALIVE_WINDOW
    devices = (
        db.query(ConnectorDevice)
        .filter(
            ConnectorDevice.user_id == user_id,
            ConnectorDevice.revoked_at.is_(None),
        )
        .all()
    )
    return any(
        (_aware(d.last_seen_at) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
        for d in devices
    )


def queue(db, user_id: str, action: str, platform: str) -> ConnectorCommand:
    """
    Add a command, replacing any identical one still pending.

    Clicking Connect twice should not open two browser windows -- so an
    unclaimed command for the same action and platform is reused rather than
    duplicated.
    """
    if action not in ACTIONS:
        raise ValueError(f"Unknown action {action!r}; expected one of {ACTIONS}")

    existing = (
        db.query(ConnectorCommand)
        .filter_by(
            user_id=user_id, action=action, platform=platform, status="pending"
        )
        .first()
    )
    if existing is not None:
        return existing

    command = ConnectorCommand(
        user_id=user_id, action=action, platform=platform, status="pending"
    )
    db.add(command)
    db.commit()
    db.refresh(command)

    logger.info("[commands] queued %s %s for %s", action, platform, user_id)
    return command


def claim_pending(db, user_id: str, limit: int = 5) -> list:
    """
    Hand a connector the commands waiting for it, marking them running.

    Expired commands are swept here rather than by a scheduled job: this is the
    only code path that runs regularly, and a background sweeper would be a
    second thing to keep alive for no benefit.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - COMMAND_TTL

    rows = (
        db.query(ConnectorCommand)
        .filter_by(user_id=user_id, status="pending")
        .order_by(ConnectorCommand.created_at.asc())
        .limit(limit)
        .all()
    )

    claimed = []
    for command in rows:
        if (_aware(command.created_at) or now) < cutoff:
            command.status = "expired"
            command.completed_at = now
            command.result = "No connector claimed this within 15 minutes."
            continue

        command.status = "running"
        command.picked_up_at = now
        claimed.append(command)

    db.commit()
    return claimed


def complete(db, command_id: str, user_id: str, ok: bool, result: str = "") -> bool:
    """Record what happened. Scoped by user so a device cannot close another's."""
    command = (
        db.query(ConnectorCommand)
        .filter_by(id=command_id, user_id=user_id)
        .one_or_none()
    )
    if command is None:
        return False

    command.status = "done" if ok else "failed"
    command.result = (result or "")[:2000]
    command.completed_at = datetime.now(timezone.utc)
    db.commit()
    return True


def recent(db, user_id: str, limit: int = 20) -> list:
    rows = (
        db.query(ConnectorCommand)
        .filter_by(user_id=user_id)
        .order_by(ConnectorCommand.created_at.desc())
        .limit(limit)
        .all()
    )
    return [r.as_dict() for r in rows]
