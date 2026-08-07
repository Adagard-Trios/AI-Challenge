"""
End-to-end: does a human opening the dashboard actually see the features?

Everything else in this suite verifies parts. Unit tests assert /api/feeds
returns entities; tsc asserts the component compiles; a grep asserts it is
imported somewhere. None of that proves anything renders. A component can be
mounted, typed, imported and unit-tested and still show nothing -- because a
401 emptied it, because a hook threw on mount, or because the panel is behind a
tab that no longer exists.

This drives a real browser and reports what is on the screen.

    # terminal 1
    cd backend && python -m uvicorn main:app --port 8000
    # terminal 2
    cd frontend && npm run start
    # terminal 3
    cd backend && python -m pytest tests/e2e -v

Skipped automatically when either server is down, so it never breaks a normal
`pytest tests/` run.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FRONTEND = "http://127.0.0.1:3000"
BACKEND = "http://127.0.0.1:8000"

pytestmark = pytest.mark.e2e


def _up(url: str) -> bool:
    try:
        import requests

        return requests.get(url, timeout=3).status_code < 500
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(scope="module")
def page():
    """One browser for the module; each test navigates fresh."""
    if not _up(FRONTEND):
        pytest.skip(f"frontend not running at {FRONTEND}")
    if not _up(f"{BACKEND}/api/status"):
        pytest.skip(f"backend not running at {BACKEND}")

    playwright = pytest.importorskip("playwright.sync_api")

    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1400, "height": 1000})
        pg = ctx.new_page()

        # Console errors are the cheapest signal there is and catch most
        # "it renders but is broken" cases.
        pg.errors = []          # type: ignore[attr-defined]
        pg.on("console", lambda m: m.type == "error" and pg.errors.append(m.text))
        pg.on("pageerror", lambda e: pg.errors.append(f"uncaught: {e}"))

        yield pg
        browser.close()


def _load(page, tab: str | None = None) -> str:
    # Each test judges its own page load. The browser is module-scoped for
    # speed, so without this the error list accumulates and a later test fails
    # on something an earlier one caused -- which passes in isolation and fails
    # in the suite, the most confusing shape a test failure can take.
    page.errors.clear()
    page.goto(FRONTEND, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    if tab:
        el = page.get_by_role("tab", name=tab)
        if el.count():
            el.first.click()
            page.wait_for_timeout(1200)
    return " ".join(page.inner_text("body").split())


# --- the app mounts ---------------------------------------------------------

def test_the_dashboard_mounts(page):
    body = _load(page)
    assert page.title(), "no page title -- the app did not mount"
    assert len(body) > 400, f"page rendered almost nothing ({len(body)} chars)"


def test_no_uncaught_errors_on_load(page):
    _load(page)
    # Filter noise the app cannot control: a backend that is mid-cycle returns
    # 404s for endpoints with no data yet, and those surface as console errors.
    real = [
        e for e in page.errors
        if "favicon" not in e.lower() and "404" not in e
    ]
    assert not real, f"console errors on load: {real[:3]}"


# --- the tabs that were asked for -------------------------------------------

def test_every_expected_tab_is_present(page):
    _load(page)
    tabs = [t.strip().upper() for t in page.get_by_role("tab").all_inner_texts()]

    for expected in ("OVERVIEW", "INTEL FEED", "STORIES", "ANOMALIES", "ACCOUNTS"):
        assert any(expected in t for t in tabs), (
            f"{expected} tab missing. Found: {tabs}"
        )


# --- risk indices and their drivers -----------------------------------------

def test_risk_indices_render_with_drilldown(page):
    """
    These were computed on every cycle and rendered nowhere -- they existed
    only in the TypeScript type.
    """
    body = _load(page, "OVERVIEW")

    assert "RISK INDICES" in body.upper(), "the risk indices card is not on screen"
    assert "Logistics friction" in body
    assert "Compliance volatility" in body
    assert "Market instability" in body

    # The drill-down control is what makes a score interrogable.
    assert "Why " in body and "%?" in body, (
        "no 'Why NN%?' drill-down -- an index with no drivers is a number with "
        "authority and no accountability"
    )


def test_regulatory_activity_shows_a_count_not_a_percentage(page):
    """
    It is `len(political_scores) * 0.1` -- a story tally with a scaling factor.
    Rendering it as a percentage beside genuinely scored indices is the exact
    confusion the backend's provenance flag was added to prevent.
    """
    body = _load(page, "OVERVIEW")

    if "Regulatory activity" not in body:
        pytest.skip("no regulatory activity in this cycle's snapshot")

    tail = body.split("Regulatory activity", 1)[1][:120]
    assert "stor" in tail.lower(), f"not shown as a story count: {tail!r}"


# --- stories ----------------------------------------------------------------

def test_stories_panel_renders(page):
    body = _load(page, "STORIES")
    assert "ONGOING STORIES" in body.upper(), "the stories panel is not on screen"
    # Either threaded stories or the honest empty state; both are working.
    assert ("No stories yet" in body) or ("event" in body.lower())


# --- the social login fields, which is what was actually asked for ----------

def test_social_accounts_panel_is_on_the_accounts_tab(page):
    body = _load(page, "ACCOUNTS")
    assert "SOCIAL ACCOUNTS" in body.upper(), (
        "the social sign-in panel is not on screen"
    )


def test_the_old_connector_pairing_card_is_gone(page):
    """The card that produced 'Sign in to control your connector'."""
    body = _load(page, "ACCOUNTS").lower()
    assert "control your connector" not in body
    assert "pairing code" not in body


def test_signed_out_state_explains_itself(page):
    """
    The 401 used to render as an empty list. These routes store a password and
    open a browser, so they require a login by design -- but "why is this
    blank" needs an answer and a command, not silence.
    """
    body = _load(page, "ACCOUNTS")

    if "Sign in to manage social accounts" in body:
        assert "create_admin" in body, (
            "the signed-out panel does not say how to create the first account"
        )
    else:
        # Already authenticated: the credential fields must be there instead.
        assert "Password" in body


def test_it_says_where_the_browser_will_open(page):
    """
    A browser opening on a different computer than the one you are looking at
    is surprising enough to state before the button, not after.
    """
    body = _load(page, "ACCOUNTS")
    assert "machine running this server" in body


def test_collected_posts_panel_exists(page):
    """Proof the accounts work; otherwise collection ends at a DB row count."""
    body = _load(page, "ACCOUNTS")
    assert "COLLECTED POSTS" in body.upper()


# --- signing in, and the credential fields behind it ------------------------

def _admin_credentials() -> dict | None:
    """
    Read the admin login from .env rather than hardcoding one.

    An earlier version used a fixed demo account, which meant the suite either
    depended on a throwaway admin existing on every machine, or -- worse --
    documented a working password in the repo for an instance that may be
    publicly tunnelled.
    """
    import re

    env_file = PROJECT_ROOT.parent / ".env"
    if not env_file.exists():
        return None

    env = dict(re.findall(
        r"^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$",
        env_file.read_text(encoding="utf-8"), re.M,
    ))
    email = (env.get("BOOTSTRAP_ADMIN_EMAIL") or "").strip()
    password = (env.get("BOOTSTRAP_ADMIN_PASSWORD") or "").strip()
    return {"email": email, "password": password} if email and password else None


def _sign_in(page) -> bool:
    """Click Sign in and submit the form. False if the account does not exist."""
    admin = _admin_credentials()
    if admin is None:
        return False

    page.errors.clear()
    page.goto(FRONTEND, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)

    button = page.get_by_role("button", name="Sign in")
    if not button.count():
        return "Sign out" in page.inner_text("body")   # already signed in

    button.first.click()
    page.wait_for_timeout(1500)

    form = page.locator("form")
    if not form.count():
        return False
    form.locator("input[type=email]").fill(admin["email"])
    form.locator("input[type=password]").fill(admin["password"])
    form.locator("button[type=submit]").click()
    page.wait_for_timeout(4500)

    return "Sign out" in page.inner_text("body")


def test_a_sign_in_control_exists(page):
    """
    REGRESSION. RequireAuth renders the dashboard whenever auth is NOT
    enforced, so with AUTH_ENFORCED=0 -- the default, and how this runs locally
    -- the login screen was unreachable and no sign-in control existed
    anywhere. The social fields require a user by design, so they showed
    "sign in to manage social accounts" beside no way of doing it.
    """
    _load(page)
    body = page.inner_text("body")
    assert ("Sign in" in body) or ("Sign out" in body), (
        "no way to authenticate from the dashboard"
    )


def test_signing_in_actually_lands_back_on_the_dashboard(page):
    """
    REGRESSION. /login rendered Login unconditionally, so a successful login
    returned 200 and left the user staring at the same form.
    """
    if not _sign_in(page):
        pytest.skip("no usable admin in .env; run scripts/create_admin.py")

    assert page.get_by_role("tab").count() > 0, (
        "signed in but the dashboard did not render"
    )


def test_the_credential_fields_render_for_every_platform(page):
    """The thing that was actually asked for: username + password, per platform."""
    if not _sign_in(page):
        pytest.skip("no usable admin in .env; run scripts/create_admin.py")

    page.get_by_role("tab", name="ACCOUNTS").first.click()
    page.wait_for_timeout(2500)
    body = " ".join(page.inner_text("body").split())

    for platform in ("X (Twitter)", "LinkedIn", "Facebook", "Instagram"):
        assert platform in body, f"{platform} has no row"

    assert page.locator("input[type=password]").count() >= 4, (
        "fewer password fields than platforms"
    )
    assert "Save" in body and "Connect" in body


def test_each_platform_shows_its_daily_budget(page):
    """The caps that stand between a personal account and a restriction."""
    if not _sign_in(page):
        pytest.skip("no usable admin in .env; run scripts/create_admin.py")

    page.get_by_role("tab", name="ACCOUNTS").first.click()
    page.wait_for_timeout(2500)
    body = " ".join(page.inner_text("body").split())

    assert "Today's collection budget" in body or "collection budget" in body
    # Real per-platform caps from hygiene.py, not placeholders.
    assert "/120" in body and "/40" in body, (
        "budget bars are not showing the real per-platform caps"
    )


# --- the model cards are honest ---------------------------------------------

def test_unavailable_models_explain_themselves(page):
    """
    Weather, currency and stock are TensorFlow models. Whether they run depends
    on the host, but a card must never be a silent spinner or a bare red error.
    """
    body = _load(page, "OVERVIEW")

    if "Not running on this deployment" in body:
        assert "512 MB" in body or "TensorFlow" in body, (
            "the unavailable card does not say why"
        )
