"""
Partial selector rot must not report success.

A scraper already returns status="error" when its *container* selector matches
nothing, so a wholesale layout change is caught. The gap was partial rot: the
container still matches, only the inner text selector has changed, every post is
dropped by the scrapers' `if not text: continue` guard, and the run ends with the
default status="ok" and zero posts.

That is indistinguishable from a search that legitimately found nothing -- so
"we can no longer read X" and "quiet news day" looked identical in the feed, for
as long as it took someone to notice the social domain had gone silent.
"""

import ast
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SCRAPERS = PROJECT_ROOT / "src" / "scrapers"


def _ctx(platform="twitter", containers=0):
    """A ScrapeContext with no browser behind it."""
    from src.scrapers.base import ScrapeContext
    from src.scrapers.credentials import SocialCredential

    cred = SocialCredential(
        platform=platform,
        storage_state={"cookies": []},
        account_key=f"test:{platform}",
    )
    ctx = ScrapeContext(page=None, credential=cred, context=None)
    if containers:
        ctx.note_containers(containers)
    return ctx


# --- the rule --------------------------------------------------------------

def test_rendered_posts_but_extracted_none_is_an_error():
    """THE regression. 20 tweets on screen, 0 parsed -> must not read as ok."""
    from src.scrapers.base import ScrapeResult, _flag_extraction_failure

    result = ScrapeResult(posts=[], status="ok", platform="twitter")
    _flag_extraction_failure(result, _ctx("twitter", containers=20))

    assert result.status == "error", (
        "the page rendered 20 post containers and yielded nothing; that is "
        "selector rot, not an empty search"
    )
    assert "20" in result.reason
    assert "selector" in result.reason.lower()


def test_genuinely_empty_search_stays_ok():
    """No containers rendered means the query really had no results."""
    from src.scrapers.base import ScrapeResult, _flag_extraction_failure

    result = ScrapeResult(posts=[], status="ok", platform="twitter")
    _flag_extraction_failure(result, _ctx("twitter", containers=0))

    assert result.status == "ok"
    assert result.reason is None


def test_partial_extraction_is_not_flagged():
    """20 containers, 3 parsed is a working scraper with noisy input."""
    from src.scrapers.base import ScrapeResult, _flag_extraction_failure

    result = ScrapeResult(posts=[{"text": "a"}] * 3, status="ok", platform="twitter")
    _flag_extraction_failure(result, _ctx("twitter", containers=20))

    assert result.status == "ok"


@pytest.mark.parametrize("status", ["challenged", "expired", "budget_exhausted", "error"])
def test_a_real_status_is_never_overwritten(status):
    """
    Challenge and expiry are more actionable than 'selectors changed' and must
    survive -- a challenged session also renders containers it cannot parse.
    """
    from src.scrapers.base import ScrapeResult, _flag_extraction_failure

    result = ScrapeResult(posts=[], status=status, reason="original",
                          platform="twitter")
    _flag_extraction_failure(result, _ctx("twitter", containers=20))

    assert result.status == status
    assert result.reason == "original"


def test_note_containers_keeps_the_high_water_mark():
    """
    Scrapers re-locate containers on every scroll pass, and a later pass can
    return fewer. The peak is what says whether anything was ever there.
    """
    ctx = _ctx("twitter")
    ctx.note_containers(12)
    ctx.note_containers(3)
    ctx.note_containers(0)

    assert ctx.containers_seen == 12


def test_note_containers_tolerates_none():
    ctx = _ctx("twitter")
    ctx.note_containers(None)
    assert ctx.containers_seen == 0


# --- every scraper participates -------------------------------------------

@pytest.mark.parametrize(
    "module", ["twitter.py", "linkedin.py", "facebook.py", "instagram.py"]
)
def test_every_scraper_reports_its_container_count(module):
    """
    A scraper that never calls note_containers() can still fail silently -- the
    rule in base.py has nothing to act on.
    """
    tree = ast.parse((SCRAPERS / module).read_text(encoding="utf-8"))

    called = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "note_containers"
        for node in ast.walk(tree)
    )
    assert called, f"{module} never calls ctx.note_containers()"


def test_run_scrape_applies_the_rule():
    """The check must sit on the success path, not only be defined."""
    tree = ast.parse((SCRAPERS / "base.py").read_text(encoding="utf-8"))

    fn = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == "run_scrape"),
        None,
    )
    assert fn is not None

    called = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_flag_extraction_failure"
        for node in ast.walk(fn)
    )
    assert called, "run_scrape does not call _flag_extraction_failure"
