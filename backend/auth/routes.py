"""
auth/routes.py
Auth, account-connection, connector-pairing and ingest endpoints.

APIRouter is used for new routes only. The 39 pre-existing routes in main.py are
deliberately left as they are -- converting them would be a large, risky diff
with no user-visible benefit, on a file that has already hidden three
duplicate-registration bugs.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import ws_tickets
from .config import settings
from .db import get_db
from .dependencies import require_admin, require_device, require_user
from .models import (
    ConnectorDevice, IngestedPost, Invite, SocialConnection, User, utcnow,
)
from .passwords import WeakPassword, hash_password, verify_password
from .tokens import (
    TokenError, TokenExpired, TokenReplayed, hash_secret, issue_pair,
    new_pair_code, new_secret, revoke_all_for_user, revoke_family,
    rotate_refresh_token,
)

logger = logging.getLogger("Roger.auth.routes")

router = APIRouter(prefix="/api", tags=["auth"])

PLATFORMS = {"twitter", "facebook", "instagram", "linkedin", "reddit"}

# Pragmatic email check rather than pydantic's EmailStr, which pulls in
# email-validator -- a dependency the slim runtime set does not carry, and one
# that is hard to justify for an invite-only tool where an admin types the
# address. This rejects the shapes that are obviously wrong and normalises case;
# deliverability is proven by the invite actually arriving, not by a regex.
_EMAIL_RE = __import__("re").compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email(value: str) -> str:
    value = (value or "").strip().lower()
    if not _EMAIL_RE.match(value) or len(value) > 320:
        raise ValueError("not a valid email address")
    return value


class _EmailModel(BaseModel):
    @field_validator("email", check_fields=False)
    @classmethod
    def _email(cls, v: str) -> str:
        return _validate_email(v)


# --- schemas ---------------------------------------------------------------

class LoginRequest(_EmailModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    # Accepted from the body now; the endpoint is written so a cookie can supply
    # it later without a rewrite, once a custom domain makes cookies viable.
    refresh_token: Optional[str] = None


class AcceptInviteRequest(BaseModel):
    token: str
    password: str
    display_name: Optional[str] = None


class RegisterRequest(_EmailModel):
    email: str
    password: str
    display_name: Optional[str] = None


class InviteRequest(_EmailModel):
    email: str
    role: str = Field(default="member", pattern="^(member|admin)$")


class ConnectionUpsert(BaseModel):
    platform: str
    handle: Optional[str] = None
    session_expires_at: Optional[datetime] = None
    status: str = "ok"
    status_reason: Optional[str] = None

    # Today's pacing budget, mirrored from the connector for display.
    #
    # Optional throughout: an older connector does not send it, and absent must
    # read as "not reported" rather than as zero consumption -- a budget shown
    # as 0/120 when it is really 118/120 is worse than showing nothing.
    budget: Optional["BudgetReport"] = None


class BudgetReport(BaseModel):
    day: Optional[str] = None
    requests_used: Optional[int] = None
    requests_cap: Optional[int] = None
    posts_used: Optional[int] = None
    posts_cap: Optional[int] = None


class IngestedPostIn(BaseModel):
    platform: str
    poster: Optional[str] = None
    text: str
    url: Optional[str] = None
    posted_at: Optional[str] = None
    likes: int = 0
    shares: int = 0
    comments: int = 0


class IngestRequest(BaseModel):
    posts: List[IngestedPostIn] = Field(default_factory=list)
    connection_status: Optional[ConnectionUpsert] = None


def _content_hash(poster: Optional[str], text: str) -> str:
    """Mirrors db_manager.generate_content_hash so dedup stays consistent."""
    import hashlib
    return hashlib.sha256(f"{poster or ''}|{text}".encode("utf-8")).hexdigest()


def _user_out(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


# --- auth ------------------------------------------------------------------

@router.post("/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.lower()))

    # Verify even when the user is missing, so response timing does not reveal
    # which emails exist.
    stored = user.password_hash if user else "$2b$12$" + "x" * 53
    ok = verify_password(payload.password, stored)

    if not user or not ok or not user.is_active:
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    user.last_login_at = utcnow()
    pair = issue_pair(db, user)
    db.commit()
    return {**pair.as_dict(), "user": _user_out(user)}


@router.post("/auth/refresh")
def refresh(payload: RefreshRequest = Body(default=RefreshRequest()),
            db: Session = Depends(get_db)):
    if not payload.refresh_token:
        raise HTTPException(status_code=400, detail="refresh_token is required")
    try:
        pair = rotate_refresh_token(db, payload.refresh_token)
    except TokenReplayed as exc:
        # 401, and the family is already revoked. The client must log in again.
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except (TokenExpired, TokenError) as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return pair.as_dict()


@router.post("/auth/logout")
def logout(payload: RefreshRequest = Body(default=RefreshRequest()),
           db: Session = Depends(get_db)):
    if payload.refresh_token:
        revoke_family(db, payload.refresh_token)
    return {"status": "logged_out"}


@router.post("/auth/ws-ticket")
def ws_ticket(user: Optional[User] = Depends(require_user)):
    """Short-lived single-use ticket for the WebSocket handshake."""
    if user is None:
        if settings().enforced:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"ticket": None, "auth_enforced": False}
    return {"ticket": ws_tickets.issue(user.id), "expires_in": ws_tickets.TICKET_TTL_SECONDS}


def self_registration_open() -> bool:
    """
    Whether anyone may create their own account.

    On by default because it was asked for, but read at request time rather
    than import time so it can be turned off without a redeploy -- which is the
    thing you want available if signups are ever abused.
    """
    return os.getenv("ALLOW_SELF_REGISTRATION", "1").strip().lower() in (
        "1", "true", "yes", "on",
    )


@router.get("/auth/registration")
def registration_status():
    """Lets the login page show or hide the Register form. Public by necessity."""
    return {"open": self_registration_open()}


@router.post("/auth/register")
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    """
    Create an account, unprivileged.

    The role matters more than it looks. The social vault and session store are
    machine-global -- one CredentialVault for the whole install, no user_id
    anywhere -- so any account that can reach /api/social/* can list the
    owner's connected accounts and collect using their session.

    Open registration would therefore have handed a stranger the owner's
    Instagram. That is why every social route now requires an ADMIN, and why
    accounts made here are never one. See src/social/routes.py.
    """
    if not self_registration_open():
        raise HTTPException(
            status_code=403,
            detail="Self-registration is disabled on this instance.",
        )

    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        # Deliberately explicit. Account enumeration matters on a login form,
        # where a silent failure protects the existing user; on a signup form
        # the alternative is someone retyping a password they already have.
        raise HTTPException(
            status_code=409, detail="An account already exists for that email"
        )

    try:
        pw_hash = hash_password(payload.password, rounds=settings().bcrypt_rounds)
    except WeakPassword as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    user = User(
        email=email,
        password_hash=pw_hash,
        display_name=payload.display_name,
        role="viewer",
    )
    db.add(user)
    db.flush()

    pair = issue_pair(db, user)
    db.commit()
    logger.info("[auth] self-registered %s as viewer", email)
    return {**pair.as_dict(), "user": _user_out(user)}


@router.post("/auth/accept-invite")
def accept_invite(payload: AcceptInviteRequest, db: Session = Depends(get_db)):
    invite = db.scalar(select(Invite).where(Invite.token_hash == hash_secret(payload.token)))
    if invite is None or not invite.is_usable:
        raise HTTPException(status_code=400, detail="Invite is invalid or has expired")

    if db.scalar(select(User).where(User.email == invite.email.lower())):
        raise HTTPException(status_code=409, detail="An account already exists for that email")

    try:
        pw_hash = hash_password(payload.password, rounds=settings().bcrypt_rounds)
    except WeakPassword as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    user = User(
        email=invite.email.lower(),
        password_hash=pw_hash,
        display_name=payload.display_name,
        role=invite.role,
    )
    db.add(user)
    invite.used_at = utcnow()
    db.flush()

    pair = issue_pair(db, user)
    db.commit()
    return {**pair.as_dict(), "user": _user_out(user)}


@router.get("/me")
def me(user: Optional[User] = Depends(require_user)):
    if user is None:
        return {"authenticated": False, "auth_enforced": settings().enforced}
    return {"authenticated": True, "user": _user_out(user)}


@router.post("/me/logout-everywhere")
def logout_everywhere(user: Optional[User] = Depends(require_user),
                      db: Session = Depends(get_db)):
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    revoke_all_for_user(db, user)
    return {"status": "all_sessions_revoked"}


# --- invites (admin) -------------------------------------------------------

@router.post("/invites")
def create_invite(payload: InviteRequest,
                  admin: Optional[User] = Depends(require_admin),
                  db: Session = Depends(get_db)):
    raw, hashed = new_secret()
    db.add(Invite(
        email=payload.email.lower(),
        token_hash=hashed,
        role=payload.role,
        created_by=admin.id if admin else None,
        expires_at=utcnow() + timedelta(days=7),
    ))
    db.commit()
    # The raw token is shown exactly once -- it is not recoverable afterwards.
    return {"invite_token": raw, "email": payload.email, "expires_in_days": 7}


# --- connected accounts ----------------------------------------------------

@router.get("/connections")
def list_connections(user: Optional[User] = Depends(require_user),
                     db: Session = Depends(get_db)):
    if user is None:
        return {"connections": [], "auth_enforced": settings().enforced}

    rows = db.scalars(
        select(SocialConnection).where(SocialConnection.user_id == user.id)
    ).all()

    def _budget_out(c: SocialConnection) -> Optional[dict]:
        """
        Today's pacing consumption, or None.

        Pacing is the main thing standing between a personal account and a
        restriction, and until now its consumption was invisible: the caps in
        scrapers/hygiene.py were enforced silently, so "why did it stop
        collecting?" had no answer anywhere in the interface.
        """
        if c.budget_requests_cap is None:
            return None

        today = datetime.now(timezone.utc).date().isoformat()
        if c.budget_day != today:
            return None  # yesterday's figures; today's budget is untouched

        used = c.budget_requests_used or 0
        cap = c.budget_requests_cap or 0
        return {
            "day": c.budget_day,
            "requests_used": used,
            "requests_cap": cap,
            "posts_used": c.budget_posts_used or 0,
            "posts_cap": c.budget_posts_cap or 0,
            "requests_remaining": max(0, cap - used),
            "fraction_used": round(used / cap, 3) if cap else None,
            "exhausted": cap > 0 and used >= cap,
        }

    def out(c: SocialConnection) -> dict:
        expires = c.session_expires_at
        days_left = None
        if expires:
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            days_left = max(0, (expires - utcnow()).days)
        return {
            "platform": c.platform,
            "handle": c.handle,
            "status": c.status,
            "status_reason": c.status_reason,
            "session_expires_at": c.session_expires_at.isoformat() if c.session_expires_at else None,
            "days_until_expiry": days_left,
            "last_collected_at": c.last_collected_at.isoformat() if c.last_collected_at else None,
            "posts_collected": c.posts_collected,
            "cooldown_until": c.cooldown_until.isoformat() if c.cooldown_until else None,
            # None when the connector has not reported, and a stale day counts
            # as not reported: yesterday's 118/120 shown as today's would send
            # someone looking for a problem that reset hours ago.
            "budget": _budget_out(c),
        }

    return {
        "connections": [out(c) for c in rows],
        "available_platforms": sorted(PLATFORMS),
        # Stated in the API, not only in the UI, so it is impossible to miss.
        "note": (
            "Session cookies are held by your connector on your own machine. "
            "This server stores connection status only, never credentials."
        ),
    }


@router.delete("/connections/{platform}")
def disconnect(platform: str,
               user: Optional[User] = Depends(require_user),
               db: Session = Depends(get_db)):
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    row = db.scalar(select(SocialConnection).where(
        SocialConnection.user_id == user.id, SocialConnection.platform == platform.lower()
    ))
    if row is None:
        raise HTTPException(status_code=404, detail=f"No {platform} connection")
    db.delete(row)
    db.commit()
    return {
        "status": "disconnected",
        "platform": platform,
        "reminder": (
            "Removed from this server. The session itself lives in your "
            "connector -- disconnect it there too, and log out on the platform "
            "if you want the session invalidated."
        ),
    }


@router.post("/connections/{platform}/resume")
def resume_after_challenge(platform: str,
                           user: Optional[User] = Depends(require_user),
                           db: Session = Depends(get_db)):
    """
    Clear a challenge cooldown. Deliberately manual.

    A challenge means the platform decided our behaviour warranted a check.
    Auto-resuming is how a soft block becomes a permanent one, so this requires
    a human who has looked at the account.
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    row = db.scalar(select(SocialConnection).where(
        SocialConnection.user_id == user.id, SocialConnection.platform == platform.lower()
    ))
    if row is None:
        raise HTTPException(status_code=404, detail=f"No {platform} connection")

    row.status = "ok"
    row.status_reason = None
    row.cooldown_until = None
    db.commit()
    return {"status": "resumed", "platform": platform}


# --- connector pairing -----------------------------------------------------

@router.post("/connector/pair")
def start_pairing(user: Optional[User] = Depends(require_user),
                  db: Session = Depends(get_db)):
    """
    Mint a short pairing code, displayed in the web UI (phone or desktop).

    The user types it into the connector on their desktop. The code is
    typeable rather than scannable because the phone showing a QR cannot also
    scan it.
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    code, code_hash = new_pair_code()
    device = ConnectorDevice(
        user_id=user.id,
        pair_code_hash=code_hash,
        pair_expires_at=utcnow() + timedelta(minutes=10),
    )
    db.add(device)
    db.commit()
    return {"pair_code": code, "expires_in_minutes": 10, "device_id": device.id}


@router.post("/connector/claim")
def claim_pairing(pair_code: str = Body(..., embed=True),
                  device_name: str = Body("connector", embed=True),
                  db: Session = Depends(get_db)):
    """
    Called by the connector with the code the user typed.

    Unauthenticated by design -- the code IS the credential, and it is
    short-lived and single-use.
    """
    device = db.scalar(select(ConnectorDevice).where(
        ConnectorDevice.pair_code_hash == hash_secret(pair_code.strip()),
        ConnectorDevice.paired_at.is_(None),
    ))
    if device is None:
        raise HTTPException(status_code=400, detail="Invalid or already-used pairing code")

    expires = device.pair_expires_at
    if expires and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires and expires <= utcnow():
        raise HTTPException(status_code=400, detail="Pairing code has expired")

    raw, hashed = new_secret(48)
    device.token_hash = hashed
    device.pair_code_hash = None          # single use
    device.paired_at = utcnow()
    device.name = device_name
    db.commit()

    return {
        "device_token": raw,          # shown once; the connector stores it locally
        "device_id": device.id,
        "user_id": device.user_id,
    }


@router.get("/connector/devices")
def list_devices(user: Optional[User] = Depends(require_user),
                 db: Session = Depends(get_db)):
    if user is None:
        return {"devices": []}
    rows = db.scalars(select(ConnectorDevice).where(
        ConnectorDevice.user_id == user.id, ConnectorDevice.revoked_at.is_(None)
    )).all()
    return {"devices": [{
        "id": d.id,
        "name": d.name,
        "paired": d.is_paired,
        "paired_at": d.paired_at.isoformat() if d.paired_at else None,
        "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
    } for d in rows]}


@router.delete("/connector/devices/{device_id}")
def revoke_device(device_id: str,
                  user: Optional[User] = Depends(require_user),
                  db: Session = Depends(get_db)):
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    device = db.get(ConnectorDevice, device_id)
    if device is None or device.user_id != user.id:
        raise HTTPException(status_code=404, detail="Unknown device")
    device.revoked_at = utcnow()
    device.token_hash = None
    db.commit()
    return {"status": "revoked", "device_id": device_id}


# --- ingest ----------------------------------------------------------------

@router.post("/ingest")
def ingest(payload: IngestRequest,
           device: ConnectorDevice = Depends(require_device),
           db: Session = Depends(get_db)):
    """
    Receive posts collected by a connector.

    Device-token authenticated always, never gated by AUTH_ENFORCED: this writes
    to the feed, so an unauthenticated variant would be an open write endpoint.
    """
    stored = skipped = 0

    for post in payload.posts:
        if not post.text or not post.text.strip():
            continue
        digest = _content_hash(post.poster, post.text)

        exists = db.scalar(select(IngestedPost.id).where(
            IngestedPost.user_id == device.user_id,
            IngestedPost.content_hash == digest,
        ))
        if exists:
            skipped += 1
            continue

        db.add(IngestedPost(
            user_id=device.user_id,
            platform=post.platform.lower(),
            content_hash=digest,
            poster=post.poster,
            text=post.text,
            url=post.url,
            posted_at=post.posted_at,
            likes=post.likes,
            shares=post.shares,
            comments=post.comments,
        ))
        stored += 1

    if payload.connection_status:
        cs = payload.connection_status
        conn = db.scalar(select(SocialConnection).where(
            SocialConnection.user_id == device.user_id,
            SocialConnection.platform == cs.platform.lower(),
        ))
        if conn is None:
            conn = SocialConnection(user_id=device.user_id, platform=cs.platform.lower())
            db.add(conn)

        conn.handle = cs.handle or conn.handle
        conn.status = cs.status
        conn.status_reason = cs.status_reason
        conn.session_expires_at = cs.session_expires_at or conn.session_expires_at
        conn.last_collected_at = utcnow()
        conn.posts_collected = (conn.posts_collected or 0) + stored

        # Only overwrite when the connector actually reported. Defaulting a
        # missing report to zero would show a nearly-spent budget as untouched.
        if cs.budget is not None:
            conn.budget_day = cs.budget.day
            conn.budget_requests_used = cs.budget.requests_used
            conn.budget_requests_cap = cs.budget.requests_cap
            conn.budget_posts_used = cs.budget.posts_used
            conn.budget_posts_cap = cs.budget.posts_cap

        # A challenge stops that account until a human resumes it.
        if cs.status == "challenged":
            conn.cooldown_until = utcnow() + timedelta(hours=24)
            logger.warning(
                "[ingest] %s challenged for user %s -- collection stopped for 24h",
                cs.platform, device.user_id,
            )

    db.commit()
    return {"status": "ok", "stored": stored, "skipped_duplicates": skipped}


@router.get("/ingest/recent")
def recent_ingested(limit: int = 50,
                    platform: Optional[str] = None,
                    user: Optional[User] = Depends(require_user),
                    db: Session = Depends(get_db)):
    """Posts collected by this user's connector."""
    if user is None:
        return {"posts": [], "count": 0}

    q = select(IngestedPost).where(IngestedPost.user_id == user.id)
    if platform:
        q = q.where(IngestedPost.platform == platform.lower())
    rows = db.scalars(
        q.order_by(IngestedPost.collected_at.desc()).limit(min(limit, 200))
    ).all()

    return {
        "count": len(rows),
        "posts": [{
            "platform": p.platform,
            "poster": p.poster,
            "text": p.text,
            "url": p.url,
            "posted_at": p.posted_at,
            "likes": p.likes,
            "shares": p.shares,
            "comments": p.comments,
            "collected_at": p.collected_at.isoformat() if p.collected_at else None,
            # The pictures, and anything read out of them. Stored since the
            # image pipeline landed and exposed nowhere, so the panel could not
            # show why an apparently empty post had been kept -- which on an
            # image-only post is the entire content.
            "images": [{
                "url": i.url,
                "ocr_text": i.ocr_text,
                "ocr_lang": i.ocr_lang,
                # Surfaced rather than hidden: these are natural-scene
                # photographs, not scans, and a weak read should be marked as
                # one instead of presented as text that was definitely there.
                "ocr_confidence": (
                    round(i.ocr_confidence, 3) if i.ocr_confidence is not None else None
                ),
            } for i in (p.images or [])],
        } for p in rows],
    }
