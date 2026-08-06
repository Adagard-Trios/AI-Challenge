"""
Social accounts, connected from the dashboard instead of a terminal.

The connector was a separate process for one reason: when the server is a
shared free-tier host, a password sent to it is a password on someone else's
machine. Hosting from your own laptop removes that reason -- the server and
"your machine" are the same computer -- so the fields moved into the dashboard.

The reason is gone. The safety properties are not, and these tests are what
stop them drifting away now that the code lives in the backend:

  * the password is stored encrypted and never comes back out over the API
  * saving a password does not log anything in -- it pre-fills a form and stops
  * every route requires a logged-in user
  * the dashboard and the CLI share one store, so neither can show a stale view
  * nothing claims an account is safe from restriction
"""

import ast
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
REPO_ROOT = PROJECT_ROOT.parent
for path in (str(PROJECT_ROOT), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

SERVICE = PROJECT_ROOT / "src" / "social" / "service.py"
ROUTES = PROJECT_ROOT / "src" / "social" / "routes.py"


def _function(path: Path, name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"{path.name} has no function {name!r}")


# --- the password does not come back ----------------------------------------

def test_no_response_carries_a_password():
    """
    The vault has no method that returns one, and no route should either. A
    password that can be read back is a password one XSS away from leaving.
    """
    source = ROUTES.read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        fields = {
            target.target.id
            for target in node.body
            if isinstance(target, ast.AnnAssign) and isinstance(target.target, ast.Name)
        }
        if node.name.endswith("Out") or "Response" in node.name:
            assert "password" not in fields, f"{node.name} exposes a password"

    # The only place the word may legitimately appear as an input.
    assert "class CredentialsIn" in source
    assert source.count("password") <= 12, (
        "'password' appears more often than the single input model needs -- "
        "check nothing echoes it back"
    )


def test_the_account_listing_returns_usernames_but_never_secrets():
    from src.social import service as svc

    listing = _function(SERVICE, "saved_usernames")
    assert "describe()" in listing, (
        "saved_usernames must use vault.describe(), which returns usernames only"
    )
    assert "get(" not in listing, "saved_usernames reads full credential records"

    # describe() is the only vault method the service uses for display.
    accounts = _function(SERVICE, "accounts")
    assert ".describe()" in accounts
    assert '"password"' not in accounts


def test_storing_credentials_does_not_log_them():
    """
    A password in a log file is a password in a log file. This has bitten every
    project that ever logged a request body.
    """
    save = _function(SERVICE, "save_credentials")

    for line in save.splitlines():
        if "logger." in line:
            assert "password" not in line, f"password reaches a log line: {line.strip()}"

    route = _function(ROUTES, "save_credentials")
    for line in route.splitlines():
        if "logger." in line:
            assert "payload" not in line and "password" not in line, (
                f"the route logs the request body: {line.strip()}"
            )


def test_an_unexpected_storage_failure_does_not_echo_the_exception():
    """
    A keyring or crypto error can carry fragments of what it was handling, so
    the generic handler replaces the detail rather than forwarding it.

    Scoped to the `except Exception` branch on purpose. The ValueError branch
    above it *should* forward its message -- that one is our own validation
    text ("Both a username and a password are required"), which is exactly what
    the user needs to see.
    """
    source = ROUTES.read_text(encoding="utf-8")
    tree = ast.parse(source)

    node = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "save_credentials"
    )

    generic = [
        h for h in ast.walk(node)
        if isinstance(h, ast.ExceptHandler)
        and isinstance(h.type, ast.Name) and h.type.id == "Exception"
    ]
    assert generic, "save_credentials has no catch-all handler"

    body = "\n".join(ast.get_source_segment(source, h) or "" for h in generic)
    assert "Could not store the credentials" in body
    assert "str(exc)" not in body.replace(" ", ""), (
        "the catch-all forwards the raw exception text"
    )


# --- saving is not logging in -----------------------------------------------

def test_saving_a_password_does_not_start_a_login():
    """
    Save and Connect are separate actions. Merging them would hide which one
    just happened, and would mean storing a password silently opened a browser.
    """
    save = _function(SERVICE, "save_credentials")

    for forbidden in ("playwright", "start_connect", "_run_connect", "launch"):
        assert forbidden not in save, (
            f"save_credentials references {forbidden!r} -- storing a password "
            "must not trigger a login"
        )


def test_the_login_form_is_still_never_submitted():
    """
    The property that keeps accounts alive, unchanged by the move into the
    backend: the browser pre-fills two fields and a human does the rest.
    """
    from src.social import browser_login as connect

    source = _function(
        PROJECT_ROOT / "src" / "social" / "browser_login.py", "_prefill_login",
    )

    code = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )
    for forbidden in ("click(", "press(", "submit", "keyboard"):
        assert forbidden not in code, (
            f"_prefill_login uses {forbidden!r} -- it must fill and stop"
        )

    assert connect.LOGIN_FIELDS, "login field selectors disappeared"


def test_connect_waits_for_real_cookies_rather_than_a_confirmation():
    """
    The CLI asked the user to press Enter, which could be answered before the
    login finished and produced a half-captured session. Watching for the auth
    cookies cannot be answered early.
    """
    waiter = _function(SERVICE, "_await_login")
    assert "missing_required" in waiter
    assert "LOGIN_TIMEOUT_SECONDS" in waiter, "the wait is unbounded"

    # Checked as a CALL, not as text. The module docstring explains the CLI's
    # `input("Press Enter...")` in order to say why it is gone, and a substring
    # search matches that explanation -- a test failing on its own prose.
    tree = ast.parse(SERVICE.read_text(encoding="utf-8"))
    calls = [
        node.func.id for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert "input" not in calls, (
        "a blocking input() cannot work in a web request"
    )


def test_the_connect_job_does_not_block_the_request():
    start = _function(SERVICE, "start_connect")
    assert "threading.Thread" in start, (
        "connect must run off-request; a login takes a human minutes"
    )


# --- every route needs a logged-in user -------------------------------------

def test_every_social_route_requires_authentication():
    """
    These endpoints store a password, open a browser on the host machine, and
    read a session cookie. On a tunnelled laptop an unauthenticated version
    would hand all three to anyone with the URL.
    """
    source = ROUTES.read_text(encoding="utf-8")
    tree = ast.parse(source)

    routed = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        decorators = [
            d for d in node.decorator_list
            if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
            and isinstance(d.func.value, ast.Name) and d.func.value.id == "router"
        ]
        if decorators:
            routed.append(node)

    assert routed, "no routes found; has the router been renamed?"

    for node in routed:
        body = ast.get_source_segment(source, node) or ""
        assert "require_user" in body, f"{node.name} does not depend on require_user"
        assert "_require(user)" in body, (
            f"{node.name} takes a user but never rejects None -- with "
            "AUTH_ENFORCED off, require_user returns None instead of raising"
        )


def test_unsupported_platforms_are_rejected_at_the_route():
    route = ROUTES.read_text(encoding="utf-8")
    assert "_check_platform" in route
    assert "SUPPORTED_PLATFORMS" in route


# --- one store, two front doors ---------------------------------------------

def test_the_dashboard_and_the_cli_share_one_store():
    """
    If these diverged, `connector status` and the dashboard would each show a
    private half of reality -- an account connected in one being invisible in
    the other.
    """
    source = SERVICE.read_text(encoding="utf-8")
    assert "from .vault import CredentialVault" in source
    assert "from .storage import SessionStore" in source


def test_collection_writes_rotated_cookies_back():
    """
    Platforms rotate cookies during ordinary use. Discarding them makes a stored
    session drift stale until it stops working, which a user experiences as "it
    randomly logs me out every few weeks".
    """
    collect = _function(SERVICE, "collect")
    assert "rotated_state" in collect
    assert 'result.status != "challenged"' in collect, (
        "a session captured mid-challenge should not be persisted"
    )


def test_a_challenge_is_not_retried_automatically():
    collect = _function(SERVICE, "collect")
    assert "challenged" in collect
    assert "will NOT retry" in collect


def test_collected_posts_deduplicate_against_the_connector_path():
    """
    Both paths write to ingested_posts. Using a different hash would double
    every post for anyone who used both.
    """
    store = _function(ROUTES, "_store")
    assert "sha256" in store
    assert "content_hash" in store


# --- the agent pipeline can actually see connected accounts -----------------

def test_the_scrapers_are_pointed_at_the_dashboard_store():
    """
    The gap that made this feature complete-looking and non-functional.

    Every scraper calls get_credential(), whose default is NullCredentialStore
    -- correct for a shared server, fatal here. Without the bridge you could
    sign in, see "Connected" with a handle and an expiry, and all five agents
    would still scrape nothing. No error; the social feed was just always
    empty.
    """
    source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    assert "credential_bridge" in source, (
        "nothing installs a credential store, so connected accounts are "
        "invisible to the agents"
    )
    assert "_credential_bridge.install()" in source


def test_the_bridge_reads_the_same_store_the_dashboard_writes():
    bridge = PROJECT_ROOT / "src" / "social" / "credential_bridge.py"
    source = bridge.read_text(encoding="utf-8")
    assert "from .storage import SessionStore" in source


def test_the_bridge_does_not_cache_sessions():
    """
    collect() writes rotated cookies back after every run. A cached credential
    would go stale exactly when a platform rotated -- the failure the write-back
    exists to prevent.
    """
    bridge = PROJECT_ROOT / "src" / "social" / "credential_bridge.py"
    source = bridge.read_text(encoding="utf-8")
    tree = ast.parse(source)

    get = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "get"
    )
    body = ast.get_source_segment(source, get) or ""
    assert "self.store.load(" in body, "get() does not read through to the store"


def test_the_bridge_shares_a_budget_key_with_collect_now():
    """
    Two readers of one account must share one counter, or each could spend a
    full daily allowance without the other noticing.
    """
    bridge = (PROJECT_ROOT / "src" / "social" / "credential_bridge.py").read_text(
        encoding="utf-8")
    service = SERVICE.read_text(encoding="utf-8")

    assert 'f"local:{platform}"' in bridge
    assert 'f"local:{platform}"' in service


# --- offered platforms must be collectable ----------------------------------

def test_every_platform_offered_for_login_can_actually_be_collected():
    """
    Reddit has a login URL and vault support but NO session scraper -- it is
    read through its public JSON API. Listing it would let someone save a
    password, complete a browser sign-in, click Collect and get "unsupported".
    """
    from src.scrapers import registry
    from src.social import service as svc

    for platform in svc.SUPPORTED_PLATFORMS:
        scraper = svc.COLLECTORS[platform]
        assert scraper in registry.REGISTRY, (
            f"{platform} is offered for login but {scraper} is not registered"
        )


def test_the_platform_list_is_derived_not_copied():
    source = SERVICE.read_text(encoding="utf-8")
    assert "SUPPORTED_PLATFORMS = tuple(COLLECTORS)" in source, (
        "the list is hand-maintained again and will drift from what can collect"
    )


# --- collected posts are visible --------------------------------------------

def test_collected_posts_have_a_frontend_consumer():
    """
    /api/ingest/recent existed with no consumer, so "scrape the posts" ended at
    a row count in a database that nothing displayed.
    """
    app_dir = REPO_ROOT / "frontend" / "app"
    if not app_dir.exists():
        pytest.skip("frontend not present")

    hits = [
        path for path in app_dir.rglob("*.tsx")
        if "ingest/recent" in path.read_text(encoding="utf-8", errors="ignore")
    ]
    assert hits, "nothing in the frontend reads /api/ingest/recent"


# --- no false promises ------------------------------------------------------

def test_the_ui_does_not_promise_accounts_are_safe():
    card = REPO_ROOT / "frontend" / "app" / "components" / "settings" / "SocialAccounts.tsx"
    if not card.exists():
        pytest.skip("frontend not present")

    text = card.read_text(encoding="utf-8").lower()
    for claim in ("never be banned", "never gets banned", "cannot be banned",
                  "guaranteed safe", "100% safe", "completely safe"):
        assert claim not in text, f"the UI promises {claim!r}, which is not true"

    # And it must say the true thing.
    assert "terms" in text, (
        "the UI does not mention that automated collection breaches platform terms"
    )


def test_the_ui_says_where_the_browser_opens():
    """
    A browser opening on a different computer than the one you are looking at
    is surprising enough that it has to be stated before the button, not
    discovered after it.
    """
    card = REPO_ROOT / "frontend" / "app" / "components" / "settings" / "SocialAccounts.tsx"
    if not card.exists():
        pytest.skip("frontend not present")

    text = card.read_text(encoding="utf-8")
    assert "machine running this server" in text
