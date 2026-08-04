"""
src/scrapers/credentials.py
The single seam through which a scraper obtains a social session.

This replaces the previous arrangement: 14 near-identical copies of a filesystem
probe, spread across utils.py, tool_factory.py and profile_scrapers.py, using
two different naming conventions -- one of which (``tw_state.json``,
``fb_state.json``, ``ig_state.json``, ``li_state.json``, 26 probe sites) was
never written by anything in the repo and could not ever have resolved.

Direction of travel: credentials live on the *user's* machine, held by the
connector, and the server stores none at all. ``FileCredentialStore`` exists so
local development and the connector itself keep working; the server will use a
store that simply has nothing to hand out.

The decrypted storage_state is only ever a dict in memory. Playwright's
``new_context(storage_state=...)`` accepts a dict as well as a path (verified
against the installed version), so cookies never need to touch disk.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Protocol

logger = logging.getLogger("Roger.scrapers.credentials")

PLATFORMS = ("twitter", "facebook", "instagram", "linkedin", "reddit")

# First-party cookie domains per platform. Everything else in a captured
# storage_state is third-party tracking (doubleclick, demdex, rlcdn) that we
# have no reason to store or replay.
FIRST_PARTY_DOMAINS: Dict[str, tuple] = {
    "twitter": (".x.com", "x.com", ".twitter.com", "twitter.com"),
    "facebook": (".facebook.com", "facebook.com", ".web.facebook.com"),
    "instagram": (".instagram.com", "instagram.com"),
    "linkedin": (".linkedin.com", "linkedin.com", ".www.linkedin.com"),
    "reddit": (".reddit.com", "reddit.com", "old.reddit.com"),
}

# Cookies without which the session is not usable. Used to decide whether a
# capture actually succeeded, and to derive a truthful expiry.
REQUIRED_COOKIES: Dict[str, tuple] = {
    # ct0 is NOT optional: X validates it against the x-csrf-token header on
    # every authenticated XHR. Dropping it fails silently and presents as an
    # unexplained session expiry.
    "twitter": ("auth_token", "ct0"),
    "facebook": ("c_user", "xs"),
    "instagram": ("sessionid",),
    "linkedin": ("li_at", "JSESSIONID"),
    "reddit": ("reddit_session",),
}


class CredentialError(Exception):
    pass


@dataclass(frozen=True)
class SocialCredential:
    platform: str
    storage_state: dict          # decrypted; MEMORY ONLY, never logged or serialised
    handle: Optional[str] = None
    account_key: Optional[str] = None   # rate-limiter key, e.g. "<user>:twitter"
    expires_at: Optional[datetime] = None
    source: str = "unknown"

    def __repr__(self) -> str:  # pragma: no cover - defensive
        # Never let cookies reach a log line or a traceback.
        return (
            f"SocialCredential(platform={self.platform!r}, handle={self.handle!r}, "
            f"cookies=<{len(self.storage_state.get('cookies', []))} redacted>)"
        )

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return self.expires_at <= datetime.now(timezone.utc)


class CredentialStore(Protocol):
    """Where a scraper gets its session from."""

    def get(self, platform: str) -> Optional[SocialCredential]: ...
    def put(self, platform: str, storage_state: dict, handle: Optional[str] = None) -> None: ...
    def available(self) -> List[str]: ...


# --- helpers ---------------------------------------------------------------

def filter_first_party(storage_state: dict, platform: str) -> dict:
    """
    Drop everything that is not the platform's own cookie.

    Keeps the payload minimal, and means a captured session cannot carry an
    unrelated site's credentials along with it.
    """
    domains = FIRST_PARTY_DOMAINS.get(platform.lower(), ())
    if not domains:
        return storage_state

    def keep_cookie(c: dict) -> bool:
        d = (c.get("domain") or "").lower()
        return any(d == dom or d.endswith(dom) for dom in domains)

    def keep_origin(o: dict) -> bool:
        origin = (o.get("origin") or "").lower()
        return any(dom.lstrip(".") in origin for dom in domains)

    return {
        "cookies": [c for c in storage_state.get("cookies", []) if keep_cookie(c)],
        "origins": [o for o in storage_state.get("origins", []) if keep_origin(o)],
    }


def missing_required(storage_state: dict, platform: str) -> List[str]:
    """Required cookies absent from this state. Empty means usable."""
    required = REQUIRED_COOKIES.get(platform.lower(), ())
    names = {c.get("name") for c in storage_state.get("cookies", [])}
    return [r for r in required if r not in names]


def derive_expiry(storage_state: dict, platform: str) -> Optional[datetime]:
    """
    Earliest expiry among the *required* cookies -- the real ceiling on the
    session's life.

    This matters: for LinkedIn the binding constraint is JSESSIONID at roughly
    three months, not li_at at twelve. Reporting li_at's expiry would promise
    the user four times the life they actually have.
    """
    required = set(REQUIRED_COOKIES.get(platform.lower(), ()))
    if not required:
        return None

    expiries = []
    for c in storage_state.get("cookies", []):
        if c.get("name") not in required:
            continue
        exp = c.get("expires")
        # -1 (or absent) means a session cookie: no expiry to report.
        if exp is None or exp <= 0:
            continue
        expiries.append(exp)

    if not expiries:
        return None
    return datetime.fromtimestamp(min(expiries), tz=timezone.utc)


def validate(storage_state: dict, platform: str) -> None:
    """Raise CredentialError if this cannot possibly work."""
    if not isinstance(storage_state, dict):
        raise CredentialError("storage_state must be a JSON object")
    if "cookies" not in storage_state:
        raise CredentialError("storage_state has no 'cookies' key")
    if not isinstance(storage_state.get("cookies"), list):
        raise CredentialError("storage_state['cookies'] must be a list")

    missing = missing_required(storage_state, platform)
    if missing:
        raise CredentialError(
            f"{platform}: missing required cookie(s) {missing}. "
            "The capture did not include a signed-in session."
        )


# --- stores ----------------------------------------------------------------

class NullCredentialStore:
    """
    Hands out nothing.

    This is the correct store for the deployed server: collection happens in the
    user's connector, so the server holds no social credentials at all.
    """

    def get(self, platform: str) -> Optional[SocialCredential]:
        return None

    def put(self, platform: str, storage_state: dict, handle: Optional[str] = None) -> None:
        raise CredentialError(
            "This deployment does not store social credentials. "
            "Sessions live in the user's connector."
        )

    def available(self) -> List[str]:
        return []


class FileCredentialStore:
    """
    Reads ``<platform>_storage_state.json`` from a directory.

    For the connector (which owns the user's sessions on their own machine) and
    for local development. Not used by the server.

    Unlike the code this replaces, the directory is explicit -- no cwd-dependent
    probe ladder, no silent fallbacks.
    """

    def __init__(self, directory: os.PathLike | str):
        self.directory = Path(directory)

    def _path(self, platform: str) -> Path:
        return self.directory / f"{platform.lower()}_storage_state.json"

    def get(self, platform: str) -> Optional[SocialCredential]:
        path = self._path(platform)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("[credentials] %s: unreadable session file: %s", platform, exc)
            return None

        state = filter_first_party(raw, platform)
        missing = missing_required(state, platform)
        if missing:
            logger.warning(
                "[credentials] %s: session file is missing %s -- treating as absent",
                platform, missing,
            )
            return None

        return SocialCredential(
            platform=platform.lower(),
            storage_state=state,
            expires_at=derive_expiry(state, platform),
            account_key=f"file:{platform.lower()}",
            source=str(path),
        )

    def put(self, platform: str, storage_state: dict, handle: Optional[str] = None) -> None:
        validate(storage_state, platform)
        state = filter_first_party(storage_state, platform)
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(platform)
        path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        try:
            os.chmod(path, 0o600)   # best effort; no-op semantics on Windows
        except OSError:
            pass

    def available(self) -> List[str]:
        return [p for p in PLATFORMS if self._path(p).exists()]


# --- module-level resolver -------------------------------------------------

_store: Optional[CredentialStore] = None


def set_credential_store(store: CredentialStore) -> None:
    global _store
    _store = store


def get_credential_store() -> CredentialStore:
    """
    Default is NullCredentialStore: the server holds no credentials.

    ALLOW_FILE_SESSIONS=1 opts into the file-backed store for local development
    and for the connector. It is off by default so a server can never silently
    start reading cookies off its own disk.
    """
    global _store
    if _store is None:
        if os.getenv("ALLOW_FILE_SESSIONS", "").lower() in ("1", "true", "yes"):
            directory = os.getenv(
                "SESSIONS_DIR",
                str(Path(__file__).resolve().parent.parent / "utils" / ".sessions"),
            )
            logger.warning(
                "[credentials] file-backed sessions enabled (ALLOW_FILE_SESSIONS) at %s",
                directory,
            )
            _store = FileCredentialStore(directory)
        else:
            _store = NullCredentialStore()
    return _store


def get_credential(platform: str) -> Optional[SocialCredential]:
    """The one call every scraper makes."""
    return get_credential_store().get(platform)
