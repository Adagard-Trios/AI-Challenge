"""
connector/backoff.py
Per-account failure backoff that survives a restart.

The point of persisting it: an in-memory counter is reset by exactly the thing
that tends to follow repeated failures -- someone restarting the connector.
That turns "back off for six hours" into "retry immediately, again", which is
the behaviour most likely to escalate a soft block into a hard one.

State lives beside the encrypted sessions, in plain JSON. It contains no
credentials -- only platform names, counters and timestamps -- so it is
deliberately not encrypted; readable state is easier to support.
"""

from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Optional

from .storage import config_dir

logger = logging.getLogger("connector.backoff")

BASE_DELAY_SECONDS = 15 * 60          # 15 minutes
MAX_DELAY_SECONDS = 6 * 3600          # 6 hours
JITTER = 0.2                          # +/-20%

# A challenge is categorically different from a failure: the platform has
# noticed us. It gets a fixed, long cooldown and requires an explicit resume,
# never an automatic one.
CHALLENGE_COOLDOWN_SECONDS = 24 * 3600


@dataclass
class PlatformState:
    failures: int = 0
    next_attempt_at: float = 0.0      # unix epoch
    last_error: Optional[str] = None
    challenged: bool = False


class BackoffStore:
    def __init__(self, directory: Optional[Path] = None):
        self.path = (directory or config_dir()) / "backoff.json"
        self._state: Dict[str, PlatformState] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._state = {k: PlatformState(**v) for k, v in raw.items()}
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            # Corrupt state must not stop collection; starting from zero is the
            # safe direction here (we pace, we do not skip).
            logger.warning("[backoff] unreadable state, starting fresh: %s", exc)
            self._state = {}

    def _save(self) -> None:
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({k: asdict(v) for k, v in self._state.items()}, indent=2),
                encoding="utf-8",
            )
            tmp.replace(self.path)
        except OSError as exc:
            logger.warning("[backoff] could not persist state: %s", exc)

    def _get(self, platform: str) -> PlatformState:
        return self._state.setdefault(platform.lower(), PlatformState())

    # -- queries -----------------------------------------------------------

    def ready(self, platform: str) -> bool:
        return time.time() >= self._get(platform).next_attempt_at

    def wait_seconds(self, platform: str) -> float:
        return max(0.0, self._get(platform).next_attempt_at - time.time())

    def is_challenged(self, platform: str) -> bool:
        return self._get(platform).challenged

    def describe(self, platform: str) -> str:
        st = self._get(platform)
        if st.challenged:
            return "challenged -- resume manually in the dashboard"
        wait = self.wait_seconds(platform)
        if wait <= 0:
            return "ready"
        return f"backing off {wait / 60:.0f}m after {st.failures} failure(s)"

    # -- transitions -------------------------------------------------------

    def record_success(self, platform: str) -> None:
        st = self._get(platform)
        if st.failures or st.next_attempt_at:
            logger.info("[backoff] %s recovered; clearing backoff", platform)
        st.failures = 0
        st.next_attempt_at = 0.0
        st.last_error = None
        self._save()

    def record_failure(self, platform: str, error: Optional[str] = None) -> float:
        """Exponential with jitter, capped. Returns the delay applied."""
        st = self._get(platform)
        st.failures += 1
        st.last_error = error

        delay = min(BASE_DELAY_SECONDS * (2 ** (st.failures - 1)), MAX_DELAY_SECONDS)
        delay *= random.uniform(1 - JITTER, 1 + JITTER)

        st.next_attempt_at = time.time() + delay
        self._save()

        logger.warning("[backoff] %s failure #%d; next attempt in %.0fm",
                       platform, st.failures, delay / 60)
        return delay

    def record_challenge(self, platform: str, reason: Optional[str] = None) -> None:
        """
        Hard stop. Fixed 24h cooldown AND a flag that only resume() clears, so
        the wait elapsing is not enough on its own -- a human has to look.
        """
        st = self._get(platform)
        st.challenged = True
        st.last_error = reason
        st.next_attempt_at = time.time() + CHALLENGE_COOLDOWN_SECONDS
        self._save()
        logger.error(
            "[backoff] %s CHALLENGED -- stopped. Check the account, then resume "
            "it in the dashboard. It will not restart on its own.", platform,
        )

    def resume(self, platform: str) -> None:
        """Explicit operator action after a challenge."""
        st = self._get(platform)
        st.challenged = False
        st.failures = 0
        st.next_attempt_at = 0.0
        self._save()
        logger.info("[backoff] %s resumed by operator", platform)

    def snapshot(self) -> Dict[str, dict]:
        return {k: asdict(v) for k, v in self._state.items()}
