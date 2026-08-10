"""
src/config/public_guard.py
The checks that must run before this API is reachable from the internet.

WHY THIS IS A MODULE AND NOT JUST A SCRIPT
------------------------------------------
All of this logic lived in `scripts/serve_public.py`, which refuses to serve on
dangerous configurations rather than warning about them -- a warning scrolls
past, a refusal does not.

But `serve_public.py` is a CLI, and it is NOT the container entrypoint. The
image runs `scripts/start_backend.sh`, which runs uvicorn directly. So every one
of these checks was bypassed the moment the API was containerised -- which is
precisely when it becomes internet-facing. The safety net existed only on the
path people were moving away from.

The checks therefore live here, and are called from application startup when
PUBLIC_HOSTING=1, whatever launched the process. `serve_public.py` becomes a
thin CLI over the same function so the two cannot drift.

Nothing here is enforced when PUBLIC_HOSTING is unset. Running on a laptop for
development is not the same risk as being reachable, and treating it as such
teaches people to set the flag that turns the checks off.
"""

from __future__ import annotations

import logging
import os
from typing import List

logger = logging.getLogger("Roger.public_guard")


def _flag(name: str) -> bool:
    return (os.getenv(name, "") or "").strip().lower() in ("1", "true", "yes", "on")


def _isset(name: str) -> bool:
    return bool((os.getenv(name) or "").strip())


def public_hosting_declared() -> bool:
    return _flag("PUBLIC_HOSTING")


def validate(host: str = "") -> List[str]:
    """
    Blocking problems. An empty list means it is safe to serve publicly.

    `host` is optional because a container does not choose its bind address the
    way the CLI does -- it binds 0.0.0.0 by necessity and the orchestrator
    controls exposure. Passing "" skips the bind check rather than failing every
    containerised start.
    """
    problems: List[str] = []

    if not _flag("AUTH_ENFORCED"):
        problems.append(
            "AUTH_ENFORCED is not 1.\n"
            "      Every route would be publicly writable, including the "
            "device pairing\n"
            "      endpoints -- anyone with the URL could attach their own "
            "client."
        )

    secret = (os.getenv("AUTH_SECRET") or "").strip()
    if not secret:
        problems.append(
            "AUTH_SECRET is unset.\n"
            "      A random key would be minted per boot, logging everyone out "
            "on restart.\n"
            "      With more than one replica, tokens issued by one are "
            "rejected by the others.\n"
            '      python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )
    elif len(secret) < 32:
        problems.append(f"AUTH_SECRET is {len(secret)} chars; HS256 needs >= 32.")

    if not _isset("CORS_ALLOW_ORIGINS"):
        problems.append(
            "CORS_ALLOW_ORIGINS is unset, so CORS falls back to '*'.\n"
            "      Set it to your frontend origin, exactly."
        )

    if not _isset("BOOTSTRAP_ADMIN_EMAIL") or not _isset("BOOTSTRAP_ADMIN_PASSWORD"):
        problems.append(
            "BOOTSTRAP_ADMIN_EMAIL / BOOTSTRAP_ADMIN_PASSWORD are not both set.\n"
            "      Self-registration only creates viewers, so without these "
            "there is no admin\n"
            "      at all and the accounts surface is unreachable."
        )

    # Not a hard failure, because it is a legitimate choice -- but it is a
    # choice, and the default is the permissive one. On a public URL an unset
    # value means anyone with the link can create an account and read the
    # intelligence feed.
    if os.getenv("ALLOW_SELF_REGISTRATION") is None:
        logger.warning(
            "[public] ALLOW_SELF_REGISTRATION is unset and defaults to ON. "
            "Anyone with this URL can create an account and read the feed. "
            "New accounts are viewers and every social route requires admin, "
            "so a connected account is not reachable -- but set it to 0 if "
            "signups should be closed. It is read per request, so no restart "
            "is needed."
        )

    if host == "0.0.0.0":
        problems.append(
            "Binding 0.0.0.0 exposes this API to every device on the local "
            "network.\n"
            "      A tunnel does not need it -- it connects outward from this "
            "machine.\n"
            "      Pass --host 0.0.0.0 --i-mean-it if you really want LAN "
            "access."
        )

    return problems


def enforce_at_startup(host: str = "") -> None:
    """
    Called from application startup. Refuses to continue when PUBLIC_HOSTING=1
    and something is unsafe.

    Raises RuntimeError rather than sys.exit so a test can assert on it and so
    the traceback names this module. In a container, an exception here means the
    pod crash-loops with the reason in the logs -- which is the correct outcome:
    a misconfigured public deployment should not come up.
    """
    if not public_hosting_declared():
        return

    problems = validate(host)
    if not problems:
        logger.info("[public] PUBLIC_HOSTING=1 and the safety checks pass")
        return

    detail = "\n".join(f"  - {p}" for p in problems)
    raise RuntimeError(
        "PUBLIC_HOSTING=1 but this instance is not safe to expose:\n"
        f"{detail}\n"
        "Fix these, or unset PUBLIC_HOSTING if this is not internet-facing."
    )
