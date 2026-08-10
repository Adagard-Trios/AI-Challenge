"""
src/scrapers/challenge.py
Decide whether a loaded page means: we are fine, our session died, or the
platform is challenging us.

This is the module that keeps accounts safe. The rule it enforces is simple and
absolute: **when a platform pushes back, stop.** No retry, no workaround, no
attempt to solve a challenge. Retrying into a checkpoint is what turns a soft
block into a permanent one.

What it replaces
----------------
Detection used to be a single expression, repeated at eight sites:

    "login" in page.url

That is wrong in both directions. It false-*negatives* on every challenge wall,
because X serves those at ``/account/access`` and Meta at ``/checkpoint/`` --
neither contains "login" -- so the scraper would happily keep hammering an
account that had already been flagged. And it false-*positives* on any post URL
containing the substring "login".

It also assumed a logged-out state produces a redirect. All four platforms
increasingly serve a **200 OK logged-out page** at the URL you asked for, so
absence-of-login-URL is not evidence of a live session. Hence the third state:
a *positive* logged-in assertion, checked explicitly.

Design
------
``classify()`` is a pure function over a page snapshot, so every signal is
unit-testable against an HTML fixture with no browser involved. ``probe()`` is
the thin Playwright adapter.

Order matters: challenge is checked before expiry, because a challenge page
often also lacks the logged-in markers and would otherwise be misread as a
simple expiry -- which would prompt the user to re-connect, sending fresh
credentials straight into a flagged session.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, List, Optional, Sequence, Set
from urllib.parse import urlsplit

logger = logging.getLogger("Roger.scrapers.challenge")


class SessionState(str, Enum):
    OK = "ok"
    EXPIRED = "expired"        # session no longer valid -> user must reconnect
    CHALLENGED = "challenged"  # platform is actively gating us -> hard stop
    UNKNOWN = "unknown"        # no positive assertion; treat as suspicious


class SessionExpired(Exception):
    """Session is no longer authenticated. Caller must stop and flag reconnect."""


class ChallengeDetected(Exception):
    """
    Platform served a challenge / checkpoint / soft block.

    Caller must stop immediately, cool down, and require explicit user action.
    Never retried, never auto-resumed, never solved.
    """


@dataclass(frozen=True)
class PlatformSignals:
    # URL *path* fragments (matched on path only, so a post whose query string
    # contains "login" cannot trigger a false positive).
    expired_paths: Sequence[str] = ()
    challenge_paths: Sequence[str] = ()

    # CSS selectors. The caller resolves presence; classify() only reads the set.
    expired_selectors: Sequence[str] = ()
    challenge_selectors: Sequence[str] = ()
    logged_in_selectors: Sequence[str] = ()

    # Case-insensitive substrings of visible text.
    challenge_text: Sequence[str] = ()
    expired_text: Sequence[str] = ()

    def all_selectors(self) -> List[str]:
        return list(
            dict.fromkeys(
                [*self.expired_selectors, *self.challenge_selectors, *self.logged_in_selectors]
            )
        )


SIGNALS = {
    "twitter": PlatformSignals(
        expired_paths=("/i/flow/login", "/login", "/i/flow/signup"),
        challenge_paths=("/account/access", "/i/flow/consent_flow"),
        expired_selectors=('[data-testid="loginButton"]', '[data-testid="signupButton"]'),
        challenge_selectors=(
            'iframe[src*="arkoselabs"]',
            "#arkose",
            '[data-testid="ocfEnterTextTextInput"]',
        ),
        logged_in_selectors=(
            '[data-testid="SideNav_AccountSwitcher_Button"]',
            '[data-testid="AppTabBar_Home_Link"]',
            '[data-testid="primaryColumn"]',
        ),
        challenge_text=(
            "suspicious login prevented",
            "verify your identity",
            "we need to confirm",
            "your account has been locked",
            "something went wrong. try reloading",
        ),
        expired_text=("sign in to x", "log in to twitter", "sign up for x"),
    ),
    "linkedin": PlatformSignals(
        expired_paths=("/authwall", "/uas/login", "/checkpoint/lg/login", "/login"),
        challenge_paths=("/checkpoint/challenge", "/checkpoint/rp"),
        expired_selectors=("a[href*='/login']", "form.login__form", "#session_key"),
        challenge_selectors=(
            "#captcha-internal",
            'iframe[src*="arkoselabs"]',
            ".challenge-dialog",
        ),
        logged_in_selectors=(
            ".global-nav__me",
            "img.global-nav__me-photo",
            "#global-nav",
        ),
        challenge_text=(
            "let's do a quick security check",
            "we've restricted your account",
            "verify your identity",
            "unusual activity",
        ),
        expired_text=("join linkedin", "sign in to see", "new to linkedin"),
    ),
    "facebook": PlatformSignals(
        expired_paths=("/login.php", "/login/", "/login"),
        challenge_paths=("/checkpoint/", "/checkpoint"),
        expired_selectors=('input[name="pass"]', "#email", "#loginbutton"),
        challenge_selectors=(
            '[data-testid="checkpoint_title"]',
            "#checkpointSubmitButton",
        ),
        logged_in_selectors=(
            '[aria-label="Your profile"]',
            '[aria-label="Account"]',
            'div[role="banner"]',
        ),
        challenge_text=(
            "you're temporarily blocked",
            "we limit how often",
            "please confirm it's you",
            "your account has been locked",
            "suspicious activity",
        ),
        expired_text=("log in to facebook", "log into facebook", "create new account"),
    ),
    "instagram": PlatformSignals(
        expired_paths=("/accounts/login", "/accounts/signup"),
        challenge_paths=("/challenge", "/accounts/suspended"),
        expired_selectors=('input[name="username"]', 'input[name="password"]'),
        challenge_selectors=("#challenge_form", '[role="dialog"] form'),
        logged_in_selectors=(
            'svg[aria-label="Home"]',
            'a[href="/direct/inbox/"]',
            'nav[role="navigation"]',
        ),
        challenge_text=(
            "suspicious login attempt",
            "we detected unusual activity",
            "try again later",
            "please wait a few minutes before you try again",
            "your account has been temporarily locked",
        ),
        expired_text=("log in to instagram", "sign up to see"),
    ),
    "reddit": PlatformSignals(
        expired_paths=("/login", "/register"),
        challenge_paths=("/quarantine",),
        expired_selectors=(".login-form", 'input[name="password"]'),
        challenge_selectors=('iframe[title*="recaptcha"]', "#quarantine_optin"),
        logged_in_selectors=('[data-testid="user-drawer-button"]', "#header-bottom-right .user"),
        challenge_text=("you have been temporarily blocked", "rate limit"),
        expired_text=("log in to reddit",),
    ),
}


def _path_of(url: str) -> str:
    try:
        return (urlsplit(url).path or "/").lower()
    except ValueError:
        return ""


def _norm_text(text: str) -> str:
    """Lowercase and collapse whitespace so multi-line markup matches."""
    return re.sub(r"\s+", " ", (text or "")).lower()


def classify(
    platform: str,
    url: str,
    text: str = "",
    present_selectors: Optional[Iterable[str]] = None,
) -> SessionState:
    """
    Pure classifier. ``present_selectors`` is the subset of
    ``SIGNALS[platform].all_selectors()`` the caller found on the page.

    Order is deliberate: CHALLENGE first. A challenge page usually also lacks
    the logged-in markers, and misreading it as EXPIRED would tell the user to
    reconnect -- feeding fresh credentials into an already-flagged session.
    """
    sig = SIGNALS.get(platform.lower())
    if sig is None:
        return SessionState.UNKNOWN

    present: Set[str] = set(present_selectors or ())
    path = _path_of(url)
    body = _norm_text(text)

    # 1. Challenge
    if any(p in path for p in sig.challenge_paths):
        return SessionState.CHALLENGED
    if present & set(sig.challenge_selectors):
        return SessionState.CHALLENGED
    if any(marker in body for marker in sig.challenge_text):
        return SessionState.CHALLENGED

    # 2. Expired
    if any(path == p or path.startswith(p) for p in sig.expired_paths):
        return SessionState.EXPIRED
    if present & set(sig.expired_selectors):
        return SessionState.EXPIRED
    if any(marker in body for marker in sig.expired_text):
        return SessionState.EXPIRED

    # 3. Positive assertion -- required, not inferred
    if present & set(sig.logged_in_selectors):
        return SessionState.OK

    return SessionState.UNKNOWN


def probe(page, platform: str, *, timeout_ms: int = 1500) -> SessionState:
    """
    Playwright adapter: resolve the platform's selectors against a live page,
    then delegate to ``classify``.

    Selector checks use a short timeout because we are testing for *presence*,
    not waiting for an element to appear.
    """
    sig = SIGNALS.get(platform.lower())
    if sig is None:
        return SessionState.UNKNOWN

    present: List[str] = []
    for selector in sig.all_selectors():
        try:
            if page.locator(selector).first.is_visible(timeout=timeout_ms):
                present.append(selector)
        except Exception:
            # Selector invalid for this DOM, or simply absent. Both mean
            # "not present" -- never let a probe failure abort the scrape.
            continue

    try:
        text = page.inner_text("body", timeout=timeout_ms)
    except Exception:
        text = ""

    try:
        url = page.url
    except Exception:
        url = ""

    return classify(platform, url, text, present)


def enforce(page, platform: str) -> SessionState:
    """
    Probe and raise on a bad state.

    UNKNOWN is deliberately *not* fatal: a slow render or an A/B layout should
    degrade to "we got nothing useful", not to "your account is broken". It is
    logged so a persistent UNKNOWN is visible as a selector-rot signal.
    """
    state = probe(page, platform)

    if state is SessionState.CHALLENGED:
        raise ChallengeDetected(
            f"{platform}: platform served a challenge or checkpoint. "
            "Stopping this account; explicit user action required."
        )
    if state is SessionState.EXPIRED:
        raise SessionExpired(f"{platform}: session is no longer authenticated.")
    if state is SessionState.UNKNOWN:
        logger.warning(
            "[challenge] %s: no logged-in assertion matched -- selectors may have "
            "rotted, or the page did not finish rendering",
            platform,
        )
    return state


def evidence(page, platform: str) -> dict:
    """
    Minimal, non-sensitive record of why we stopped, for the audit log.

    Deliberately never a screenshot: that would capture the user's private feed.
    """
    try:
        url_path = _path_of(page.url)
    except Exception:
        url_path = ""
    try:
        heading = (page.inner_text("h1, h2", timeout=1000) or "")[:200]
    except Exception:
        heading = ""
    return {"platform": platform, "url_path": url_path, "heading": heading}
