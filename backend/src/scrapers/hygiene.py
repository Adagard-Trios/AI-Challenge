"""
src/scrapers/hygiene.py
Browser launch profiles and pacing constants, in one place.

Scope note: this is *operational hygiene*, not detection evasion. Everything
here exists so that automated collection behaves like an ordinary, polite
client -- correct headers, realistic pacing, no hammering. It deliberately does
not attempt to defeat bot detection: no fingerprint randomisation, no CAPTCHA
handling, no proxy rotation. When a platform says stop, the caller stops
(see challenge.py).

Why centralise: the same settings were previously spread across ~12 launch
sites with three different values. The copies that actually ran -- the ones in
tool_factory.py -- sent

    Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36

with no ``Chrome/`` and no ``Safari/537.36`` token. That is not a User-Agent any
real browser has ever sent, and sites serve it a degraded or mobile layout,
which then breaks the desktop selectors. That was a correctness bug, not a
stealth one.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List

# --- User agents -----------------------------------------------------------
# Full, coherent UA strings. A UA must match the browser we actually launch;
# claiming to be something else produces markup our selectors do not expect.

CHROME_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Instagram serves a substantially simpler DOM to mobile Safari, which is what
# the existing Instagram scrapers target.
IPHONE_SAFARI_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)

# Used only for Instagram's own media endpoint, which rejects browser UAs.
INSTAGRAM_APP_UA = (
    "Instagram 290.0.0.0.66 (iPhone14,5; iOS 17_0; en_US) AppleWebKit/605.1.15"
)
INSTAGRAM_APP_ID = "936619743392459"


# --- Launch arguments ------------------------------------------------------

# --disable-dev-shm-usage matters on Render specifically: containers get a 64MB
# /dev/shm by default and Chromium crashes when it fills. --disable-gpu and
# --no-zygote reduce resident memory. Deliberately NOT using --single-process:
# it looks like a memory win and reliably crashes on these pages.
BASE_LAUNCH_ARGS: List[str] = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-infobars",
    "--disable-blink-features=AutomationControlled",
]

# Resource types we never read. Images and fonts are the majority of a Facebook
# or Instagram feed's resident memory, so blocking them is the single cheapest
# memory win available.
BLOCKED_RESOURCE_TYPES = frozenset({"image", "media", "font"})


class LaunchProfile(str, Enum):
    DESKTOP = "desktop"   # twitter, facebook, linkedin
    MOBILE = "mobile"     # instagram


@dataclass(frozen=True)
class ContextProfile:
    user_agent: str
    viewport: Dict[str, int]
    locale: str = "en-US"
    timezone_id: str = "Asia/Colombo"   # matches the platform's subject matter

    def as_context_kwargs(self) -> dict:
        return {
            "user_agent": self.user_agent,
            "viewport": dict(self.viewport),
            "locale": self.locale,
            "timezone_id": self.timezone_id,
        }


PROFILES: Dict[LaunchProfile, ContextProfile] = {
    LaunchProfile.DESKTOP: ContextProfile(
        user_agent=CHROME_DESKTOP_UA,
        viewport={"width": 1400, "height": 900},
    ),
    LaunchProfile.MOBILE: ContextProfile(
        user_agent=IPHONE_SAFARI_UA,
        viewport={"width": 430, "height": 932},
    ),
}


# Removes the `navigator.webdriver` flag that Playwright sets. This is standard
# practice and is about not being gratuitously misidentified; it is not an
# attempt to defeat a fingerprinting system.
WEBDRIVER_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = window.chrome || {runtime: {}};
"""


# --- Pacing ----------------------------------------------------------------
# Jittered ranges rather than fixed sleeps. The previous code used a bare
# time.sleep(5) after navigation in most places, which is both slower than
# needed and perfectly periodic.

@dataclass(frozen=True)
class PacingProfile:
    """Seconds. Each is a (low, high) range sampled uniformly."""
    after_nav: tuple = (3.0, 6.0)
    between_scrolls: tuple = (1.8, 3.5)
    between_posts: tuple = (0.8, 2.0)
    before_retry: tuple = (2.0, 4.0)


DEFAULT_PACING = PacingProfile()


def jittered(span: tuple) -> float:
    """Sample a delay from a (low, high) range."""
    low, high = span
    return random.uniform(low, high)


# --- Daily budgets ---------------------------------------------------------
# Per connected account, per UTC day. These are intentionally conservative:
# the agent loop runs every 60s, which would otherwise mean ~1440 hits/day on
# a single account. Enforced in base.ScrapeContext.pace().

DAILY_BUDGETS: Dict[str, Dict[str, int]] = {
    "twitter":   {"requests": 120, "posts": 600},
    "facebook":  {"requests": 60,  "posts": 300},
    "instagram": {"requests": 60,  "posts": 300},
    "linkedin":  {"requests": 40,  "posts": 200},
    "reddit":    {"requests": 500, "posts": 2000},   # public JSON API, no account
}


def budget_for(platform: str) -> Dict[str, int]:
    return DAILY_BUDGETS.get(platform.lower(), {"requests": 60, "posts": 300})
