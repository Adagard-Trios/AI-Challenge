"""
backend/scripts/scraper_selftest.py
Are the scrapers still working?

Run this when the social feed goes quiet, after a platform redesign, or before
trusting a run:

    cd backend && python scripts/scraper_selftest.py --platform all

Nothing else in the project can answer that question. The unit tests cover
registration, wiring and the status vocabulary, but not one of them would fail
if X renamed ``data-testid='tweetText'`` tomorrow -- and the scrapers key on
platform markup, which changes without notice.

What this reports that a post count cannot: **per-selector hit rates**. The
distinction matters because the two failures look identical from outside:

    twitter    OK    5 posts | TWEET 5  TEXT 5  USER 5
    linkedin   WARN  0 posts | POST 8   TEXT 0  POSTER 8   <- TEXT rotted
    facebook   FAIL  0 posts | MESSAGE 0                   <- page/layout gone

The middle line is the case worth having a tool for. Eight posts rendered and
none could be read; before ``containers_seen`` landed in base.py that returned
status "ok" with zero posts, indistinguishable from a quiet day.

It works by wrapping ``page.locator`` so every selector the scrapers use is
counted as they use it. No scraper code is involved, so this cannot drift out of
sync with what actually runs.

This drives real sessions against real accounts. It is paced by the same rate
limiter and daily budget as a normal run, but it is not free -- keep --max-items
small.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Run as a script from anywhere: backend/ has to be importable for `src.*`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.scrapers import registry  # noqa: E402
from src.scrapers.base import ScrapeResult, browser_session  # noqa: E402
from src.scrapers.credentials import get_credential  # noqa: E402
from src.scrapers.hygiene import LaunchProfile  # noqa: E402

logger = logging.getLogger("selftest")

# The post container each platform renders; what a fixture captures.
CONTAINER_SELECTOR = {
    "twitter": "article[data-testid='tweet']",
    "linkedin": "div.feed-shared-update-v2, li.artdeco-card",
    "facebook": "div[data-ad-preview='message']",
    "instagram": "article",
}

PLATFORM_SCRAPERS = {
    "twitter": ("scrape_twitter", "Sri Lanka"),
    "linkedin": ("scrape_linkedin", "Sri Lanka business"),
    "facebook": ("scrape_facebook", "Sri Lanka"),
    "instagram": ("scrape_instagram", "srilanka"),
}

# Selectors worth naming in the report, per module. Anything else the scrapers
# touch still gets counted; these just get friendly labels.
LABELS = {
    "article[data-testid='tweet']": "TWEET",
    "div[data-testid='tweetText']": "TEXT",
    "div[data-testid='User-Name']": "USER",
    "div.feed-shared-update-v2, li.artdeco-card": "POST",
    "div.update-components-text span.break-words, span.break-words": "TEXT",
    "span.update-components-actor__name span[dir='ltr']": "POSTER",
    "div[data-ad-preview='message']": "MESSAGE",
    "a[href*='/p/'], a[href*='/reel/']": "POST_LINK",
    "article h1, article span": "CAPTION",
}


class _CountingLocator:
    """Passes everything through, counting nested .locator() calls."""

    def __init__(self, locator, tally: Dict[str, int]):
        self._locator = locator
        self._tally = tally

    def locator(self, selector, **kwargs):
        child = self._locator.locator(selector, **kwargs)
        _record(self._tally, selector, child)
        return _CountingLocator(child, self._tally)

    def all(self):
        return [_CountingLocator(x, self._tally) for x in self._locator.all()]

    @property
    def first(self):
        return _CountingLocator(self._locator.first, self._tally)

    def __getattr__(self, name):
        return getattr(self._locator, name)


class _CountingPage:
    """Wraps a Playwright Page, counting every selector the scrapers query."""

    def __init__(self, page, tally: Dict[str, int]):
        self._page = page
        self._tally = tally

    def locator(self, selector, **kwargs):
        loc = self._page.locator(selector, **kwargs)
        _record(self._tally, selector, loc)
        return _CountingLocator(loc, self._tally)

    def wait_for_selector(self, selector, **kwargs):
        try:
            return self._page.wait_for_selector(selector, **kwargs)
        finally:
            # Record even on timeout: a selector that never resolves is exactly
            # what we are here to find.
            self._tally.setdefault(selector, 0)

    def __getattr__(self, name):
        return getattr(self._page, name)


def _record(tally: Dict[str, int], selector: str, locator) -> None:
    """Keep the high-water mark; scrapers re-query as they scroll."""
    try:
        n = locator.count()
    except Exception:
        n = 0
    tally[selector] = max(tally.get(selector, 0), n)


def _label(selector: str) -> str:
    return LABELS.get(selector, selector if len(selector) <= 34 else selector[:31] + "...")


FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent
    / "backend" / "tests" / "fixtures" / "scrapers"
)

# Replaces every text node in a captured fixture. Selector tests care about
# structure, not content, and a logged-in social feed is full of other people's
# private posts, names and DMs. Redacting at capture time means a fixture can
# never carry any of that into the repository.
#
# Long enough to clear the scrapers' MIN_TEXT_LEN guard, so extraction still
# behaves the way it would on a real post.
REDACTED = "REDACTED SAMPLE POST TEXT FOR SELECTOR TESTING ONLY"

_REDACT_JS = """
(container) => {
  const KEEP_ATTRS = new Set([
    'data-testid', 'data-ad-preview', 'class', 'role', 'dir', 'href', 'aria-label'
  ]);
  const clone = container.cloneNode(true);
  const walk = (node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      if (node.textContent.trim()) node.textContent = '__REDACTED__';
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    for (const attr of [...node.attributes]) {
      if (!KEEP_ATTRS.has(attr.name)) {
        node.removeAttribute(attr.name);
      } else if (attr.name === 'href') {
        // Keep the shape a selector matches on, drop the identity.
        node.setAttribute('href', attr.value.replace(/[^/]+$/, 'redacted'));
      } else if (attr.name === 'aria-label') {
        node.setAttribute('aria-label', '0');
      }
    }
    for (const child of [...node.childNodes]) walk(child);
  };
  walk(clone);
  return clone.outerHTML;
}
"""


def capture_fixture(page, container_selector: str, platform: str, limit: int = 3) -> Optional[Path]:
    """
    Save redacted post markup so selector tests can run offline.

    Structure and the attributes selectors key on are preserved; every text node
    becomes a placeholder. Nothing identifying survives.
    """
    try:
        containers = page.locator(container_selector)
        n = min(containers.count(), limit)
        if not n:
            return None

        parts = [
            containers.nth(i).evaluate(_REDACT_JS).replace("__REDACTED__", REDACTED)
            for i in range(n)
        ]
    except Exception as exc:
        logger.warning("[selftest] %s: could not capture fixture: %s", platform, exc)
        return None

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    path = FIXTURE_DIR / f"{platform}.html"
    path.write_text(
        "<!-- Captured by `python -m connector.selftest --capture`.\n"
        "     Every text node is replaced with a placeholder at capture time;\n"
        "     only structure and the attributes selectors match on remain.\n"
        "     Recapture after a platform redesign. -->\n"
        f"<div id=\"fixture-root\">\n{chr(10).join(parts)}\n</div>\n",
        encoding="utf-8",
    )
    return path


def probe(platform: str, value: str, max_items: int, capture: bool = False) -> dict:
    """Run one scraper with instrumentation and report what matched."""
    spec = registry.REGISTRY.get(PLATFORM_SCRAPERS[platform][0])
    credential = get_credential(platform)

    if credential is None:
        return {"platform": platform, "verdict": "SKIP",
                "reason": "no account connected", "selectors": {}, "posts": 0}
    if credential.is_expired:
        return {"platform": platform, "verdict": "SKIP",
                "reason": "session expired -- reconnect", "selectors": {}, "posts": 0}

    tally: Dict[str, int] = {}
    profile = LaunchProfile.MOBILE if platform == "instagram" else LaunchProfile.DESKTOP

    try:
        with browser_session(credential, profile=profile) as ctx:
            ctx.page = _CountingPage(ctx.page, tally)
            result = spec.fn(ctx, value, max_items=max_items)
            if not isinstance(result, ScrapeResult):
                result = ScrapeResult(posts=list(result or []))

            if capture:
                container = CONTAINER_SELECTOR.get(platform)
                saved = container and capture_fixture(ctx.page, container, platform)
                if saved:
                    print(f"             -> fixture written: {saved}")
    except Exception as exc:
        return {"platform": platform, "verdict": "FAIL", "reason": str(exc)[:120],
                "selectors": tally, "posts": 0}

    posts = len(result.posts)
    containers = getattr(ctx, "containers_seen", 0)

    if result.status in ("challenged", "expired"):
        verdict, reason = "BLOCKED", result.reason or result.status
    elif posts:
        # Posts came back, but check whether any field is systematically empty.
        blank = [
            field for field in ("text", "poster")
            if all(not p.get(field) or p.get(field) == "Unknown" for p in result.posts)
        ]
        verdict = "WARN" if blank else "OK"
        reason = f"every post has an empty {'/'.join(blank)}" if blank else ""
    elif containers:
        verdict = "WARN"
        reason = f"{containers} containers rendered, none parsed -- selector rot"
    else:
        verdict = "FAIL"
        reason = result.reason or "nothing rendered"

    return {"platform": platform, "verdict": verdict, "reason": reason,
            "selectors": tally, "posts": posts, "containers": containers,
            "status": result.status}


def render(report: dict) -> str:
    sels = report.get("selectors") or {}
    # Zero-hit selectors first: those are the story.
    ordered = sorted(sels.items(), key=lambda kv: (kv[1] != 0, _label(kv[0])))
    detail = "  ".join(f"{_label(s)} {n}" for s, n in ordered) or "(none queried)"

    line = (f"  {report['platform']:<10} {report['verdict']:<7} "
            f"{report['posts']:>3} posts | {detail}")
    if report.get("reason"):
        line += f"\n             -> {report['reason']}"
    return line


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check whether the Playwright scrapers still match their platforms."
    )
    parser.add_argument("--platform", default="all",
                        choices=["all", *PLATFORM_SCRAPERS])
    parser.add_argument("--max-items", type=int, default=5,
                        help="posts per platform; keep this small (default 5)")
    parser.add_argument("--query", default=None,
                        help="override the search term for the chosen platform")
    parser.add_argument("--capture", action="store_true",
                        help="save redacted post markup as an offline "
                             "selector-test fixture")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    # Read the same sessions everything else does.
    #
    # probe() calls get_credential(), whose default store hands out nothing --
    # correct for a server, useless here. Without this the tool reports
    # "no account connected" for every platform even when accounts are
    # connected, which is the most misleading possible answer from a tool whose
    # entire job is telling you whether collection works.
    #
    # The backend installs this at startup; a standalone CLI run has to do it
    # for itself.
    try:
        from src.social.credential_bridge import install as _install_sessions

        _install_sessions()
    except Exception as exc:  # noqa: BLE001
        print(f"  ! could not open the local session store: {exc}")

    targets = list(PLATFORM_SCRAPERS) if args.platform == "all" else [args.platform]

    print(f"\nScraper self-test -- {args.max_items} posts per platform\n")
    reports = []
    for platform in targets:
        _, default_query = PLATFORM_SCRAPERS[platform]
        report = probe(platform, args.query or default_query, args.max_items,
                       capture=args.capture)
        reports.append(report)
        print(render(report))

    bad = [r for r in reports if r["verdict"] in ("WARN", "FAIL", "BLOCKED")]
    checked = [r for r in reports if r["verdict"] != "SKIP"]

    print()
    if not checked:
        print("  No accounts connected -- nothing was checked.")
        return 2
    if bad:
        print(f"  {len(bad)} of {len(checked)} platform(s) need attention.")
        print("  A selector showing 0 above is the one to fix.")
        return 1
    print(f"  All {len(checked)} connected platform(s) healthy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
