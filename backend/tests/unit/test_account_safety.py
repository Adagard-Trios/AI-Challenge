"""
The measures that keep a personal account working, asserted rather than assumed.

This file exists because "are we sure?" is not answerable by reading comments.
Each protection here was added for a stated reason, and each is one refactor
away from silently disappearing -- which is exactly what happened when
collection moved out of the connector and into the backend and inherited the
60-second agent loop.

What is deliberately NOT here, and never will be: fingerprint randomisation,
CAPTCHA solving, proxy rotation. Those are ban EVASION. They escalate the
consequence when detection happens, they are outside what this project is for,
and their absence is a design decision rather than an oversight.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# --- 1. pacing between collections of the same account ----------------------

def test_an_account_is_not_collected_on_every_agent_cycle():
    """
    REGRESSION, and the most dangerous one found.

    The agent loop runs every 60 seconds. The connector deliberately used 15
    minutes and said why: "hitting a logged-in account that often is the
    behaviour that earns a challenge". Folding collection into the backend
    inherited the 60s cadence, which would have touched a personal account 60
    times an hour in a perfectly periodic pattern.
    """
    from src.social.credential_bridge import (
        MIN_COLLECTION_INTERVAL, SessionStoreCredentialStore,
    )

    assert MIN_COLLECTION_INTERVAL >= 600, (
        f"minimum gap is {MIN_COLLECTION_INTERVAL}s -- too fast for an account"
    )

    class FakeStore:
        def load(self, platform):
            return {"storage_state": {"cookies": [{"name": "li_at", "value": "x"}]},
                    "handle": "@me"}

    store = SessionStoreCredentialStore(store=FakeStore())
    served = sum(1 for _ in range(60) if store.get("linkedin") is not None)

    assert served == 1, (
        f"60 agent cycles served {served} credentials; the pacing gate is not "
        "holding"
    )


def test_the_gate_covers_every_caller_not_just_the_loop():
    """
    The dashboard's "Collect now", the agent loop and the selftest all reach
    scraping through get_credential(). A gate in the loop alone would leave the
    other two unpaced.
    """
    import ast

    source = (PROJECT_ROOT / "src" / "social" / "credential_bridge.py").read_text(
        encoding="utf-8")
    fn = next(
        n for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.FunctionDef) and n.name == "get"
    )
    assert "_too_soon(" in (ast.get_source_segment(source, fn) or "")


def test_the_interval_is_jittered():
    """A request exactly every 900 seconds is its own tell."""
    source = (PROJECT_ROOT / "src" / "social" / "credential_bridge.py").read_text(
        encoding="utf-8")
    assert "INTERVAL_JITTER" in source and "uniform" in source


# --- 2. daily budgets -------------------------------------------------------

def test_daily_budgets_are_conservative():
    from src.scrapers.hygiene import DAILY_BUDGETS

    # A 60s loop unrestrained would be ~1440/day. These are the numbers that
    # make a spent budget a backstop rather than the primary control.
    assert DAILY_BUDGETS["twitter"]["requests"] <= 150
    assert DAILY_BUDGETS["linkedin"]["requests"] <= 60
    for platform, caps in DAILY_BUDGETS.items():
        assert caps["requests"] > 0, f"{platform} has no cap"


def test_the_budget_is_enforced_not_merely_declared():
    import ast

    source = (PROJECT_ROOT / "src" / "scrapers" / "base.py").read_text(encoding="utf-8")
    fn = next(
        n for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.FunctionDef) and n.name == "pace"
    )
    body = ast.get_source_segment(source, fn) or ""
    assert "budget_for(" in body and "BudgetExhausted" in body


# --- 3. a challenge stops everything ----------------------------------------

def test_a_challenge_requires_a_human_to_clear():
    """
    Auto-resuming answers "is a person present?" with "no", and retrying into a
    challenge is what converts it into a lasting restriction.
    """
    from src.social.backoff import CHALLENGE_COOLDOWN_SECONDS, BackoffStore

    assert CHALLENGE_COOLDOWN_SECONDS >= 12 * 3600

    import inspect

    source = inspect.getsource(BackoffStore.record_challenge)
    assert "resume" in source.lower(), (
        "nothing documents that only an explicit resume clears a challenge"
    )


def test_collection_checks_the_challenge_flag_before_scraping(tmp_path):
    from src.social import service as svc

    import ast
    source = (PROJECT_ROOT / "src" / "social" / "service.py").read_text(encoding="utf-8")
    fn = next(
        n for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.FunctionDef) and n.name == "collect"
    )
    body = ast.get_source_segment(source, fn) or ""
    assert "is_challenged(" in body
    assert "ready(" in body


def test_failures_back_off_exponentially_and_survive_a_restart():
    from src.social.backoff import BASE_DELAY_SECONDS, MAX_DELAY_SECONDS

    assert BASE_DELAY_SECONDS >= 600
    assert MAX_DELAY_SECONDS >= 3600

    # Persisted, because restarting is exactly what people do after failures.
    source = (PROJECT_ROOT / "src" / "social" / "backoff.py").read_text(encoding="utf-8")
    assert "_save" in source and "_load" in source


# --- 4. sessions are reused, not re-created ---------------------------------

def test_rotated_cookies_are_written_back():
    """
    A fresh session on every run is itself anomalous -- a real person's session
    lasts weeks. Reuse is the single biggest factor in how long an account
    keeps working, and it only works if rotated values are kept.
    """
    import ast

    source = (PROJECT_ROOT / "src" / "social" / "service.py").read_text(encoding="utf-8")
    fn = next(
        n for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.FunctionDef) and n.name == "collect"
    )
    body = ast.get_source_segment(source, fn) or ""
    assert "rotated_state" in body
    assert 'result.status != "challenged"' in body


def test_the_login_is_never_automated_past_a_challenge():
    """
    Logging in is the risky act, not scraping. The password fills two fields
    and stops; the human does submit, 2FA and captcha.
    """
    import ast

    source = (PROJECT_ROOT / "src" / "social" / "browser_login.py").read_text(
        encoding="utf-8")
    fn = next(
        n for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.FunctionDef) and n.name == "_prefill_login"
    )
    code = "\n".join(
        line for line in (ast.get_source_segment(source, fn) or "").splitlines()
        if not line.strip().startswith("#")
    )
    for forbidden in ("click(", "press(", "submit", "keyboard"):
        assert forbidden not in code


# --- 5. what we deliberately do NOT do --------------------------------------

def test_no_ban_evasion_machinery():
    """
    Fingerprint spoofing, CAPTCHA solving and proxy rotation are evasion, not
    hygiene. Their absence is a decision. If one ever appears, this project has
    changed into something else and that should be a deliberate act, not a
    quiet commit.
    """
    social = PROJECT_ROOT / "src" / "social"
    scrapers = PROJECT_ROOT / "src" / "scrapers"

    banned = ("2captcha", "anticaptcha", "capsolver", "deathbycaptcha",
              "proxy_pool", "rotate_proxy", "randomize_fingerprint",
              "spoof_canvas", "stealth_plugin")

    for directory in (social, scrapers):
        for path in directory.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            for term in banned:
                assert term not in text, f"{path.name} references {term!r}"


def test_the_scope_is_stated_in_the_code():
    """So the next person does not add evasion thinking it was an oversight."""
    hygiene = (PROJECT_ROOT / "src" / "scrapers" / "hygiene.py").read_text(
        encoding="utf-8").lower()
    assert "not detection evasion" in hygiene or "not an attempt to defeat" in hygiene


# --- paced is not the same as not connected ---------------------------------

def test_a_paced_account_is_not_reported_as_disconnected():
    """
    REGRESSION, and the reason Instagram appeared to produce no feeds.

    The 15-minute gate returns None from get_credential(), and registry.run
    read every None as "No account connected. Connect one in Settings". On a
    60-second agent loop that was the answer fourteen times out of fifteen --
    telling the user to fix something that was not broken, and telling the
    agent there was nothing to collect from.
    """
    from src.scrapers import registry
    from src.social.credential_bridge import SessionStoreCredentialStore

    class Connected(SessionStoreCredentialStore):
        class _Store:
            @staticmethod
            def load(platform):
                return {"storage_state": {"cookies": [{"name": "sessionid", "value": "x"}]},
                        "handle": "@me"}

            @staticmethod
            def available():
                return ["instagram"]

        @property
        def store(self):
            return self._Store()

    from src.scrapers.credentials import set_credential_store

    store = Connected()
    set_credential_store(store)
    try:
        assert store.get("instagram") is not None, "first call should serve"
        assert store.get("instagram") is None, "second call should be paced"

        result = registry.run("scrape_instagram", "srilanka", max_items=1)
        assert result["status"] == "paced", (
            f"a paced account reports {result['status']!r}: {result['reason'][:80]}"
        )
        assert "connected and working" in result["reason"]
        assert result.get("retry_after_seconds", 0) > 0
    finally:
        set_credential_store(None)


def test_pacing_is_not_charged_to_an_account_that_does_not_exist():
    """
    Consuming the slot before loading the session marked a platform that had
    never been connected as "collected recently". Pacing protects a session;
    there is nothing to protect when there is none.
    """
    from src.social.credential_bridge import SessionStoreCredentialStore

    class Empty(SessionStoreCredentialStore):
        class _Store:
            @staticmethod
            def load(platform):
                return None

            @staticmethod
            def available():
                return []

        @property
        def store(self):
            return self._Store()

    store = Empty()
    assert store.get("twitter") is None
    assert store.is_paced("twitter") is False, (
        "a platform with no session was charged a pacing slot"
    )


def test_asking_whether_an_account_is_paced_does_not_consume_it():
    """is_paced() is a read; _too_soon() is the one that charges."""
    from src.social.credential_bridge import SessionStoreCredentialStore

    store = SessionStoreCredentialStore(store=object())
    for _ in range(5):
        assert store.is_paced("linkedin") is False
    assert store.seconds_until_ready("linkedin") == 0
