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
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth.db import session_scope
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
    """
    A signed-in user, always -- and not conditional on AUTH_ENFORCED.

    This used to demand an admin, because the credential vault and session store
    were machine-global: one Instagram slot for the whole install, so reaching
    these routes meant reaching the OWNER'S connected accounts. Every caller now
    passes its user to get_service(), which seals that user's passwords and
    cookies under their own directory and their own encryption key, so there is
    nothing left for a second account to reach into. The role check was
    protecting shared state that no longer exists.

    What has NOT been relaxed is the identity requirement. require_user returns
    None when enforcement is off, and these routes still refuse that: without a
    user there is no directory to scope to, so serving the request would mean
    falling back to exactly the shared vault this replaced.
    """
    if user is None:
        raise HTTPException(
            status_code=401,
            detail=(
                "Sign in to manage social accounts. They are stored per account, "
                "so this needs to know who you are."
            ),
        )
    return user


def _require_a_machine_that_can_log_in() -> None:
    """
    Refuse clearly, rather than failing deep inside Playwright.

    Connecting an account is not a thing a server can do, at any memory size.
    browser_login.py launches with headless=False so a human can complete 2FA
    and any challenge, and the resulting session is encrypted to the OS keyring
    of the machine that created it. A container has no display and no keyring.

    Without this the request reaches start_connect, Playwright raises about a
    missing browser or a missing display, and the user gets a stack trace that
    reads like a bug in the platform rather than "this cannot be done here".

    DISABLE_LOCAL_SOCIAL_SESSIONS is the signal: the deployment sets it
    precisely because sessions do not belong on a shared host, so it already
    means "this machine is not where accounts live".
    """
    import os

    disabled = (os.getenv("DISABLE_LOCAL_SOCIAL_SESSIONS", "") or "").strip()
    if disabled.lower() in ("1", "true", "yes", "on"):
        raise HTTPException(
            status_code=503,
            detail=(
                "Accounts cannot be connected on this server. Signing in opens "
                "a real browser window for two-factor authentication, and the "
                "session is encrypted to that machine's keyring -- neither "
                "exists in a container. Run the collector on your own machine "
                "(backend/scripts/collector.py, see HOSTING.md); it shares "
                "this database and this pacing gate, so anything it collects "
                "appears here."
            ),
        )

    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except Exception:
        raise HTTPException(
            status_code=503,
            detail=(
                "Playwright is not installed on this server, so no browser can "
                "be opened. This is deliberate in the deployed image: social "
                "collection runs on the user's own machine. See HOSTING.md."
            ),
        )


@router.get("/accounts")
def list_accounts(user: Optional[User] = Depends(require_user)):
    """Connection state, saved usernames, in-flight jobs and today's budget."""
    _require(user)

    service = social_service.get_service(user.id)
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
        social_service.get_service(user.id).save_credentials(
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
    removed = social_service.get_service(user.id).forget_credentials(platform)
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
    _require_a_machine_that_can_log_in()

    job = social_service.get_service(user.id).start_connect(platform)
    return {
        "status": "started",
        "job": job.as_dict(),
        "note": "A browser window is opening on the machine running this server.",
    }


@router.get("/job/{platform}")
def job_status(platform: str, user: Optional[User] = Depends(require_user)):
    _require(user)
    platform = _check_platform(platform)

    job = social_service.get_service(user.id).job(platform)
    return {"job": job.as_dict() if job else None}


@router.post("/disconnect")
def disconnect(payload: PlatformIn, user: Optional[User] = Depends(require_user)):
    _require(user)
    platform = _check_platform(payload.platform)

    removed = social_service.get_service(user.id).disconnect(platform)
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

    social_service.get_service(user.id).resume(platform)
    return {
        "status": "resumed",
        "platform": platform,
        "note": "Collection will retry on the next cycle.",
    }


@router.post("/collect")
def collect_now(payload: PlatformIn,
                user: Optional[User] = Depends(require_user)):
    """
    Collect once from a connected account and store the posts.

    Runs in FastAPI's threadpool -- the scrapers are synchronous and do real
    network I/O, so this must not touch the event loop.

    Deliberately does NOT take Depends(get_db). FastAPI resolves dependencies
    before the body runs, so a request-scoped session would be held for the
    whole call -- and this call drives a Playwright browser, which is minutes.
    That is the same mistake that exhausted the pool via require_user and made
    every other route return 500 while naming the pool rather than the culprit.
    The session is opened below, after the scrape, only if there is anything to
    write.
    """
    _require(user)
    platform = _check_platform(payload.platform)
    # Collection drives a browser too, so the same refusal applies --
    # and reaching it means the account was connected somewhere else.
    _require_a_machine_that_can_log_in()

    outcome = social_service.get_service(user.id).collect(platform)
    posts = outcome.pop("posts", [])

    stored = 0
    if posts:
        try:
            with session_scope() as db:
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
        images = post.get("images") or []

        # A post with no caption but an image is now kept -- the scrapers used
        # to discard those, which threw away exactly the ones whose content
        # lives in the picture. The hash falls back to the image URLs so two
        # different image-only posts do not collide on an empty string.
        if not text and not images:
            continue

        content_hash = hashlib.sha256(
            f"{post.get('poster') or ''}|{text or '|'.join(images)}".encode("utf-8")
        ).hexdigest()

        exists = db.query(IngestedPost.id).filter_by(
            user_id=user.id, content_hash=content_hash,
        ).first()
        if exists:
            continue

        row = IngestedPost(
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
        )
        db.add(row)
        db.flush()          # assigns row.id, which PostImage rows reference
        stored += 1

        # Read the pictures BEFORE handing the post on, so the extracted text
        # reaches classification with everything else. Doing it afterwards
        # would mean severity, entities and stories were all decided without
        # the contents of the image -- which on an image-only post is the
        # entire post.
        enriched = text
        if images:
            try:
                from src.images import ingest_post_images
                from src.images.pipeline import text_from

                results = ingest_post_images(row.id, images, db)
                enriched = (text + text_from(results)).strip()
            except Exception:  # noqa: BLE001
                # An unreadable image costs its text, never the post.
                logger.exception("[social] image processing failed for a post")

        if enriched:
            _to_intelligence_pipeline(post, enriched)

    db.commit()
    return stored


def _to_intelligence_pipeline(post: dict, text: str) -> None:
    """
    Hand a collected post to the same ingestion the agents feed.

    Without this, "Collect now" was a dead end. Posts went into IngestedPost,
    whose only reader is /api/ingest/recent -- the COLLECTED POSTS panel. They
    were displayed and then never classified, never given entities, never
    threaded into a story, and never reached the intelligence feed. Searching
    src/nodes for IngestedPost returns nothing.

    The agent loop's own social scraping (via get_credential) always went
    through storage_manager, so the two paths were producing different
    outcomes from the same scraper. This converges them.

    Deliberately best-effort: a storage failure must not lose the posts already
    written above, which are what the user asked for by pressing the button.
    """
    try:
        from main import storage_manager
    except Exception:  # noqa: BLE001
        return

    try:
        # storage_manager owns semantic dedup; asking first keeps the vector
        # store from filling with near-identical events.
        is_dup, _, _ = storage_manager.is_duplicate(text)
        if is_dup:
            return

        storage_manager.store_event(
            event_id=str(uuid.uuid4()),
            summary=text,
            domain="social",
            # Unclassified on purpose. The aggregator assigns severity and
            # impact_type from the LLM; inventing them here would put a
            # confident-looking guess next to model output, which is the
            # provenance problem this codebase keeps having to undo.
            severity="low",
            impact_type="risk",
            confidence_score=0.5,
            metadata={
                "platform": post.get("platform"),
                "poster": post.get("poster"),
                "url": post.get("url"),
                "source_tool": "social_collect_now",
            },
        )
    except Exception:  # noqa: BLE001
        logger.exception("[social] could not hand post to the intelligence pipeline")


# --- search by picture -------------------------------------------------------

@router.post("/images/search")
async def search_images(
    file: UploadFile = File(...),
    limit: int = 20,
    user: Optional[User] = Depends(require_user),
):
    """
    Find collected posts containing this image, or one like it.

    Available to any signed-in user rather than admins only: unlike the
    credential routes, this reads already-collected intelligence and touches no
    session. Checking whether a photograph has been posted before is exactly
    the sort of verification a viewer should be able to do.

    Two kinds of answer, and the response says which: `same_image` means the
    perceptual hashes match, so this photograph has appeared before -- the
    recycled-disaster-photo case. `similar_scene` means CLIP thinks they look
    alike, which is context, not proof.
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload")
    if len(data) > 12 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image is too large (max 12 MB)")

    from src.images.search import search_by_image

    with session_scope() as db:
        result = search_by_image(data, db, limit=min(limit, 50))

    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result
