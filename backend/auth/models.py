"""
auth/models.py
Identity schema.

Deliberately does NOT store social session cookies. Collection runs in the
user's connector on their own machine, so the server never receives one. What is
stored per connected account is metadata only: which platform, which handle,
when the session expires, when it was last seen working. That is enough to drive
the UI and to tell a user to reconnect, and it means a database compromise
yields no account access.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="member")  # member|admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Bumped to invalidate every outstanding access token for this user at once
    # (password change, forced logout). Access tokens carry it as `ver`.
    token_version: Mapped[int] = mapped_column(Integer, default=0)

    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    connections: Mapped[list["SocialConnection"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class RefreshToken(Base):
    """
    Opaque refresh token, stored as a SHA-256 hash.

    Rotated on every use. `family_id` groups a rotation chain so that replaying
    a token already spent can revoke the entire chain -- the standard mitigation
    for a token that must live in client storage.
    """
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    family_id: Mapped[str] = mapped_column(String(32), index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="refresh_tokens")

    @property
    def is_usable(self) -> bool:
        if self.revoked_at is not None or self.used_at is not None:
            return False
        expires = self.expires_at
        if expires.tzinfo is None:              # SQLite drops tzinfo on read
            expires = expires.replace(tzinfo=timezone.utc)
        return expires > utcnow()


class Invite(Base):
    """Invite-only registration. No open signup for a single-org BI tool."""
    __tablename__ = "invites"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(20), default="member")
    created_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def is_usable(self) -> bool:
        if self.used_at is not None:
            return False
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return expires > utcnow()


class SocialConnection(Base):
    """
    Metadata about a connected account. **No cookies.**

    The session itself lives in the user's connector. The server keeps only what
    it needs to render status and prompt a reconnect.
    """
    __tablename__ = "social_connections"
    __table_args__ = (
        UniqueConstraint("user_id", "platform", name="uq_user_platform"),
        Index("ix_conn_user_platform", "user_id", "platform"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(20))
    handle: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # ok | expired | challenged | disconnected
    status: Mapped[str] = mapped_column(String(20), default="ok")
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    session_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    posts_collected: Mapped[int] = mapped_column(Integer, default=0)

    # Set when a platform challenges us. Collection stays stopped until the user
    # explicitly resumes -- never auto-resumed.
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Today's collection budget, as last reported by the connector.
    #
    # The caps in scrapers/hygiene.py (120/60/40 requests per platform per day)
    # have always been enforced and never shown. A user approaching one saw
    # collection quietly return less, then stop, with the reason visible only in
    # a local log. Pacing is the main thing standing between a personal account
    # and a restriction, so how much of it has been spent is exactly what the
    # person whose account it is should be able to see.
    #
    # Nullable and advisory: the authoritative counter lives in the connector
    # process. This is a mirror for display, not a control.
    budget_day: Mapped[str | None] = mapped_column(String(10), nullable=True)
    budget_requests_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budget_requests_cap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budget_posts_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budget_posts_cap: Mapped[int | None] = mapped_column(Integer, nullable=True)

    user: Mapped[User] = relationship(back_populates="connections")


class ConnectorDevice(Base):
    """
    A connector installation paired to a user.

    Pairing: the web UI mints a short code, the user types it into the connector
    on their desktop, and the connector exchanges it for a long-lived device
    token. Only the token hash is stored.
    """
    __tablename__ = "connector_devices"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), default="connector")
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)

    pair_code_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    pair_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def is_paired(self) -> bool:
        return self.token_hash is not None and self.revoked_at is None


class IngestedPost(Base):
    """
    A post pushed up by a connector.

    content_hash mirrors db_manager.generate_content_hash so dedup is consistent
    with the existing pipeline.
    """
    __tablename__ = "ingested_posts"
    __table_args__ = (
        UniqueConstraint("user_id", "content_hash", name="uq_user_content"),
        Index("ix_posts_user_time", "user_id", "collected_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(20), index=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)

    poster: Mapped[str | None] = mapped_column(String(200), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    posted_at: Mapped[str | None] = mapped_column(String(64), nullable=True)

    likes: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)

    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    images: Mapped[list["PostImage"]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )


class PostImage(Base):
    """
    One image attached to a collected post.

    A separate table rather than columns on IngestedPost because a post can
    carry several images -- an Instagram carousel routinely has ten -- and
    because the interesting fields (perceptual hash, extracted text, embedding)
    belong to the image, not the post.

    `phash` is the near-duplicate key. It is indexed and deliberately not
    unique: the same photograph legitimately appears in several posts, and that
    recurrence is the signal image search exists to surface -- a flood
    photograph from 2017 being reposted as today's news.
    """

    __tablename__ = "post_images"
    __table_args__ = (
        Index("ix_post_images_phash", "phash"),
        Index("ix_post_images_post", "post_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    post_id: Mapped[str] = mapped_column(
        ForeignKey("ingested_posts.id", ondelete="CASCADE"), index=True
    )

    url: Mapped[str] = mapped_column(Text)
    # Absent until the download succeeds. Nullable so a post is never blocked
    # on fetching its pictures.
    local_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    phash: Mapped[str | None] = mapped_column(String(32), nullable=True)

    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_lang: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 0-1. Stored so the UI can mark a weak read rather than presenting it as
    # text that was definitely there -- these are natural-scene photographs,
    # not scanned documents, and Sinhala accuracy in particular is poor.
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    post: Mapped["IngestedPost"] = relationship(back_populates="images")
