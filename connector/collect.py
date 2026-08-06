"""
connector/collect.py
Run collection locally and push results to the server.

This is the half of the design that lowers ban risk. Requests originate from the
user's own residential IP, carrying a session created on that same IP -- rather
than from a datacenter, which is one of the strongest bot signals there is and
which no amount of browser-flag tuning addresses.

Scraping itself is the consolidated implementation in backend/src/scrapers, so
the connector and the server share exactly one copy of the logic.
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from src.scrapers import registry  # noqa: E402
from src.scrapers.credentials import SocialCredential, derive_expiry  # noqa: E402

from .backoff import BackoffStore  # noqa: E402
from .storage import DeviceConfig, SessionStore  # noqa: E402

logger = logging.getLogger("connector.collect")

# Search scrapers only. Profile scrapers need a target, which comes from the
# server's intel config.
DEFAULT_SCRAPERS = {
    "twitter": "scrape_twitter",
    "linkedin": "scrape_linkedin",
    "facebook": "scrape_facebook",
    "instagram": "scrape_instagram",
}

# Used when the dashboard asks for a one-off collect and supplies no query of
# its own. Kept broad on purpose -- a targeted query belongs in the intel
# config, not in a button.
DEFAULT_QUERY = "Sri Lanka"

# How often to check for dashboard instructions, independent of the collect
# interval. The 15-minute collect cadence exists to protect the ACCOUNT;
# applying it to a button press protects nothing and just makes Connect feel
# broken, so commands are polled on a short cycle in between collections.
COMMAND_POLL_SECONDS = 20.0


class Collector:
    def __init__(self, store: Optional[SessionStore] = None,
                 config: Optional[DeviceConfig] = None,
                 backoff: Optional["BackoffStore"] = None):
        self.store = store or SessionStore()
        self.config = config or DeviceConfig()
        self.backoff = backoff or BackoffStore()

    # -- credentials ------------------------------------------------------

    def credential_for(self, platform: str) -> Optional[SocialCredential]:
        record = self.store.load(platform)
        if record is None:
            return None
        state = record.get("storage_state") or {}
        device = self.config.load()
        return SocialCredential(
            platform=platform,
            storage_state=state,
            handle=record.get("handle"),
            account_key=f"{device.get('user_id', 'local')}:{platform}",
            expires_at=derive_expiry(state, platform),
            source="connector",
        )

    def connected(self) -> List[str]:
        return self.store.available()

    @staticmethod
    def _budget_for(platform: str, account_key: str) -> Optional[dict]:
        """
        Today's budget consumption for this account, or None if unavailable.

        Never allowed to break a push: reporting how much budget is left is
        strictly less important than delivering the posts that were collected.
        """
        try:
            from src.scrapers.base import budget_snapshot

            snapshot = budget_snapshot(account_key, platform)
            return {
                "day": snapshot["day"],
                "requests_used": snapshot["requests_used"],
                "requests_cap": snapshot["requests_cap"],
                "posts_used": snapshot["posts_used"],
                "posts_cap": snapshot["posts_cap"],
            }
        except Exception as exc:  # noqa: BLE001
            logger.debug("[collect] no budget snapshot for %s: %s", platform, exc)
            return None

    # -- server -----------------------------------------------------------

    def _push(self, posts: List[dict], status: dict) -> dict:
        import requests

        device = self.config.load()
        url = device.get("server_url", "").rstrip("/")
        token = device.get("device_token")
        if not url or not token:
            raise RuntimeError("Connector is not paired. Run: connector pair <code>")

        response = requests.post(
            f"{url}/api/ingest",
            headers={"Authorization": f"Bearer {token}"},
            json={"posts": posts, "connection_status": status},
            timeout=60,
        )
        if response.status_code == 401:
            raise RuntimeError(
                "The server rejected this device token. It may have been revoked "
                "in Settings -> Devices. Re-pair the connector."
            )
        response.raise_for_status()
        return response.json()

    # -- collection -------------------------------------------------------

    def collect_platform(self, platform: str, query: str, max_items: int = 20) -> dict:
        """
        Collect one platform and push the result.

        Status is reported even when nothing is collected -- especially then.
        A challenge or an expiry is exactly what the user needs to see, and
        staying silent about it is how a flagged account goes unnoticed.
        """
        scraper = DEFAULT_SCRAPERS.get(platform)
        if scraper is None:
            return {"platform": platform, "status": "unsupported"}

        # A challenge stops this account until a human resumes it, and a run of
        # failures backs off exponentially. Both survive a restart, which is the
        # whole point -- restarting is exactly what people do after failures,
        # and an in-memory counter would reset right when it matters.
        if self.backoff.is_challenged(platform):
            return {"platform": platform, "status": "challenged",
                    "detail": self.backoff.describe(platform)}
        if not self.backoff.ready(platform):
            return {"platform": platform, "status": "backing_off",
                    "detail": self.backoff.describe(platform)}

        credential = self.credential_for(platform)
        if credential is None:
            return {"platform": platform, "status": "not_connected"}

        if credential.is_expired:
            self._push([], {
                "platform": platform, "handle": credential.handle,
                "status": "expired",
                "status_reason": "The stored session has passed its expiry date.",
            })
            return {"platform": platform, "status": "expired"}

        from src.scrapers.base import run_scrape
        spec = registry.REGISTRY[scraper]
        result = run_scrape(credential, spec.fn, query, max_items=max_items)

        # Write refreshed cookies back to local storage.
        #
        # Platforms rotate values like ct0, lidc and sessionid during ordinary
        # use. Discarding them -- which is what the original code did, since it
        # never read the session back after a run -- makes a stored session
        # drift stale until it stops working, and the user experiences that as
        # "it randomly logs me out every few weeks".
        #
        # Skipped on a challenge: whatever the platform handed back mid-challenge
        # is not a session we want to keep.
        if result.rotated_state and result.status != "challenged":
            try:
                self.store.save(platform, result.rotated_state, handle=credential.handle)
            except Exception as exc:
                # Never let a persistence failure lose the posts we just collected.
                logger.warning("[collect] could not persist rotated %s session: %s",
                               platform, exc)

        posts = [{
            "platform": platform,
            "poster": p.get("poster"),
            "text": p.get("text", ""),
            "url": p.get("url"),
            "posted_at": p.get("timestamp"),
            "likes": int(p.get("likes") or 0),
            "shares": int(p.get("retweets") or p.get("shares") or 0),
            "comments": int(p.get("replies") or p.get("comments") or 0),
        } for p in result.posts]

        status = {
            "platform": platform,
            "handle": credential.handle,
            "status": {"ok": "ok", "expired": "expired", "challenged": "challenged"}
                      .get(result.status, "ok"),
            "status_reason": result.reason,
            "session_expires_at": (credential.expires_at.isoformat()
                                   if credential.expires_at else None),
            # How much of today's pacing budget this account has spent.
            #
            # The caps exist to protect the account and were enforced silently,
            # so approaching one looked like collection quietly returning less
            # and then stopping. The counter lives here, in this process -- the
            # server only mirrors it for display.
            "budget": self._budget_for(platform, credential.account_key),
        }

        pushed = self._push(posts, status)

        if result.status == "challenged":
            self.backoff.record_challenge(platform, result.reason)
        elif result.status in ("ok", "budget_exhausted"):
            self.backoff.record_success(platform)
        else:
            # expired counts as a failure for pacing: retrying a dead session
            # every 15 minutes is pointless traffic against an account the
            # platform is already watching.
            self.backoff.record_failure(platform, result.reason)

        if result.status == "challenged":
            logger.error(
                "[collect] %s served a challenge. Collection for this account is "
                "stopped; resume it in the dashboard once you have checked the "
                "account. It will NOT retry on its own.", platform,
            )

        return {
            "platform": platform,
            "status": result.status,
            "collected": len(posts),
            "stored": pushed.get("stored", 0),
            "duplicates": pushed.get("skipped_duplicates", 0),
        }

    def collect_all(self, query: str, max_items: int = 20) -> List[dict]:
        results = []
        for platform in self.connected():
            if platform not in DEFAULT_SCRAPERS:
                continue
            try:
                results.append(self.collect_platform(platform, query, max_items))
            except Exception as exc:
                logger.exception("[collect] %s failed", platform)
                results.append({"platform": platform, "status": "error", "error": str(exc)})
        return results


    # -- commands from the dashboard ---------------------------------------

    def _server(self):
        """(url, token) for this paired connector, or (None, None)."""
        device = self.config.load()
        url = (device.get("server_url") or "").rstrip("/")
        token = device.get("device_token")
        return (url or None), token

    def claim_commands(self) -> List[dict]:
        """
        Ask the server what the dashboard wants done.

        Polled on the collect loop, so it doubles as the liveness ping the
        dashboard reads to decide whether to say "your connector will do this
        shortly" or "no connector is running".
        """
        import requests

        url, token = self._server()
        if not url or not token:
            return []

        try:
            response = requests.get(
                f"{url}/api/connector/commands/pending",
                headers={"Authorization": f"Bearer {token}"},
                timeout=20,
            )
            if response.status_code == 404:
                # An older server without the command queue. Not an error --
                # collection still works, the dashboard buttons just do nothing.
                return []
            response.raise_for_status()
            return response.json().get("commands", [])
        except Exception as exc:
            logger.warning("[commands] could not poll: %s", exc)
            return []

    def _report(self, command_id: str, ok: bool, result: str) -> None:
        import requests

        url, token = self._server()
        if not url or not token:
            return
        try:
            requests.post(
                f"{url}/api/connector/commands/{command_id}/result",
                headers={"Authorization": f"Bearer {token}"},
                json={"ok": ok, "result": result[:2000]},
                timeout=20,
            )
        except Exception as exc:
            logger.warning("[commands] could not report %s: %s", command_id, exc)

    def run_command(self, command: dict) -> None:
        """
        Execute one dashboard instruction, here on this machine.

        Credentials come from the LOCAL vault, never from the command -- the
        server has no idea what they are. The command carries a verb and a
        platform name and nothing else.
        """
        action = command.get("action")
        platform = command.get("platform", "")
        command_id = command.get("id")

        logger.info("[commands] %s %s (from the dashboard)", action, platform)

        try:
            if action == "connect":
                from .connect import connect_via_login
                from .vault import CredentialVault

                prefill = None
                try:
                    prefill = CredentialVault().get(platform)
                except Exception:
                    pass

                summary = connect_via_login(platform, prefill=prefill)
                self._report(
                    command_id, True,
                    f"Connected{' as ' + summary['handle'] if summary.get('handle') else ''}.",
                )

            elif action == "disconnect":
                from .connect import disconnect

                removed = disconnect(platform)
                self._report(
                    command_id, bool(removed),
                    "Disconnected." if removed else "Nothing was connected.",
                )

            elif action == "collect":
                outcome = self.collect_platform(platform, DEFAULT_QUERY, 20)
                self._report(command_id, True, str(outcome)[:500])

            else:
                self._report(command_id, False, f"Unknown action {action!r}")

        except Exception as exc:
            logger.exception("[commands] %s %s failed", action, platform)
            self._report(command_id, False, str(exc)[:500])

    def run_forever(self, query: str, interval_seconds: int = 900,
                    max_items: int = 20) -> None:
        """
        Collect on a loop.

        15 minutes by default, not the server's 60 seconds. The server loop was
        tuned for public sources with no account attached; hitting a logged-in
        account that often is the behaviour that earns a challenge.
        """
        logger.info("[collect] starting; every %ds for %s",
                    interval_seconds, self.connected() or "no connected accounts")
        while True:
            started = time.monotonic()

            # Dashboard instructions first: a user who just clicked Connect is
            # waiting on it, and a collect pass can take minutes.
            for command in self.claim_commands():
                self.run_command(command)

            for outcome in self.collect_all(query, max_items):
                logger.info("[collect] %s", outcome)

            elapsed = time.monotonic() - started

            # Poll for commands far more often than the collect interval. The
            # 15-minute cadence protects the ACCOUNT; making a button wait 15
            # minutes protects nothing, so the sleep is broken into short naps
            # that keep claiming commands in between.
            remaining = max(30.0, interval_seconds - elapsed)
            while remaining > 0:
                nap = min(COMMAND_POLL_SECONDS, remaining)
                time.sleep(nap)
                remaining -= nap
                if remaining > 0:
                    for command in self.claim_commands():
                        self.run_command(command)
