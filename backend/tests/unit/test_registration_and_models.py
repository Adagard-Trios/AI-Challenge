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

def test_self_registered_accounts_are_never_admin():
    """
    The line that keeps a stranger away from the owner's Instagram session.
    """
    source = (PROJECT_ROOT / "auth" / "routes.py").read_text(encoding="utf-8")
    fn = next(
        n for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.FunctionDef) and n.name == "register"
    )
    body = ast.get_source_segment(source, fn) or ""

    assert 'role="viewer"' in body, "registration does not pin the role"
    assert '"admin"' not in body


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
        assert "require_admin" in deps, f"{node.name} does not require an admin"
        assert "require_user" not in deps, (
            f"{node.name} accepts any logged-in user; the vault is shared, so "
            "that is the owner's connected account"
        )


def test_the_admin_check_does_not_depend_on_auth_enforced():
    """
    require_admin returns early when enforcement is off:

        if not settings().enforced:
            return user          # no is_admin check at all

    Right for ordinary routes, wrong for these. On a laptop running with
    AUTH_ENFORCED=0 -- the default -- a self-registered viewer would otherwise
    have arrived with the owner's Instagram.
    """
    source = (PROJECT_ROOT / "src" / "social" / "routes.py").read_text(encoding="utf-8")
    fn = next(
        n for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.FunctionDef) and n.name == "_require"
    )
    body = ast.get_source_segment(source, fn) or ""

    assert "is_admin" in body, (
        "_require does not check is_admin itself, so it inherits "
        "require_admin's enforcement-gated early return"
    )
    assert "403" in body


# --- the UI tells the truth before you sign up -------------------------------

def test_the_signup_form_says_social_accounts_are_owner_only():
    login = PROJECT_ROOT.parent / "frontend" / "app" / "pages" / "Login.tsx"
    if not login.exists():
        pytest.skip("frontend not present")

    text = login.read_text(encoding="utf-8")
    assert "restricted to the person running this server" in text, (
        "registration does not say what a new account cannot do"
    )
