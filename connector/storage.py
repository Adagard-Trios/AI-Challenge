"""
connector/storage.py
Local, encrypted session storage.

This is the file that makes the whole design honest. Session cookies live here,
on the user's own machine, and are never transmitted. The server receives posts
and status; it has no way to obtain a credential.

Encryption at rest uses AES-256-GCM with a key held in the OS keychain
(Credential Manager / Keychain / Secret Service) when one is available, falling
back to a key file with 0600 permissions. The fallback is weaker -- anything
running as the user can read it -- and says so out loud rather than implying a
protection it does not provide.

What this protects against: a stolen laptop with disk encryption off, a synced
backup, someone reading the config directory. What it does not: malware running
as the user. Nothing file-based can.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger("connector.storage")

APP_NAME = "roger-connector"
KEYRING_SERVICE = "roger-connector"
KEYRING_KEY = "session-encryption-key"

# Bound the payload: a legitimate storage_state is single-digit KB. Anything
# larger is a mistake or an attempt to fill the disk.
MAX_STATE_BYTES = 512 * 1024


def config_dir() -> Path:
    """Per-OS config location."""
    if sys.platform == "win32":
        base = Path(os.getenv("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.getenv("XDG_CONFIG_HOME") or Path.home() / ".config")
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _restrict(path: Path) -> None:
    """Owner-only. A no-op on Windows, where ACLs govern instead."""
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


class KeyStore:
    """Holds the encryption key, preferring the OS keychain."""

    def __init__(self, directory: Optional[Path] = None):
        self.directory = directory or config_dir()
        self._key: Optional[bytes] = None

    def _keyring(self):
        try:
            import keyring
            return keyring
        except ImportError:
            return None

    def _key_file(self) -> Path:
        return self.directory / "session.key"

    def load_or_create(self) -> bytes:
        if self._key is not None:
            return self._key

        kr = self._keyring()
        if kr is not None:
            try:
                stored = kr.get_password(KEYRING_SERVICE, KEYRING_KEY)
                if stored:
                    self._key = bytes.fromhex(stored)
                    return self._key
            except Exception as exc:
                logger.warning("[storage] keychain unreadable (%s); using key file", exc)

        path = self._key_file()
        if path.exists():
            self._key = path.read_bytes()
            if len(self._key) == 32:
                return self._key
            logger.warning("[storage] key file malformed; regenerating")

        key = AESGCM.generate_key(bit_length=256)

        if kr is not None:
            try:
                kr.set_password(KEYRING_SERVICE, KEYRING_KEY, key.hex())
                self._key = key
                logger.info("[storage] encryption key stored in the OS keychain")
                return key
            except Exception as exc:
                logger.warning("[storage] could not write to keychain (%s)", exc)

        path.write_bytes(key)
        _restrict(path)
        logger.warning(
            "[storage] No OS keychain available. The encryption key is in %s with "
            "owner-only permissions. This protects a stolen disk or a synced "
            "backup; it does NOT protect against software running as you.",
            path,
        )
        self._key = key
        return key


class SessionStore:
    """
    Encrypted per-platform session storage.

    Layout: one file per platform, ``<platform>.session``, containing
    nonce(12) || ciphertext || tag. The platform name is bound in as AAD, so a
    file renamed from linkedin.session to twitter.session fails to decrypt
    rather than silently loading the wrong credential.
    """

    def __init__(self, directory: Optional[Path] = None):
        self.directory = directory or config_dir()
        self.directory.mkdir(parents=True, exist_ok=True)
        self._keys = KeyStore(self.directory)

    def _path(self, platform: str) -> Path:
        return self.directory / f"{platform.lower()}.session"

    def _aad(self, platform: str) -> bytes:
        return f"roger:connector:v1:{platform.lower()}".encode()

    def save(self, platform: str, storage_state: dict, handle: Optional[str] = None) -> None:
        payload = json.dumps({
            "storage_state": storage_state,
            "handle": handle,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }).encode("utf-8")

        if len(payload) > MAX_STATE_BYTES:
            raise ValueError(
                f"session payload is {len(payload)} bytes, over the "
                f"{MAX_STATE_BYTES} limit -- this does not look like a session"
            )

        aesgcm = AESGCM(self._keys.load_or_create())
        nonce = os.urandom(12)
        blob = nonce + aesgcm.encrypt(nonce, payload, self._aad(platform))

        path = self._path(platform)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(blob)
        _restrict(tmp)
        tmp.replace(path)          # atomic; never a half-written session
        logger.info("[storage] saved %s session (%d bytes encrypted)", platform, len(blob))

    def load(self, platform: str) -> Optional[dict]:
        path = self._path(platform)
        if not path.exists():
            return None
        try:
            blob = path.read_bytes()
            nonce, ct = blob[:12], blob[12:]
            plaintext = AESGCM(self._keys.load_or_create()).decrypt(
                nonce, ct, self._aad(platform)
            )
            return json.loads(plaintext)
        except Exception as exc:
            # Wrong key, tampering, or a renamed file. Never fall back to
            # anything -- a failed decrypt means we do not have this session.
            logger.error("[storage] cannot decrypt %s session: %s", platform, exc)
            return None

    def delete(self, platform: str) -> bool:
        path = self._path(platform)
        if not path.exists():
            return False
        # Best-effort overwrite before unlink. On an SSD with wear levelling
        # this is not a guarantee, which is why the real answer is telling the
        # user to log out on the platform.
        try:
            size = path.stat().st_size
            with open(path, "r+b") as fh:
                fh.write(os.urandom(size))
                fh.flush()
                os.fsync(fh.fileno())
        except OSError:
            pass
        path.unlink(missing_ok=True)
        logger.info("[storage] deleted %s session", platform)
        return True

    def available(self) -> list:
        return sorted(p.stem for p in self.directory.glob("*.session"))


class DeviceConfig:
    """Server URL and device token. The token is a credential, so 0600."""

    def __init__(self, directory: Optional[Path] = None):
        self.path = (directory or config_dir()) / "device.json"

    def load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def save(self, **fields) -> None:
        data = {**self.load(), **fields}
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        _restrict(self.path)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)

    @property
    def is_paired(self) -> bool:
        d = self.load()
        return bool(d.get("device_token") and d.get("server_url"))
