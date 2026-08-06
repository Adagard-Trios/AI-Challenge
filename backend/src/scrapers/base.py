"""
src/scrapers/base.py
The one place a browser is launched, and the one place pacing is enforced.

Replaces 24 scattered ``chromium.launch()`` sites that disagreed about launch
args, user agent, viewport and error handling. Because every scraper goes
through ``browser_session``, pacing and challenge detection cannot be bypassed
by forgetting to add them to a new scraper.

Scrapers written against this contain no session handling, no launch config, no
rate limiting and no status bookkeeping -- they navigate and extract, and raise
on trouble.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, Iterator, List, Optional

from ..utils.rate_limiter import get_rate_limiter
from . import challenge as challenge_mod
from .credentials import SocialCredential
from .hygiene import (
    BASE_LAUNCH_ARGS,
    BLOCKED_RESOURCE_TYPES,
    DEFAULT_PACING,
    PROFILES,
    WEBDRIVER_INIT_SCRIPT,
    LaunchProfile,
    budget_for,
    jittered,
)

logger = logging.getLogger("Roger.scrapers.base")


class BudgetExhausted(Exception):
    """Daily cap for this account reached. Not an error -- stop cleanly."""


@dataclass
class _DailyBudget:
    """
    In-process daily counters.

    Deliberately simple: the connector is a single long-lived process, so this
    is sufficient there. The server does not scrape at all. If collection ever
    moves somewhere multi-process, this needs to become a shared counter --
    it is isolated here so that change is one class.
    """
    day: date
    requests: int = 0
    posts: int = 0


_budgets: Dict[str, _DailyBudget] = {}


def _budget(account_key: str) -> _DailyBudget:
    today = date.today()
    b = _budgets.get(account_key)
    if b is None or b.day != today:
        b = _DailyBudget(day=today)
        _budgets[account_key] = b
    return b


def reset_budgets() -> None:
    """Tests."""
    _budgets.clear()


def budget_snapshot(account_key: str, platform: str) -> Dict[str, object]:
    """
    How much of today's collection budget this account has spent.

    The caps have always been enforced and never reported. A user therefore had
    no way to know they were approaching one: collection simply produced fewer
    posts, then stopped, with `budget_exhausted` visible only in a connector log
    nobody reads. "Why did it stop collecting?" had no answer in the interface.

    Read-only, and it deliberately does not create a counter for an account that
    has not run today -- asking about a budget should not start charging one.
    """
    caps = budget_for(platform)
    today = date.today()
    entry = _budgets.get(account_key)

    # A stale entry is last UTC day's, which is spent-nothing for today.
    used_requests = entry.requests if entry and entry.day == today else 0
    used_posts = entry.posts if entry and entry.day == today else 0

    return {
        "platform": platform,
        "day": today.isoformat(),
        "requests_used": used_requests,
        "requests_cap": caps["requests"],
        "posts_used": used_posts,
        "posts_cap": caps["posts"],
        "exhausted": used_requests >= caps["requests"],
    }


@dataclass
class ScrapeResult:
    """
    Uniform return shape.

    ``posts`` keeps exactly the keys the existing scrapers emit, so
    ``db_manager.extract_post_data`` needs no changes: source, poster, text,
    and optionally timestamp, url, likes, retweets, replies.

    ``rotated_state`` carries the session as it stood at the end of the run, so
    the caller can write refreshed cookies back. It is excluded from as_dict()
    -- it is credential material and must never reach a JSON payload, a log
    line, or an LLM's context.
    """
    posts: List[dict] = field(default_factory=list)
    status: str = "ok"          # ok|expired|challenged|rate_limited|budget_exhausted|error
    reason: Optional[str] = None
    platform: Optional[str] = None
    rotated_state: Optional[dict] = field(default=None, repr=False)

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "platform": self.platform,
            "reason": self.reason,
            "count": len(self.posts),
            "results": self.posts,
        }


class ScrapeContext:
    """Handed to every scraper. The only surface they need."""

    def __init__(self, page, credential: SocialCredential, context):
        self.page = page
        self.credential = credential
        self._context = context
        self.platform = credential.platform
        self._account_key = credential.account_key or f"anon:{credential.platform}"
        self._posts_seen = 0
        # Highest number of post containers seen on the page during this run.
        # See note_containers().
        self.containers_seen = 0

    # -- pacing ------------------------------------------------------------

    # -- selector health ---------------------------------------------------

    def note_containers(self, n: int) -> None:
        """
        Record how many post containers the page actually rendered.

        This is what separates "the search found nothing" from "the search found
        plenty and our text selector no longer matches any of it". Without it,
        partial selector rot is invisible: the container selector still hits, the
        inner selector does not, every post is dropped by the `if not text`
        guard, and the scraper returns status="ok" with zero posts -- identical
        to a genuinely empty result. run_scrape() turns that case into an error.
        """
        self.containers_seen = max(self.containers_seen, int(n or 0))

    def pace(self, kind: str = "nav") -> None:
        """
        Wait our turn, then apply a human-scale jittered delay.

        Charges the daily request budget for navigations. Raises
        BudgetExhausted when the account has done enough for one day.
        """
        if kind == "nav":
            b = _budget(self._account_key)
            cap = budget_for(self.platform)["requests"]
            if b.requests >= cap:
                raise BudgetExhausted(
                    f"{self.platform}: daily request cap reached ({b.requests}/{cap})"
                )
            b.requests += 1

        limiter = get_rate_limiter()
        with limiter.acquire(self.platform, account_key=self._account_key):
            pass  # acquiring is the pacing; the work happens after we return

        span = {
            "nav": DEFAULT_PACING.after_nav,
            "scroll": DEFAULT_PACING.between_scrolls,
            "post": DEFAULT_PACING.between_posts,
        }.get(kind, DEFAULT_PACING.between_posts)
        time.sleep(jittered(span))

    def count_posts(self, n: int) -> None:
        """Charge the daily post budget. Caps output rather than erroring."""
        b = _budget(self._account_key)
        b.posts += n
        self._posts_seen += n

    def posts_remaining(self) -> int:
        b = _budget(self._account_key)
        return max(0, budget_for(self.platform)["posts"] - b.posts)

    # -- health ------------------------------------------------------------

    def assert_healthy(self) -> None:
        """Raise SessionExpired / ChallengeDetected if the platform pushed back."""
        challenge_mod.enforce(self.page, self.platform)

    # -- navigation --------------------------------------------------------

    def goto(self, url: str, *, timeout_ms: int = 60000, wait_until: str = "domcontentloaded"):
        """Paced navigation followed by a health check."""
        self.pace("nav")
        resp = self.page.goto(url, timeout=timeout_ms, wait_until=wait_until)
        self.assert_healthy()
        return resp

    def scroll(self, times: int = 1, pixels: int = 2200) -> None:
        for _ in range(times):
            self.pace("scroll")
            try:
                self.page.mouse.wheel(0, pixels)
            except Exception:
                break

    # -- session -----------------------------------------------------------

    def persist_state(self) -> Optional[dict]:
        """
        Return the session as it now stands, so rotated cookies can be saved.

        Nothing in the original codebase did this, so every refreshed ct0 /
        lidc / sessionid was discarded and the stored session drifted stale
        until it died. Writing it back is the single highest-leverage change
        for session longevity -- and it is exactly what an ordinary browser
        does.
        """
        try:
            return self._context.storage_state()
        except Exception as exc:
            logger.warning("[base] %s: could not read storage_state: %s", self.platform, exc)
            return None


@contextmanager
def browser_session(
    credential: SocialCredential,
    *,
    profile: LaunchProfile = LaunchProfile.DESKTOP,
    headless: bool = True,
    block_media: bool = True,
) -> Iterator[ScrapeContext]:
    """
    Launch a browser carrying ``credential``, yield a ScrapeContext, clean up.

    The storage_state is passed as a **dict**, so decrypted cookies exist only
    in memory and never touch disk.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Playwright is not installed. Collection runs in the connector, "
            "not on the server -- see DEPLOY.md."
        ) from exc

    ctx_profile = PROFILES[profile]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, args=list(BASE_LAUNCH_ARGS))
        try:
            context = browser.new_context(
                storage_state=credential.storage_state,   # dict, not a path
                **ctx_profile.as_context_kwargs(),
            )
            try:
                context.add_init_script(WEBDRIVER_INIT_SCRIPT)

                if block_media:
                    # Images/fonts/media are the bulk of a feed's resident
                    # memory and we never read them.
                    def _route(route):
                        try:
                            if route.request.resource_type in BLOCKED_RESOURCE_TYPES:
                                route.abort()
                            else:
                                route.continue_()
                        except Exception:
                            pass
                    context.route("**/*", _route)

                page = context.new_page()
                page.set_default_timeout(45000)

                yield ScrapeContext(page, credential, context)
            finally:
                try:
                    context.close()
                except Exception:
                    pass
        finally:
            try:
                browser.close()
            except Exception:
                pass


def _flag_extraction_failure(result: ScrapeResult, ctx: ScrapeContext) -> None:
    """
    Turn "rendered N posts, extracted 0" into an error.

    A scraper reports status="error" when its *container* selector matches
    nothing, so a wholesale layout change is caught. Partial rot was not: if the
    container still matches and only the inner text selector has changed, every
    post is dropped by the scrapers' `if not text: continue` guard and the run
    ends with the default status="ok" and an empty list -- which reads exactly
    like a search that legitimately had no results. That is the difference
    between "quiet news day" and "we stopped being able to read X", and the feed
    showed them identically.

    A genuinely empty page leaves containers_seen at 0 and stays "ok".
    """
    if result.status != "ok" or result.posts:
        return

    # getattr, not attribute access: this runs on the success path of every
    # scrape, and a guard that raises on an unexpected context object would turn
    # a good run into an error. Absent means "no evidence", which means no flag.
    containers = getattr(ctx, "containers_seen", 0) or 0
    if containers <= 0:
        return

    result.status = "error"
    result.reason = (
        f"{getattr(ctx, 'platform', 'scraper')}: page rendered {containers} post container(s) "
        "but none could be parsed -- the post selectors have almost certainly "
        "changed. Run `python -m connector.selftest` to see which one."
    )
    logger.error("[base] %s", result.reason)


def run_scrape(credential: SocialCredential, fn, *args, **kwargs) -> ScrapeResult:
    """
    Execute a scraper and translate every outcome into a ScrapeResult.

    The status contract, which the tool layer surfaces to the agent and the UI:

      challenged      -> platform pushed back. Hard stop, zero retries.
      expired         -> session dead. User must reconnect.
      budget_exhausted-> daily cap reached. Not an error.
      error           -> anything else; safe to try again later.

    Also promotes the one silent failure the status contract could not express:
    a page that rendered post containers from which nothing could be extracted.
    See _flag_extraction_failure().
    """
    platform = credential.platform
    profile = LaunchProfile.MOBILE if platform == "instagram" else LaunchProfile.DESKTOP

    try:
        with browser_session(credential, profile=profile) as ctx:
            result = fn(ctx, *args, **kwargs)
            if not isinstance(result, ScrapeResult):
                result = ScrapeResult(posts=list(result or []))
            result.platform = platform

            # Capture the session as it now stands, so rotated cookies can be
            # written back. Platforms refresh values like ct0, lidc and
            # sessionid during normal use; the original code never read them
            # back, so every refresh was discarded and the stored session drifted
            # stale until it died. Persisting it is what an ordinary browser
            # does, and it is the single biggest factor in how long a connected
            # account keeps working.
            result.rotated_state = ctx.persist_state()
            _flag_extraction_failure(result, ctx)
            return result

    except challenge_mod.ChallengeDetected as exc:
        logger.error("[base] %s CHALLENGED -- stopping this account: %s", platform, exc)
        return ScrapeResult(status="challenged", reason=str(exc), platform=platform)

    except challenge_mod.SessionExpired as exc:
        logger.warning("[base] %s session expired: %s", platform, exc)
        return ScrapeResult(status="expired", reason=str(exc), platform=platform)

    except BudgetExhausted as exc:
        logger.info("[base] %s: %s", platform, exc)
        return ScrapeResult(status="budget_exhausted", reason=str(exc), platform=platform)

    except Exception as exc:
        logger.exception("[base] %s scrape failed", platform)
        return ScrapeResult(status="error", reason=str(exc), platform=platform)
