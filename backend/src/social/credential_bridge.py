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
import threading
import time
from typing import Dict, List, Optional

logger = logging.getLogger("Roger.social.credentials")

# Minimum gap between two collections of the SAME account, in seconds.
#
# The agent loop runs every 60 seconds. That cadence was chosen for public
# sources with no account attached, and it is far too fast for a logged-in one:
# the connector deliberately used 15 minutes and said why -- "hitting a
# logged-in account that often is the behaviour that earns a challenge".
#
# Folding collection into the backend silently inherited the 60s loop, which
# would have meant touching a personal account 60 times an hour in a perfectly
# periodic pattern. The daily budget would eventually stop it, but only after
# roughly two hours of behaviour no human produces -- and exhausting a cap is a
# worse signal than never approaching one.
#
# Jittered, because a request exactly every 900 seconds is its own tell.
MIN_COLLECTION_INTERVAL = float(os.getenv("SOCIAL_MIN_INTERVAL_SECONDS", "900"))
INTERVAL_JITTER = 0.25


def _next_allowed(base: float) -> float:
    import random

    return base * random.uniform(1.0, 1.0 + INTERVAL_JITTER)


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
        self._last_served: Dict[str, float] = {}
        self._gate = threading.Lock()

    # --- shared pacing ------------------------------------------------------
    #
    # The in-process gate below is correct for exactly one process. Two
    # replicas each keep their own _last_served dict, so an account gated to
    # one collection per 15 minutes gets two -- and N replicas get N. The whole
    # purpose of this gate is that a personal account should not look like a
    # bot, so multiplying it is the one failure here with a lasting
    # consequence.
    #
    # When REDIS_URL is set, the deadline moves to a Redis key with a TTL:
    #
    #     SET roger:pace:{platform} <token> NX PX <interval_ms>
    #
    # atomic in one round trip, so the check-then-set race across replicas
    # cannot happen. Note this could NOT be done by storing the existing
    # value: time.monotonic() is process-relative, its zero point differs per
    # process, and comparing one process's monotonic clock against another's is
    # meaningless. Redis owning the expiry is what makes it comparable at all.

    def _pace_key(self, platform: str) -> str:
        return f"roger:pace:{platform}"

    def _shared(self):
        """The Redis client, or None when shared pacing is not in play."""
        from src.runtime.redis_client import configured, get_client

        if not configured():
            return None
        return get_client()

    def is_paced(self, platform: str) -> bool:
        """
        Whether this account is inside its cooling-off window, WITHOUT
        consuming it.

        Exists so callers can tell "paced" from "not connected". Both used to
        surface as a None credential, and registry.run reported every None as
        "No account connected. Connect one in Settings" -- which is false when
        an account is connected and merely waiting, tells the user to fix
        something that is not broken, and tells the agent there is no account
        to collect from. On a 60-second loop against a 15-minute gate that was
        the answer 14 times out of 15.

        FAILS CLOSED. If REDIS_URL is configured but Redis cannot be reached,
        this returns True -- paced -- and nothing collects. Losing an hour of
        posts costs nothing and is recoverable; failing open means every
        replica collects at once, unpaced, against one account, which is not.
        """
        if MIN_COLLECTION_INTERVAL <= 0:
            return False

        from src.runtime.redis_client import configured

        if configured():
            client = self._shared()
            if client is None:
                logger.warning(
                    "[credentials] Redis is configured but unreachable; "
                    "treating %s as paced. Collection is suspended rather "
                    "than run without a shared gate.", platform,
                )
                return True
            try:
                return bool(client.exists(self._pace_key(platform)))
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[credentials] could not read the shared pacing gate "
                    "(%s); treating %s as paced", exc, platform,
                )
                return True

        with self._gate:
            due = self._last_served.get(platform)
            return due is not None and time.monotonic() < due

    def seconds_until_ready(self, platform: str) -> int:
        from src.runtime.redis_client import configured

        if configured():
            client = self._shared()
            if client is None:
                # Unknown, and the honest answer is "not yet". Reporting 0
                # would tell the dashboard to retry immediately.
                return int(MIN_COLLECTION_INTERVAL)
            try:
                ttl_ms = client.pttl(self._pace_key(platform))
                # -2 = no key, -1 = key with no expiry. Neither is a wait.
                return max(0, int(ttl_ms // 1000)) if ttl_ms and ttl_ms > 0 else 0
            except Exception:  # noqa: BLE001
                return int(MIN_COLLECTION_INTERVAL)

        with self._gate:
            due = self._last_served.get(platform)
            if due is None:
                return 0
            return max(0, int(due - time.monotonic()))

    def _too_soon(self, platform: str) -> bool:
        """
        True when this account was collected too recently.

        Enforced here rather than in the agent loop because this is the one
        place every scraper passes through -- the loop, the dashboard's
        "Collect now", and the selftest all call get_credential(). A gate in
        the loop would leave the other two unpaced.

        Consumes the slot when it allows one through, which is why is_paced()
        exists separately for callers that only want to ask.

        Across replicas this is one SET NX PX: the winner creates the key, and
        everyone else sees it already exists. Check-then-set as two operations
        would let two replicas both read "free" and both collect.
        """
        if MIN_COLLECTION_INTERVAL <= 0:
            return False

        from src.runtime.redis_client import configured

        if configured():
            client = self._shared()
            if client is None:
                # Same reasoning as is_paced: no shared gate means no
                # collection, not unpaced collection.
                logger.warning(
                    "[credentials] Redis unreachable; refusing to serve %s "
                    "rather than collect without a shared gate", platform,
                )
                return True
            try:
                interval_ms = int(_next_allowed(MIN_COLLECTION_INTERVAL) * 1000)
                acquired = client.set(
                    self._pace_key(platform), "1", nx=True, px=interval_ms
                )
                # set(nx=True) returns True on success and None when the key
                # already exists.
                return not bool(acquired)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[credentials] could not take the shared pacing slot "
                    "(%s); refusing %s", exc, platform,
                )
                return True

        now = time.monotonic()
        with self._gate:
            due = self._last_served.get(platform)
            if due is not None and now < due:
                return True
            self._last_served[platform] = now + _next_allowed(MIN_COLLECTION_INTERVAL)
            return False

    @property
    def store(self):
        if self._store is None:
            from .storage import SessionStore

            self._store = SessionStore()
        return self._store

    def get(self, platform: str):
        from src.scrapers.credentials import SocialCredential, derive_expiry

        # Pacing is checked WITHOUT consuming first, then the session is
        # loaded, and only a real credential consumes the slot.
        #
        # The obvious order -- consume, then load -- marked an account as
        # "collected recently" when there was no account at all, so a platform
        # that had never been connected reported itself as cooling off. Pacing
        # protects a session; there is nothing to protect when there is none.
        if self.is_paced(platform):
            # DEBUG rather than WARNING: on a 60s loop this is the normal case
            # roughly fourteen times out of fifteen, and a warning that fires
            # constantly is one nobody reads.
            logger.debug(
                "[credentials] %s collected recently; skipping this cycle "
                "(minimum gap %.0fs)", platform, MIN_COLLECTION_INTERVAL,
            )
            return None

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

        # A real credential is about to be served, so start the clock now.
        # Doing this earlier charged platforms that turned out to have no
        # session at all.
        self._too_soon(platform)

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
