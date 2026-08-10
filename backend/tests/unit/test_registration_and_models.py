"""
Self-registration, and the model IDs that stopped existing.

TWO SILENT FAILURES, ONE OF THEM LIVE
-------------------------------------
The Roger chatbot asked Groq for meta-llama/llama-4-maverick-17b-128e-instruct,
which Groq deprecated on 20 February 2026. Every message returned 404. The RAG
layer caught the exception, logged it, and handed the user a generic failure --
so the symptom was "the chatbot never answers", which reads as slowness or a
bad key rather than a model that no longer exists. Groq deprecated six models
during 2026; this is a recurring class of failure, not an accident.

And self-registration, taken alone, would have been a hole. The credential
vault and session store are machine-global -- one per install, no user_id
anywhere -- so any account that can reach /api/social/* reaches the OWNER'S
connected Instagram: listing it, opening a browser login, collecting with its
session. Open sign-ups without scoping those routes would have handed that to
whoever signed up first.
"""

import ast
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# --- model IDs are not hardcoded, and are checkable --------------------------

def test_no_model_id_is_hardcoded_at_a_call_site():
    """
    The chatbot's model was pinned inline and silently stopped existing. Both
    call sites now resolve through src/llms/models.py so there is one place to
    change and one place to verify.
    """
    for rel in ("src/rag.py", "src/llms/groqllm.py"):
        source = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
        code = "\n".join(
            line for line in source.splitlines()
            if not line.strip().startswith("#")
        )
        assert 'model="meta-llama' not in code, f"{rel} pins a model inline"
        assert 'model="openai/' not in code, f"{rel} pins a model inline"


def test_the_deprecated_chatbot_model_is_gone():
    """The specific ID that was returning 404 on every chatbot message."""
    source = (PROJECT_ROOT / "src" / "rag.py").read_text(encoding="utf-8")
    code = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )
    assert "llama-4-maverick" not in code


def test_defaults_are_models_groq_still_offers():
    from src.llms.models import DEFAULT_AGENT_MODEL, DEFAULT_CHAT_MODEL

    # Both are current as of the migration Groq itself published for Maverick.
    assert DEFAULT_CHAT_MODEL == "openai/gpt-oss-120b"
    assert DEFAULT_AGENT_MODEL == "openai/gpt-oss-20b"


def test_models_are_overridable_by_environment(monkeypatch):
    from src.llms import models

    monkeypatch.setenv("GROQ_CHAT_MODEL", "some/other-model")
    assert models.chat_model() == "some/other-model"

    monkeypatch.setenv("GROQ_CHAT_MODEL", "   ")
    assert models.chat_model() == models.DEFAULT_CHAT_MODEL, (
        "a blank override should fall back, not ask Groq for an empty model"
    )


def test_unavailable_is_distinct_from_unknown(monkeypatch):
    """
    available_models() returns None when it could not check and a list when it
    could. Collapsing those would make the preflight report a configuration
    error every time the network hiccups -- and a checker that cries wolf gets
    ignored along with the next real warning.
    """
    from src.llms import models

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert models.available_models() is None


def test_the_preflight_verifies_models_against_the_key():
    source = (PROJECT_ROOT / "src" / "preflight.py").read_text(encoding="utf-8")
    assert "_groq_model_check" in source
    assert "available_models" in source
    assert "CHECKS" in source and "_groq_model_check," in source, (
        "the check exists but is not registered, so it never runs"
    )


# --- registration ------------------------------------------------------------

def test_registration_does_not_invent_a_second_tier():
    """
    What used to keep a stranger away from the owner's Instagram was a powerless
    "viewer" role. Isolation does that now -- per-user vaults, so a new account
    starts empty and can only reach what it connected itself -- and the role is
    no longer load-bearing.

    Pinned to the shared constant rather than a literal: a hand-written role
    here that is_admin does not recognise would let someone register, sign in,
    and then be refused their own social accounts.
    """
    source = (PROJECT_ROOT / "auth" / "routes.py").read_text(encoding="utf-8")
    fn = next(
        n for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.FunctionDef) and n.name == "register"
    )
    body = ast.get_source_segment(source, fn) or ""

    assert "role=DEFAULT_ROLE" in body, (
        "registration writes a literal role instead of the shared constant"
    )
    assert 'role="viewer"' not in body


def test_registration_can_be_switched_off_without_a_redeploy():
    source = (PROJECT_ROOT / "auth" / "routes.py").read_text(encoding="utf-8")
    fn = next(
        n for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.FunctionDef) and n.name == "self_registration_open"
    )
    body = ast.get_source_segment(source, fn) or ""
    assert "os.getenv" in body, (
        "the flag is read at import time, so disabling sign-ups needs a restart"
    )


def test_registration_rejects_a_weak_password():
    """Reuses hash_password's rules rather than inventing a second policy."""
    source = (PROJECT_ROOT / "auth" / "routes.py").read_text(encoding="utf-8")
    fn = next(
        n for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.FunctionDef) and n.name == "register"
    )
    body = ast.get_source_segment(source, fn) or ""
    assert "WeakPassword" in body and "hash_password" in body


# --- the social routes are admin-only, unconditionally -----------------------

def test_every_social_route_requires_an_admin():
    """
    Checked through the AST rather than by searching text: the docstrings in
    this module explain the earlier require_user pool bug, so a substring
    search matches the prose describing the fix and fails on it.
    """
    source = (PROJECT_ROOT / "src" / "social" / "routes.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    routed = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and any(
            isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
            and isinstance(d.func.value, ast.Name) and d.func.value.id == "router"
            for d in node.decorator_list
        )
    ]
    assert routed, "no routes found; has the router been renamed?"

    for node in routed:
        deps = {
            default.args[0].id
            for default in node.args.defaults
            if isinstance(default, ast.Call)
            and isinstance(default.func, ast.Name) and default.func.id == "Depends"
            and default.args and isinstance(default.args[0], ast.Name)
        }
        assert "require_user" in deps, f"{node.name} does not require a signed-in user"


def test_every_social_route_scopes_its_service_to_the_caller():
    """
    The guarantee that replaced the admin check.

    Isolation now rests entirely on get_service being handed the caller's id:
    that argument is what selects the per-user directory holding the passwords,
    the cookies and the pacing state. A bare get_service() falls back to the old
    install-wide store, so one omitted argument silently returns every user to
    sharing a single Instagram slot -- the exact failure the role check existed
    to prevent, reintroduced without any visible change at the route.
    """
    source = (PROJECT_ROOT / "src" / "social" / "routes.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    unscoped = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get_service"
        and not node.args
    ]
    assert not unscoped, (
        f"get_service() called with no user at line(s) {unscoped}; that opens "
        "the shared vault rather than the caller's own"
    )


def test_the_identity_check_does_not_depend_on_auth_enforced():
    """
    require_user returns None when enforcement is off, and _require must still
    refuse that. Without a user there is no directory to scope to, so serving
    the request would mean falling back to the shared vault -- on a laptop
    running the default AUTH_ENFORCED=0, anyone reaching the port.
    """
    source = (PROJECT_ROOT / "src" / "social" / "routes.py").read_text(encoding="utf-8")
    fn = next(
        n for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.FunctionDef) and n.name == "_require"
    )
    body = ast.get_source_segment(source, fn) or ""

    assert "user is None" in body and "401" in body, (
        "_require no longer refuses an anonymous caller, so with enforcement "
        "off every social route serves the unscoped vault"
    )


# --- the UI tells the truth before you sign up -------------------------------

def test_the_signup_form_states_what_a_new_account_gets():
    """
    It used to have to warn that connecting was owner-only. With per-user
    vaults there is no such restriction, and the thing worth saying before
    someone hands over an email is the isolation they are getting.
    """
    login = PROJECT_ROOT.parent / "frontend" / "app" / "pages" / "Login.tsx"
    if not login.exists():
        pytest.skip("frontend not present")

    text = login.read_text(encoding="utf-8")
    assert "visible only to you" in text, (
        "the signup form no longer tells a new account what it gets"
    )
    assert "restricted to the person running this server" not in text, (
        "the signup form still claims connecting is owner-only"
    )


def test_auth_failure_does_not_serve_an_open_api_when_enforcement_is_on():
    """
    The handler around the auth bootstrap must re-raise when AUTH_ENFORCED=1.

    Observed in production, not theorised: Postgres restarted, auth's first
    connect timed out, main.py logged "continuing without it", and the process
    served every route with require_user() returning None. /healthz answered 200
    the whole time, so nothing external showed a problem while /api/auth/login
    404'd and the dashboard was readable and writable by anyone with the URL.
    """
    source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    handlers = [
        h for h in ast.walk(tree)
        if isinstance(h, ast.ExceptHandler)
        and "auth layer" in (ast.get_source_segment(source, h) or "")
    ]
    assert handlers, "no handler around the auth bootstrap; has it been renamed?"

    body = ast.get_source_segment(source, handlers[0]) or ""
    assert "AUTH_ENFORCED" in body, (
        "the auth-failure handler does not consult AUTH_ENFORCED, so it cannot "
        "tell 'nobody asked for auth' from 'auth was required and broke'"
    )
    assert any(isinstance(n, ast.Raise) for n in ast.walk(handlers[0])), (
        "the auth-failure handler never re-raises, so a failed auth layer with "
        "enforcement on still serves every route unauthenticated"
    )
