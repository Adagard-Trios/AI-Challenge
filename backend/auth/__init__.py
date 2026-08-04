"""
backend/auth
Multi-user identity, connector pairing, and post ingest.

What this package deliberately does NOT do: store social session cookies.
Collection runs in the user's connector on their own machine, so the server
never receives one. Per connected account it keeps metadata only -- platform,
handle, expiry, last-collected -- which is enough to drive the UI and to prompt
a reconnect, and means a database compromise yields no account access.

Wiring into main.py is three lines:

    from auth import bootstrap, routes
    bootstrap.init()
    app.include_router(routes.router)

plus `Depends(require_user)` on routes that should be gated. AUTH_ENFORCED=0
(the default) keeps every existing route working while the frontend migrates.
"""

from .config import AuthConfigError, AuthSettings, reset_settings, settings
from .db import get_db, init_db, reset_engine, session_scope
from .dependencies import optional_user, require_admin, require_device, require_user
from .models import (
    Base, ConnectorDevice, IngestedPost, Invite, RefreshToken, SocialConnection, User,
)
from .passwords import WeakPassword, hash_password, verify_password
from .tokens import (
    TokenError, TokenExpired, TokenReplayed, TokenPair,
    create_access_token, decode_access_token, issue_pair,
    revoke_all_for_user, revoke_family, rotate_refresh_token,
)

__all__ = [
    "AuthConfigError", "AuthSettings", "settings", "reset_settings",
    "get_db", "init_db", "session_scope", "reset_engine",
    "optional_user", "require_admin", "require_device", "require_user",
    "Base", "ConnectorDevice", "IngestedPost", "Invite", "RefreshToken",
    "SocialConnection", "User",
    "hash_password", "verify_password", "WeakPassword",
    "TokenError", "TokenExpired", "TokenReplayed", "TokenPair",
    "create_access_token", "decode_access_token", "issue_pair",
    "rotate_refresh_token", "revoke_family", "revoke_all_for_user",
]
