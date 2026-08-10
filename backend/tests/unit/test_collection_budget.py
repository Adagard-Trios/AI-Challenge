"""
The daily collection budget, made visible.

scrapers/hygiene.py caps each connected account per UTC day -- 120 requests for
X/Twitter, 60 for Facebook and Instagram, 40 for LinkedIn. Those caps are the
main thing standing between a personal account and a restriction, and they were
enforced in complete silence: a user near a cap saw collection return fewer
posts and then stop, with `budget_exhausted` visible only in a local connector
log. "Why did it stop collecting?" had no answer anywhere in the interface.

The user asked for accounts that "never get banned". That cannot be promised by
any design -- automated collection breaches all four platforms' terms whatever
the mechanism. What can be delivered is this: the person whose account it is can
see how hard it is being worked, in time to do something about it.

The one rule these tests exist to hold: an unreported budget must never render
as zero consumption. Showing 0/120 when the real figure is 118/120 is worse
than showing nothing, because it invites exactly the extra collection that
triggers the restriction.
"""

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
REPO_ROOT = PROJECT_ROOT.parent
for path in (str(PROJECT_ROOT), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)


# --- the counter itself -----------------------------------------------------

def test_snapshot_reports_zero_for_an_account_that_has_not_run():
    from src.scrapers.base import budget_snapshot, reset_budgets

    reset_budgets()
    snap = budget_snapshot("user:linkedin", "linkedin")

    assert snap["requests_used"] == 0
    assert snap["requests_cap"] == 40      # DAILY_BUDGETS["linkedin"]
    assert snap["exhausted"] is False


def test_asking_about_a_budget_does_not_start_charging_one():
    """
    A read must not create a counter. If it did, opening the settings page
    would itself consume budget -- and the number shown would be caused by
    looking at it.
    """
    from src.scrapers import base

    base.reset_budgets()
    base.budget_snapshot("user:twitter", "twitter")

    assert base._budgets == {}, "reading a snapshot created a budget entry"


def test_snapshot_tracks_real_consumption():
    """
    Charges through the real path rather than poking the in-process dict.

    This test used to set base._budget(...).requests directly. That stopped
    describing reality once the counters could live in Redis: with a shared
    backend the snapshot reads the shared counter, so a test writing to the
    local one asserted against a number the code no longer consults. Charging
    the way the scrapers do exercises whichever backend is active, which is the
    point -- the two must agree.
    """
    from src.scrapers import base

    base.reset_budgets()

    def charge(field, n):
        # _charge returns None when there is no shared backend; fall back to
        # the in-process counter exactly as pace()/count_posts() do.
        if base._charge("user:linkedin", field, n) is None:
            setattr(base._budget("user:linkedin"), field,
                    getattr(base._budget("user:linkedin"), field) + n)

    charge("requests", 34)
    charge("posts", 120)

    snap = base.budget_snapshot("user:linkedin", "linkedin")
    assert snap["requests_used"] == 34
    assert snap["posts_used"] == 120
    assert snap["exhausted"] is False

    charge("requests", 6)   # 34 + 6 = 40, the linkedin cap
    assert base.budget_snapshot("user:linkedin", "linkedin")["exhausted"] is True

    base.reset_budgets()


def test_yesterdays_counter_does_not_leak_into_today():
    """
    Budgets reset at UTC midnight. Yesterday's 39/40 shown as today's would
    send someone hunting a problem that reset hours ago.
    """
    from src.scrapers import base

    base.reset_budgets()
    base._budgets["user:linkedin"] = base._DailyBudget(
        day=date.today() - timedelta(days=1), requests=39, posts=199,
    )

    snap = base.budget_snapshot("user:linkedin", "linkedin")
    assert snap["requests_used"] == 0
    assert snap["exhausted"] is False


# --- the connector reports it ----------------------------------------------

def test_every_account_row_carries_its_budget():
    """
    The dashboard renders a bar per account, so the budget has to ride along
    with the account listing rather than needing a second call. Previously the
    connector attached it to each status push; the backend now assembles it
    directly.
    """
    import ast

    source = (PROJECT_ROOT / "src" / "social" / "service.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "accounts"
    )
    body = ast.get_source_segment(source, fn) or ""
    assert '"budget"' in body, "account rows carry no budget"
    assert "self._budget(" in body


def test_a_budget_failure_never_breaks_the_account_listing():
    """
    Reporting how much budget is left is strictly less important than showing
    the accounts at all.
    """
    import ast

    source = (PROJECT_ROOT / "src" / "social" / "service.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_budget"
    )
    body = ast.get_source_segment(source, fn) or ""
    assert "except" in body and "return None" in body, (
        "_budget can raise into the account listing"
    )


# --- the server never invents one -------------------------------------------

class _FakeConn:
    """Mirrors the SocialConnection columns the serialiser reads."""

    def __init__(self, **kw):
        self.budget_day = kw.get("budget_day")
        self.budget_requests_used = kw.get("budget_requests_used")
        self.budget_requests_cap = kw.get("budget_requests_cap")
        self.budget_posts_used = kw.get("budget_posts_used")
        self.budget_posts_cap = kw.get("budget_posts_cap")


def _budget_out(conn):
    """
    The serialiser, exercised without standing up the whole app.

    Defined as a closure inside list_connections, so it is reached by parsing
    rather than importing -- importing main binds the auth layer to a database
    and breaks whichever test module runs next.
    """
    import ast

    source = (PROJECT_ROOT / "auth" / "routes.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_budget_out":
            namespace: dict = {
                "Optional": __import__("typing").Optional,
                "datetime": datetime,
                "timezone": timezone,
                # Only referenced as a parameter annotation, which Python
                # evaluates at definition time. _FakeConn stands in for it.
                "SocialConnection": _FakeConn,
            }
            exec(compile(ast.Module(body=[node], type_ignores=[]), "<b>", "exec"), namespace)
            return namespace["_budget_out"](conn)

    raise AssertionError("auth/routes.py no longer defines _budget_out")


def test_an_unreported_budget_is_null_not_zero():
    """
    The rule this file exists for. 0/120 is a claim that nothing has been
    spent; null is the truth, which is that nobody said.
    """
    assert _budget_out(_FakeConn()) is None


def test_a_stale_report_is_null_not_yesterdays_figures():
    assert _budget_out(_FakeConn(
        budget_day="2020-01-01",
        budget_requests_used=39, budget_requests_cap=40,
    )) is None


def test_a_current_report_is_rendered_with_headroom():
    today = datetime.now(timezone.utc).date().isoformat()

    out = _budget_out(_FakeConn(
        budget_day=today,
        budget_requests_used=34, budget_requests_cap=40,
        budget_posts_used=120, budget_posts_cap=200,
    ))

    assert out is not None
    assert out["requests_remaining"] == 6
    assert out["fraction_used"] == pytest.approx(0.85)
    assert out["exhausted"] is False


def test_a_spent_budget_says_so():
    today = datetime.now(timezone.utc).date().isoformat()

    out = _budget_out(_FakeConn(
        budget_day=today,
        budget_requests_used=40, budget_requests_cap=40,
    ))
    assert out["exhausted"] is True
    assert out["requests_remaining"] == 0


# --- the promise that cannot be made ----------------------------------------

def test_the_ui_does_not_promise_that_accounts_will_never_be_restricted():
    """
    "Never gets banned" is not deliverable by any architecture -- automated
    collection breaches every one of these platforms' terms regardless of
    mechanism. The interface must not imply otherwise, because a user who
    believes it will collect harder than someone who knows the real risk.
    """
    card = (
        REPO_ROOT / "frontend" / "app" / "components" / "settings"
        / "SocialAccounts.tsx"
    )
    if not card.exists():
        pytest.skip("frontend not present")

    text = card.read_text(encoding="utf-8").lower()
    for claim in ("never be banned", "never gets banned", "cannot be banned",
                  "guaranteed safe", "100% safe"):
        assert claim not in text, f"the UI promises {claim!r}, which is not true"
