"""
src/social/routes.py
The dashboard's social-account API.

Every route requires a logged-in user. That is not ceremony: these endpoints
store a password, open a browser on the host machine, and read a session
cookie. On a tunnelled laptop, an unauthenticated version of this would let
anyone with the URL do all three.

The password appears in exactly one place -- the body of POST /credentials --
and is never returned, never logged, and never included in any response model.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth.db import get_db
from auth.dependencies import require_user
from auth.models import User

from . import service as social_service

logger = logging.getLogger("Roger.social.routes")

router = APIRouter(prefix="/api/social", tags=["social"])


class CredentialsIn(BaseModel):
    """
    The one request that carries a password.

    Deliberately not logged anywhere, and there is no corresponding response
    model that includes it -- the vault has no method that returns one either.
    """

    platform: str
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=500)


class PlatformIn(BaseModel):
    platform: str


def _check_platform(platform: str) -> str:
    platform = (platform or "").lower().strip()
    if platform not in social_service.SUPPORTED_PLATFORMS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported platform. One of: "
                   f"{', '.join(social_service.SUPPORTED_PLATFORMS)}",
        )
    return platform


def _require(user: Optional[User]) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


@router.get("/accounts")
def list_accounts(user: Optional[User] = Depends(require_user)):
    """Connection state, saved usernames, in-flight jobs and today's budget."""
    _require(user)

    service = social_service.get_service()
    return {
        "accounts": service.accounts(),
        "platforms": list(social_service.SUPPORTED_PLATFORMS),
        # Stated in the API, not only in the UI, so it cannot be missed by
        # someone reading the network tab rather than the page.
        "note": (
            "Credentials are encrypted on the machine running this server and "
            "are never returned by this API. Connecting opens a browser window "
            "on that same machine."
        ),
    }


@router.post("/credentials")
def save_credentials(payload: CredentialsIn,
                     user: Optional[User] = Depends(require_user)):
    """
    Save a social login so the browser form can be pre-filled.

    This does NOT log the account in. The password fills two fields in a real
    browser window and stops -- a human completes the sign-in, including any
    2FA. Automating that step is what turns a routine device-verification
    prompt into a lockout.
    """
    _require(user)
    platform = _check_platform(payload.platform)

    try:
        social_service.get_service().save_credentials(
            platform, payload.username, payload.password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        # Never echo the exception verbatim: a keyring or crypto error can
        # carry fragments of what it was handling.
        logger.exception("[social] could not store credentials for %s", platform)
        raise HTTPException(
            status_code=500,
            detail="Could not store the credentials on this machine.",
        ) from exc

    return {
        "status": "saved",
        "platform": platform,
        "next": "Click Connect to open a browser and finish signing in.",
    }


@router.delete("/credentials/{platform}")
def forget_credentials(platform: str, user: Optional[User] = Depends(require_user)):
    _require(user)
    platform = _check_platform(platform)
    removed = social_service.get_service().forget_credentials(platform)
    return {"status": "forgotten" if removed else "nothing_saved", "platform": platform}


@router.post("/connect")
def connect(payload: PlatformIn, user: Optional[User] = Depends(require_user)):
    """
    Open a browser on the host machine and start a login.

    Returns immediately with a job; a login takes a human a minute or two,
    which is far longer than a request should be held open. Poll /job/{platform}.
    """
    _require(user)
    platform = _check_platform(payload.platform)

    job = social_service.get_service().start_connect(platform)
    return {
        "status": "started",
        "job": job.as_dict(),
        "note": "A browser window is opening on the machine running this server.",
    }


@router.get("/job/{platform}")
def job_status(platform: str, user: Optional[User] = Depends(require_user)):
    _require(user)
    platform = _check_platform(platform)

    job = social_service.get_service().job(platform)
    return {"job": job.as_dict() if job else None}


@router.post("/disconnect")
def disconnect(payload: PlatformIn, user: Optional[User] = Depends(require_user)):
    _require(user)
    platform = _check_platform(payload.platform)

    removed = social_service.get_service().disconnect(platform)
    return {
        "status": "disconnected" if removed else "not_connected",
        "platform": platform,
        # Deleting a local copy does not end the session at the platform.
        # Saying so avoids a false sense of having revoked access.
        "note": (
            "The local session was deleted. To invalidate it at the platform "
            "itself, use their 'log out of all devices' setting."
        ) if removed else None,
    }


@router.post("/resume")
def resume(payload: PlatformIn, user: Optional[User] = Depends(require_user)):
    """
    Lift a challenge cooldown, on the user's word that they have checked.

    Deliberately a manual action with no timer behind it. A challenge is the
    platform asking for proof a person is present; auto-resuming answers that
    with "no", and retrying into a challenge is what escalates it.
    """
    _require(user)
    platform = _check_platform(payload.platform)

    social_service.get_service().resume(platform)
    return {
        "status": "resumed",
        "platform": platform,
        "note": "Collection will retry on the next cycle.",
    }


@router.post("/collect")
def collect_now(payload: PlatformIn,
                user: Optional[User] = Depends(require_user),
                db: Session = Depends(get_db)):
    """
    Collect once from a connected account and store the posts.

    Runs in FastAPI's threadpool -- the scrapers are synchronous and do real
    network I/O, so this must not touch the event loop.
    """
    _require(user)
    platform = _check_platform(payload.platform)

    outcome = social_service.get_service().collect(platform)
    posts = outcome.pop("posts", [])

    stored = 0
    if posts:
        try:
            stored = _store(db, user, posts)
        except Exception:  # noqa: BLE001
            # Never lose the collection result to a storage failure.
            logger.exception("[social] could not store collected posts")

    return {**outcome, "collected": len(posts), "stored": stored}


def _store(db: Session, user: User, posts: list) -> int:
    """
    Persist collected posts, skipping ones already seen.

    Reuses the same table and content hash as the connector's /api/ingest path,
    so posts collected either way deduplicate against each other rather than
    doubling up.
    """
    import hashlib

    from auth.models import IngestedPost

    stored = 0
    for post in posts:
        text = (post.get("text") or "").strip()
        if not text:
            continue

        content_hash = hashlib.sha256(
            f"{post.get('poster') or ''}|{text}".encode("utf-8")
        ).hexdigest()

        exists = db.query(IngestedPost.id).filter_by(
            user_id=user.id, content_hash=content_hash,
        ).first()
        if exists:
            continue

        db.add(IngestedPost(
            user_id=user.id,
            platform=post["platform"],
            poster=post.get("poster"),
            text=text,
            url=post.get("url"),
            posted_at=post.get("posted_at"),
            likes=post.get("likes", 0),
            shares=post.get("shares", 0),
            comments=post.get("comments", 0),
            content_hash=content_hash,
        ))
        stored += 1

    db.commit()
    return stored
