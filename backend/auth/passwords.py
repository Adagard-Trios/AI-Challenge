"""
auth/passwords.py
Password hashing. bcrypt directly -- deliberately not passlib.

passlib.hash.bcrypt reads ``bcrypt.__about__.__version__`` at import to detect
the backend. bcrypt removed ``__about__`` in 4.1, and the version installed here
is 5.0.0, so passlib raises on first use. Verified in this venv:

    >>> hasattr(bcrypt, "__about__")
    False

bcrypt also hard-errors above 72 bytes rather than truncating:

    ValueError: password cannot be longer than 72 bytes

Truncating to [:72] would silently make two distinct long passwords equivalent.
Instead the password is pre-hashed to a fixed 44-byte base64 SHA-256 digest, so
any length is accepted and every byte contributes. This is the standard
construction; the base64 step matters because a raw digest can contain a NUL,
which bcrypt treats as a terminator.
"""

from __future__ import annotations

import base64
import hashlib

import bcrypt

MIN_PASSWORD_LENGTH = 10


class WeakPassword(ValueError):
    pass


def _prehash(password: str) -> bytes:
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)          # 44 bytes, no NULs


def hash_password(password: str, *, rounds: int = 12) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPassword(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        )
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt(rounds)).decode("utf-8")


def verify_password(password: str, stored_hash: str) -> bool:
    """Constant-time compare. Never raises on malformed input."""
    if not password or not stored_hash:
        return False
    try:
        return bcrypt.checkpw(_prehash(password), stored_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False
