"""
src/intelligence/command_routes.py
The dashboard end of the connector command queue.

Two audiences, two auth schemes, deliberately:

  - the browser (require_user) queues commands and reads their status
  - the connector (require_device) claims them and reports back

They never share an endpoint. A device token cannot queue work, and a browser
session cannot claim it, so a stolen device token buys an attacker nothing
beyond what that connector could already do.

Nothing here accepts a credential. The payload a browser sends is an action and
a platform name; the connector supplies its own locally-stored credentials when
it executes.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth.db import get_db
from auth.dependencies import require_device, require_user

from . import commands as command_service

logger = logging.getLogger("command_routes")

router = APIRouter(prefix="/api/connector", tags=["connector"])

PLATFORMS = ("twitter", "linkedin", "facebook", "instagram")


class CommandRequest(BaseModel):
    action: str
    platform: str


class CommandResult(BaseModel):
    ok: bool
    result: str = ""


def _require_identified_user(user):
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in to control your connector.",
        )
    return user


# --- browser side ----------------------------------------------------------

@router.post("/commands")
def queue_command(
    payload: CommandRequest,
    user=Depends(require_user),
    db: Session = Depends(get_db),
):
    """
    Ask this user's connector to do something on their machine.

    The response says explicitly whether a connector is actually running. A
    queued command against a stopped connector is valid -- it runs when one
    starts -- but a button that appears to work and silently does nothing is
    the failure mode this whole codebase keeps being bitten by.
    """
    user = _require_identified_user(user)

    if payload.action not in command_service.ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown action. Expected one of {list(command_service.ACTIONS)}.",
        )
    if payload.platform not in PLATFORMS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown platform. Expected one of {list(PLATFORMS)}.",
        )

    command = command_service.queue(db, user.id, payload.action, payload.platform)
    running = command_service.connector_is_running(db, user.id)

    return {
        "command": command.as_dict(),
        "connector_running": running,
        "message": (
            f"Your connector will {payload.action} {payload.platform} shortly."
            if running
            else (
                "Queued, but no connector is running. Start it with "
                "`python -m connector run` and this will execute within a minute."
            )
        ),
    }


@router.get("/commands")
def list_commands(user=Depends(require_user), db: Session = Depends(get_db)):
    """Recent commands and whether a connector is alive to run them."""
    user = _require_identified_user(user)
    return {
        "commands": command_service.recent(db, user.id),
        "connector_running": command_service.connector_is_running(db, user.id),
    }


# --- connector side --------------------------------------------------------

@router.get("/commands/pending")
def claim_commands(
    device=Depends(require_device),
    db: Session = Depends(get_db),
):
    """
    Claim the commands waiting for this device's user.

    Polled by the connector's collect loop, so claiming also serves as the
    liveness ping that `connector_is_running` reads -- require_device already
    stamps last_seen_at.
    """
    claimed = command_service.claim_pending(db, device.user_id)
    return {"commands": [c.as_dict() for c in claimed]}


@router.post("/commands/{command_id}/result")
def report_result(
    command_id: str,
    payload: CommandResult,
    device=Depends(require_device),
    db: Session = Depends(get_db),
):
    """Report the outcome. Scoped to the device's own user."""
    updated = command_service.complete(
        db, command_id, device.user_id, payload.ok, payload.result
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Unknown command")
    return {"ok": True}
