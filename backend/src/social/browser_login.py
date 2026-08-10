"""
connector/connect.py
Capturing a social session, on the user's own machine.

Two routes, because one of them needs no installer:

1. ``login`` -- opens a REAL, VISIBLE browser at the platform's own login page.
   The user signs in normally: password manager, passkey, 2FA, whatever they
   already use. If they have saved credentials in the local vault
   (connector/vault.py) the username and password fields are pre-filled; the
   form is never submitted automatically and no challenge is ever answered for
   them. The password lives encrypted on this machine and is never sent to the
   server. When they confirm, the session is captured and encrypted locally.

2. ``paste`` -- accepts a storage_state JSON exported from DevTools. Uglier, but
   it needs no packaged binary, so the whole pipeline is testable before code
   signing exists.

Why a desktop step is unavoidable, once per platform: every platform's auth
cookie is httpOnly -- auth_token, xs, sessionid, li_at -- verified against real
captures. document.cookie cannot read them, so there is no bookmarklet, console
snippet, or mobile path that can produce a session. A phone genuinely cannot do
this.

The browser is driven with channel="chrome" where available, so the user logs in
through the browser they already have, with their own profile and fingerprint,
rather than a freshly downloaded Chromium that looks nothing like them.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from src.scrapers.credentials import (
    CredentialError, derive_expiry, filter_first_party, missing_required, validate,
)

from .storage import SessionStore

logger = logging.getLogger("connector.connect")

LOGIN_URLS = {
    "twitter": "https://x.com/i/flow/login",
    "facebook": "https://www.facebook.com/login",
    "instagram": "https://www.instagram.com/accounts/login/",
    "linkedin": "https://www.linkedin.com/login",
    "reddit": "https://www.reddit.com/login",
}

# Where to look for the signed-in handle once login completes. Best-effort:
# it is a display nicety, never a gate.
HANDLE_PROBES = {
    "twitter": ('[data-testid="SideNav_AccountSwitcher_Button"]', "aria-label"),
    "linkedin": (".global-nav__me-photo", "alt"),
    "instagram": ('nav a[href^="/"][role="link"]', "href"),
}


def _launch_browser(playwright, *, headless: bool = False):
    """
    Prefer the user's installed Chrome.

    channel="chrome" avoids a ~150MB Chromium download and, more importantly,
    means the login happens in the browser they recognise.
    """
    try:
        return playwright.chromium.launch(channel="chrome", headless=headless)
    except Exception:
        logger.info("[connect] system Chrome not found; using bundled Chromium")
        return playwright.chromium.launch(headless=headless)


def _detect_handle(page, platform: str) -> Optional[str]:
    probe = HANDLE_PROBES.get(platform)
    if not probe:
        return None
    selector, attr = probe
    try:
        loc = page.locator(selector).first
        if loc.count():
            value = loc.get_attribute(attr) or ""
            value = value.strip().strip("/")
            if value:
                return value.split("/")[-1][:80]
    except Exception:
        pass
    return None


def connect_via_login(
    platform: str,
    store: Optional[SessionStore] = None,
    prefill: Optional[dict] = None,
) -> dict:
    """
    Open a visible browser, let the user sign in, capture the session.

    Returns a summary. The storage_state itself is written encrypted to disk and
    is deliberately not returned -- nothing upstream has a reason to hold it.
    """
    platform = platform.lower()
    if platform not in LOGIN_URLS:
        raise ValueError(f"Unsupported platform: {platform}")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is required to connect an account.\n"
            "  pip install playwright && playwright install chromium"
        ) from exc

    store = store or SessionStore()

    print(f"\nOpening {platform} in a browser window.")
    print("Sign in exactly as you normally would -- password manager, passkey and")
    print("2FA all work. This tool never sees your password.\n")

    with sync_playwright() as p:
        browser = _launch_browser(p, headless=False)
        try:
            context = browser.new_context()
            page = context.new_page()
            page.goto(LOGIN_URLS[platform], wait_until="domcontentloaded")

            # Pre-fill from the local vault if the user saved credentials.
            #
            # This types the username and password into the platform's own
            # login form and stops. It does NOT submit, and it does not touch
            # 2FA, captcha or passkey -- the human does those. Automating the
            # whole login is what turns a device-verification challenge into a
            # lockout, and the challenge exists to be answered by a person.
            if prefill:
                _prefill_login(page, platform, prefill)

            input("Press Enter here once you are signed in and can see your feed... ")

            raw_state = context.storage_state()
            handle = _detect_handle(page, platform)
        finally:
            browser.close()

    return _persist(platform, raw_state, handle, store)


# Login-form fields, per platform. Only the username and password inputs -- no
# submit button, deliberately. Best-effort: a miss means the user types it
# themselves, which is the pre-existing behaviour and not a failure.
LOGIN_FIELDS = {
    "twitter": ('input[name="text"]', 'input[name="password"]'),
    "linkedin": ("#username", "#password"),
    "facebook": ("#email", "#pass"),
    "instagram": ('input[name="username"]', 'input[name="password"]'),
    "reddit": ('input[name="username"]', 'input[name="password"]'),
}


def _prefill_login(page, platform: str, credentials: dict) -> None:
    """
    Type the saved username and password into the platform's own login form.

    Stops there. Submitting, 2FA, captcha and passkey are left to the human --
    partly because automating them is what escalates a routine device
    verification into a lockout, and partly because a challenge is meant to
    prove a person is present, and one is.

    X in particular asks for the username first and reveals the password field
    only after "Next", so the password fill is expected to miss there. That is
    fine; the field is visible on screen by the time the user needs it.
    """
    fields = LOGIN_FIELDS.get(platform)
    if not fields:
        return

    username_sel, password_sel = fields
    filled = []

    for selector, value, label in (
        (username_sel, credentials.get("username"), "username"),
        (password_sel, credentials.get("password"), "password"),
    ):
        if not value:
            continue
        try:
            field = page.locator(selector).first
            field.wait_for(state="visible", timeout=5000)
            field.fill(value)
            filled.append(label)
        except Exception:
            # Layouts change and multi-step flows hide fields. Not an error.
            continue

    if filled:
        print(f"  Pre-filled: {', '.join(filled)}. Complete any 2FA in the window.")
    else:
        print("  Could not pre-fill the form -- sign in as usual.")


def connect_via_paste(platform: str, state_json: str,
                      store: Optional[SessionStore] = None) -> dict:
    """
    Accept a storage_state exported by hand.

    Exists so the pipeline is testable before a signed installer exists --
    code signing has procurement lead time and nothing should be blocked on it.
    """
    platform = platform.lower()
    try:
        raw_state = json.loads(state_json)
    except json.JSONDecodeError as exc:
        raise CredentialError(f"Not valid JSON: {exc}") from exc

    return _persist(platform, raw_state, None, store or SessionStore())


def _persist(platform: str, raw_state: dict, handle: Optional[str],
             store: SessionStore) -> dict:
    """Filter, validate, report, store."""
    before = len(raw_state.get("cookies", []))
    state = filter_first_party(raw_state, platform)
    after = len(state.get("cookies", []))

    missing = missing_required(state, platform)
    if missing:
        raise CredentialError(
            f"The captured session is missing {missing}. That usually means "
            "login did not finish. Nothing was saved -- try again."
        )

    validate(state, platform)
    expires = derive_expiry(state, platform)

    # Say plainly what is being kept, before keeping it.
    print(f"\nCaptured {after} first-party {platform} cookies "
          f"({before - after} third-party trackers discarded).")
    print("Stored encrypted on THIS machine only. It is never uploaded --")
    print("the server receives collected posts and status, never credentials.")
    if expires:
        print(f"Session valid until roughly {expires.date().isoformat()}.")

    store.save(platform, state, handle=handle)

    return {
        "platform": platform,
        "handle": handle,
        "cookies_kept": after,
        "cookies_discarded": before - after,
        "session_expires_at": expires.isoformat() if expires else None,
    }


def disconnect(platform: str, store: Optional[SessionStore] = None) -> bool:
    store = store or SessionStore()
    removed = store.delete(platform)
    if removed:
        print(f"\nRemoved the local {platform} session.")
        print("To invalidate it on the platform itself, use their "
              "'log out of all devices' setting -- deleting a local copy does "
              "not end the session server-side.")
    return removed
