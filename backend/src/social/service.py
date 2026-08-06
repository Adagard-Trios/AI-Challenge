"""
src/social/service.py
Connect and collect social accounts from the dashboard.

The interesting problem here is that logging in takes a human a minute or two,
and an HTTP request cannot wait that long. The connector CLI solved it with
`input("Press Enter once you are signed in...")`, which is fine in a terminal
and impossible in a web request.

So login runs in a background thread and reports progress through a job record
the dashboard polls. Completion is detected by watching for the platform's
required auth cookies to appear -- `missing_required()` already knows which
those are per platform -- which is strictly better than asking the user to
confirm: it cannot be answered "yes" before the login actually finished, and it
notices the moment it does.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# connector/ is a sibling of backend/, and this module reuses its vault and
# session store on purpose -- same files, so the CLI and the dashboard see the
# same accounts rather than each keeping a private copy.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logger = logging.getLogger("Roger.social")

# Which platforms the search scrapers can collect from with a session.
#
# Deliberately NOT the vault's list, which also includes reddit. Reddit has no
# session scraper -- r/srilanka is read through its public JSON API and needs no
# account -- so offering a reddit login here would let someone save a password,
# complete a browser sign-in, click Collect, and get "unsupported". A dead end
# built out of a list that was copied rather than derived.
COLLECTORS = {
    "twitter": "scrape_twitter",
    "linkedin": "scrape_linkedin",
    "facebook": "scrape_facebook",
    "instagram": "scrape_instagram",
}

SUPPORTED_PLATFORMS = tuple(COLLECTORS)

# How long to leave the login window open before giving up. Long enough for a
# password manager, a 2FA code from a phone, and a mistyped password; short
# enough that a forgotten window does not hold a browser open all day.
LOGIN_TIMEOUT_SECONDS = 300

# How often to check whether the auth cookies have appeared.
LOGIN_POLL_SECONDS = 2.0

DEFAULT_QUERY = "Sri Lanka"


@dataclass
class Job:
    """
    A connect attempt in progress.

    Exists because the dashboard needs to show something during the ~2 minutes
    a human spends logging in, and "the request is still open" is not something
    a browser will tolerate for that long.
    """

    platform: str
    state: str = "starting"        # starting|awaiting_login|saving|done|failed
    message: str = ""
    handle: Optional[str] = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = None

    def as_dict(self) -> dict:
        return {
            "platform": self.platform,
            "state": self.state,
            "message": self.message,
            "handle": self.handle,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "running": self.state in ("starting", "awaiting_login", "saving"),
        }


class SocialService:
    """
    One instance per process. Holds the vault, the session store, and any
    in-flight login.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: Dict[str, Job] = {}
        self._vault = None
        self._sessions = None

    # -- lazily built, so importing this module never touches the keychain ----

    @property
    def vault(self):
        if self._vault is None:
            from connector.vault import CredentialVault

            self._vault = CredentialVault()
        return self._vault

    @property
    def sessions(self):
        if self._sessions is None:
            from connector.storage import SessionStore

            self._sessions = SessionStore()
        return self._sessions

    # -- credentials ---------------------------------------------------------

    def save_credentials(self, platform: str, username: str, password: str) -> None:
        """
        Store a login for pre-filling. Encrypted at rest, never logged.

        Note what this does NOT enable: the password is not used to log in
        unattended. It fills two fields in a real browser and stops.
        """
        platform = platform.lower()
        if platform not in SUPPORTED_PLATFORMS:
            raise ValueError(f"Unsupported platform: {platform}")
        if not username.strip() or not password:
            raise ValueError("Both a username and a password are required")

        self.vault.save(platform, username.strip(), password)
        # Deliberately no password, and no length, in the log line.
        logger.info("[social] stored credentials for %s (this machine only)", platform)

    def forget_credentials(self, platform: str) -> bool:
        return self.vault.forget(platform.lower())

    def saved_usernames(self) -> Dict[str, str]:
        """Usernames only. The vault has no method that returns a password."""
        return self.vault.describe()

    # -- connect -------------------------------------------------------------

    def start_connect(self, platform: str) -> Job:
        """
        Open a browser and begin a login. Returns immediately.

        The browser opens on the machine running THIS PROCESS. When that is the
        user's laptop -- the case this is built for -- it is the machine in
        front of them.
        """
        platform = platform.lower()
        if platform not in SUPPORTED_PLATFORMS:
            raise ValueError(f"Unsupported platform: {platform}")

        with self._lock:
            existing = self._jobs.get(platform)
            if existing and existing.state in ("starting", "awaiting_login", "saving"):
                return existing

            job = Job(platform=platform, state="starting",
                      message="Opening a browser window...")
            self._jobs[platform] = job

        thread = threading.Thread(
            target=self._run_connect, args=(job,),
            name=f"social-connect-{platform}", daemon=True,
        )
        thread.start()
        return job

    def job(self, platform: str) -> Optional[Job]:
        return self._jobs.get(platform.lower())

    def _run_connect(self, job: Job) -> None:
        """
        The whole login, on a background thread.

        Playwright's sync API cannot run inside the asyncio event loop, and this
        blocks for minutes regardless, so a thread is the right shape.
        """
        platform = job.platform
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self._fail(job, "Playwright is not installed on the server. "
                            "pip install playwright && playwright install chromium")
            return

        from connector.connect import (
            LOGIN_URLS, _detect_handle, _launch_browser, _persist, _prefill_login,
        )
        from src.scrapers.credentials import missing_required

        prefill = None
        try:
            prefill = self.vault.get(platform)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[social] could not read saved credentials: %s", exc)

        try:
            with sync_playwright() as p:
                browser = _launch_browser(p, headless=False)
                try:
                    context = browser.new_context()
                    page = context.new_page()
                    page.goto(LOGIN_URLS[platform], wait_until="domcontentloaded")

                    if prefill:
                        # Fills username and password into the platform's own
                        # form and stops. Never submits, never answers a
                        # challenge -- see connector/connect.py.
                        _prefill_login(page, platform, prefill)
                        job.message = ("Signed-in form pre-filled. Finish the login "
                                       "in the browser window, including any 2FA.")
                    else:
                        job.message = ("Sign in normally in the browser window. "
                                       "Save your login below to have it pre-filled "
                                       "next time.")
                    job.state = "awaiting_login"

                    state = self._await_login(context, platform, missing_required, job)
                    if state is None:
                        self._fail(
                            job,
                            "Timed out waiting for the login to complete. Nothing "
                            "was saved. The browser window was closed.",
                        )
                        return

                    job.state = "saving"
                    job.message = "Login detected. Capturing the session..."
                    handle = _detect_handle(page, platform)
                finally:
                    browser.close()

            summary = _persist(platform, state, handle, self.sessions)

            job.handle = summary.get("handle")
            job.state = "done"
            job.finished_at = datetime.now(timezone.utc)
            job.message = (
                f"Connected{' as ' + job.handle if job.handle else ''}. "
                f"Kept {summary.get('cookies_kept')} first-party cookies; the "
                f"session is encrypted on this machine."
            )
            logger.info("[social] connected %s", platform)

        except Exception as exc:  # noqa: BLE001
            logger.exception("[social] connect %s failed", platform)
            self._fail(job, str(exc)[:300])

    @staticmethod
    def _await_login(context, platform: str, missing_required, job: Job):
        """
        Wait for the platform's auth cookies to appear.

        Better than asking the user to confirm: it cannot be answered before
        the login has actually happened, and it notices the moment it has. The
        CLI's `input("Press Enter...")` could be pressed too early, which
        produced a half-captured session and a confusing failure later.
        """
        deadline = time.monotonic() + LOGIN_TIMEOUT_SECONDS

        while time.monotonic() < deadline:
            try:
                state = context.storage_state()
            except Exception:
                # The user closed the window. Nothing to capture.
                return None

            if not missing_required(state, platform):
                return state

            remaining = int(deadline - time.monotonic())
            job.message = (
                f"Waiting for you to finish signing in... ({remaining}s left). "
                "Complete any 2FA in the browser window."
            )
            time.sleep(LOGIN_POLL_SECONDS)

        return None

    def _fail(self, job: Job, message: str) -> None:
        job.state = "failed"
        job.message = message
        job.finished_at = datetime.now(timezone.utc)

    # -- state ---------------------------------------------------------------

    def disconnect(self, platform: str) -> bool:
        return self.sessions.delete(platform.lower())

    def accounts(self) -> List[dict]:
        """
        Everything the dashboard needs to render the Accounts tab.

        Reports credential and session presence separately, because they fail
        differently: saved credentials with no session means "connect not run
        yet", while a session with no credentials is perfectly normal for
        someone who signed in by hand.
        """
        connected = set(self.sessions.available())
        try:
            usernames = self.vault.describe()
        except Exception:  # noqa: BLE001
            usernames = {}

        out = []
        for platform in SUPPORTED_PLATFORMS:
            job = self._jobs.get(platform)
            record = self.sessions.load(platform) if platform in connected else None
            out.append({
                "platform": platform,
                "connected": platform in connected,
                "handle": (record or {}).get("handle"),
                "has_credentials": platform in usernames,
                "username": usernames.get(platform),
                "job": job.as_dict() if job else None,
                "budget": self._budget(platform),
            })
        return out

    @staticmethod
    def _budget(platform: str) -> Optional[dict]:
        """Today's pacing consumption, or None if nothing has run."""
        try:
            from src.scrapers.base import budget_snapshot

            return budget_snapshot(f"local:{platform}", platform)
        except Exception:  # noqa: BLE001
            return None

    # -- collect -------------------------------------------------------------

    def collect(self, platform: str, query: str = DEFAULT_QUERY,
                max_items: int = 20) -> dict:
        """
        Collect once, in-process, and hand the posts back to the caller.

        Storage is the caller's job -- this module knows about sessions and
        scrapers, not about the ingest pipeline.
        """
        platform = platform.lower()

        from src.scrapers import registry
        from src.scrapers.base import run_scrape
        from src.scrapers.credentials import SocialCredential, derive_expiry

        scraper = COLLECTORS.get(platform)
        if scraper is None:
            return {"platform": platform, "status": "unsupported", "posts": []}

        record = self.sessions.load(platform)
        if record is None:
            return {"platform": platform, "status": "not_connected", "posts": []}

        state = record.get("storage_state") or {}
        credential = SocialCredential(
            platform=platform,
            storage_state=state,
            handle=record.get("handle"),
            account_key=f"local:{platform}",
            expires_at=derive_expiry(state, platform),
            source="dashboard",
        )
        if credential.is_expired:
            return {"platform": platform, "status": "expired", "posts": []}

        result = run_scrape(credential, registry.REGISTRY[scraper].fn,
                            query, max_items=max_items)

        # Platforms rotate cookies during ordinary use. Discarding them makes a
        # stored session drift stale until it stops working, which the user
        # experiences as "it randomly logs me out every few weeks".
        if result.rotated_state and result.status != "challenged":
            try:
                self.sessions.save(platform, result.rotated_state,
                                   handle=credential.handle)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[social] could not persist rotated %s session: %s",
                               platform, exc)

        if result.status == "challenged":
            logger.error(
                "[social] %s served a challenge. Collection for this account is "
                "stopped until you resume it. It will NOT retry on its own.",
                platform,
            )

        return {
            "platform": platform,
            "status": result.status,
            "reason": result.reason,
            "posts": [{
                "platform": platform,
                "poster": post.get("poster"),
                "text": post.get("text", ""),
                "url": post.get("url"),
                "posted_at": post.get("timestamp"),
                "likes": int(post.get("likes") or 0),
                "shares": int(post.get("retweets") or post.get("shares") or 0),
                "comments": int(post.get("replies") or post.get("comments") or 0),
            } for post in result.posts],
        }


_service: Optional[SocialService] = None
_service_lock = threading.Lock()


def get_service() -> SocialService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = SocialService()
    return _service


def reset_service() -> None:
    """Tests."""
    global _service
    _service = None
