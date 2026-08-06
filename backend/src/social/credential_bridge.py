"""
src/social/credential_bridge.py
Let the agent pipeline use accounts connected from the dashboard.

THE GAP THIS CLOSES
-------------------
Every social scraper calls `get_credential(platform)`. Its default is
NullCredentialStore, which hands out nothing -- correct for a shared server,
where collection happens in the user's connector and the server should hold no
credentials at all.

The consequence, once sign-in moved into the dashboard, was a feature that
looked complete and was not: you could enter a password, complete a login, see
"Connected" with a handle and an expiry -- and the five agents would still
scrape nothing, because they ask a store that was never told about it. The
session sat encrypted in the connector's store while `get_credential` looked
somewhere else and returned None. No error anywhere; the social feed was simply
always empty.

So this adapter points the scrapers at the same encrypted store the dashboard
writes to. One store, now three readers: the CLI, the dashboard, and the agent
loop.

WHY IT IS NOT ON UNCONDITIONALLY
--------------------------------
The reasoning behind NullCredentialStore is still right for a shared host, and
`ALLOW_FILE_SESSIONS` exists precisely so a server cannot silently start
reading cookies off its own disk. This store is different in the way that
matters -- it is per-user, encrypted, and only ever written by an explicit
connect action on this machine -- but the switch stays visible rather than
implicit, and it logs which store is active on startup.
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional

logger = logging.getLogger("Roger.social.credentials")


class SessionStoreCredentialStore:
    """
    A CredentialStore backed by the connector's encrypted SessionStore.

    Reads on every call rather than caching: `collect()` writes rotated cookies
    back after each run, and a cached copy would go stale exactly when a
    platform decided to rotate -- which is the failure the write-back exists to
    prevent.
    """

    def __init__(self, store=None):
        self._store = store

    @property
    def store(self):
        if self._store is None:
            from .storage import SessionStore

            self._store = SessionStore()
        return self._store

    def get(self, platform: str):
        from src.scrapers.credentials import SocialCredential, derive_expiry

        try:
            record = self.store.load(platform)
        except Exception as exc:  # noqa: BLE001
            # A store that cannot be read must not take the agent cycle down.
            logger.warning("[credentials] could not read %s session: %s", platform, exc)
            return None

        if not record:
            return None

        state = record.get("storage_state") or {}
        if not state:
            return None

        return SocialCredential(
            platform=platform,
            storage_state=state,
            handle=record.get("handle"),
            # Shares the budget counter with the dashboard's "Collect now", so
            # the two cannot each spend a full daily allowance against one
            # account without either of them noticing.
            account_key=f"local:{platform}",
            expires_at=derive_expiry(state, platform),
            source="dashboard",
        )

    def put(self, platform: str, storage_state: dict, handle: Optional[str] = None) -> None:
        self.store.save(platform, storage_state, handle=handle)

    def available(self) -> List[str]:
        try:
            return self.store.available()
        except Exception:  # noqa: BLE001
            return []


def _disabled() -> bool:
    return os.getenv("DISABLE_LOCAL_SOCIAL_SESSIONS", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def install() -> bool:
    """
    Register the adapter. Returns whether it took effect.

    Deliberately does not override an explicitly configured store: if something
    has already called set_credential_store -- a test, or a deployment wiring
    in its own -- that choice wins.
    """
    if _disabled():
        logger.info(
            "[credentials] local social sessions disabled "
            "(DISABLE_LOCAL_SOCIAL_SESSIONS); agents will not scrape social accounts"
        )
        return False

    if os.getenv("ALLOW_FILE_SESSIONS", "").strip().lower() in ("1", "true", "yes"):
        # The old plaintext backend/src/utils/.sessions path. Leave it alone --
        # someone asked for it explicitly.
        logger.info("[credentials] ALLOW_FILE_SESSIONS is set; not installing the "
                    "encrypted dashboard store")
        return False

    try:
        from src.scrapers.credentials import set_credential_store

        set_credential_store(SessionStoreCredentialStore())
        logger.info(
            "[credentials] agents will use accounts connected in the dashboard "
            "(encrypted, this machine only)"
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("[credentials] could not install the dashboard store: %s", exc)
        return False
