"""
connector/vault.py
Social account credentials, encrypted on this machine only.

The research on why personal accounts get restricted points at one thing above
all others: **logging in is the risky act, not scraping.** A login from an
unfamiliar browser fingerprint is what triggers a device-verification challenge;
repeated logins are what trigger "too many attempts" lockouts; and a fresh
session on every run is itself anomalous, because a real person's session
persists for weeks.

So the design here is deliberately not "store the password and log in each
time". It is:

  1. The password is stored encrypted **on this device**, never sent anywhere.
  2. It is used to PRE-FILL the platform's own login form in a real, visible
     browser -- the user completes 2FA, captcha or passkey themselves.
  3. That happens **once**. The resulting session is persisted and reused, and
     rotated cookies are written back after every run, which is the single
     biggest factor in how long a connected account keeps working.

Step 3 is what actually protects the account. Steps 1-2 exist because typing a
password into a browser window by hand every time a session expires is a poor
experience, not because automating the login is safer -- it is not.

What this deliberately does NOT do, and will not: fingerprint spoofing, proxy
rotation, captcha solving, or anything else whose purpose is to make automated
access look like it is not automated. Those are ban-evasion, they escalate the
consequence when detection does happen, and they are outside what this project
is for. If a platform challenges a login, the human answers it.

Encryption reuses the connector's existing KeyStore: AES-256-GCM with the key
in the OS keychain, falling back to a 0600 file. Same protection as the session
store, because a password is at least as sensitive as a session cookie.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Dict, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .storage import KeyStore, _restrict, config_dir

logger = logging.getLogger("connector.vault")

VAULT_FILE = "credentials.enc"

# Bound in as AAD, exactly as SessionStore binds the platform name. A vault
# file renamed over a session file fails to decrypt rather than being
# misinterpreted.
VAULT_AAD = b"connector-credential-vault-v1"

# Bound to the same platform list the login flow supports.
SUPPORTED = ("twitter", "linkedin", "facebook", "instagram", "reddit")


class CredentialVault:
    """
    Username/password per platform, at rest on this machine.

    Deliberately a separate file from the session store. A user who wants to
    keep sessions but forget passwords -- a reasonable thing to want -- should
    be able to delete one without the other.
    """

    def __init__(self, directory=None, keystore: Optional[KeyStore] = None):
        self._dir = directory or config_dir()
        self._keys = keystore or KeyStore(self._dir)

    @property
    def path(self):
        return self._dir / VAULT_FILE

    def _read_all(self) -> Dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            blob = self.path.read_bytes()
            nonce, ct = blob[:12], blob[12:]
            plaintext = AESGCM(self._keys.load_or_create()).decrypt(
                nonce, ct, VAULT_AAD
            )
            return json.loads(plaintext.decode("utf-8"))
        except Exception as exc:
            # A vault that cannot be read is a real problem -- say so rather
            # than silently behaving like an empty one, which would send the
            # user round the "why won't it remember me" loop.
            logger.error("[vault] could not read credentials: %s", exc)
            raise

    def _write_all(self, data: Dict[str, dict]) -> None:
        aesgcm = AESGCM(self._keys.load_or_create())
        nonce = os.urandom(12)
        blob = nonce + aesgcm.encrypt(
            nonce, json.dumps(data).encode("utf-8"), VAULT_AAD
        )

        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(blob)
        _restrict(tmp)
        tmp.replace(self.path)
        _restrict(self.path)

    def save(self, platform: str, username: str, password: str) -> None:
        platform = platform.lower()
        if platform not in SUPPORTED:
            raise ValueError(f"Unsupported platform: {platform}")
        if not username or not password:
            raise ValueError("Both a username and a password are required")

        data = self._read_all() if self.path.exists() else {}
        data[platform] = {"username": username, "password": password}
        self._write_all(data)
        logger.info("[vault] stored credentials for %s (this device only)", platform)

    def get(self, platform: str) -> Optional[dict]:
        return self._read_all().get(platform.lower())

    def forget(self, platform: str) -> bool:
        data = self._read_all() if self.path.exists() else {}
        if platform.lower() not in data:
            return False
        del data[platform.lower()]
        self._write_all(data)
        return True

    def platforms(self) -> list:
        """Which platforms have credentials stored. Never returns secrets."""
        if not self.path.exists():
            return []
        try:
            return sorted(self._read_all())
        except Exception:  # noqa: BLE001
            # A vault that exists but will not decrypt is NOT an empty vault.
            # Returning [] silently reports "no credentials stored", so the
            # accounts panel shows every platform as unconnected and the user
            # re-enters a password that is already there. Log it; the caller
            # still gets a safe value, but the failure is no longer invisible.
            logger.warning(
                "[vault] %s exists but could not be read; reporting no platforms",
                self.path,
            )
            return []

    def describe(self) -> Dict[str, str]:
        """Usernames only, for display. Passwords never leave this class."""
        try:
            return {
                platform: entry.get("username", "")
                for platform, entry in self._read_all().items()
            }
        except Exception:  # noqa: BLE001
            # Same reasoning as platforms(): a decrypt failure must not be
            # indistinguishable from "nothing saved".
            logger.warning(
                "[vault] %s could not be decrypted; saved usernames unavailable",
                self.path,
            )
            return {}
