"""
A failure must never be indistinguishable from an empty result.

This is the single pattern behind most of the bugs found in this project, and
each of these is a real one, not a hypothetical:

  * the dashboard was publicly readable because `enforced` defaulted to false
    and the probe that would have corrected it answered 401
  * the signup page said "accounts are invite-only" because a failed probe and
    a closed instance were the same value
  * the social-accounts panel rendered an empty list because a non-401 error
    and "no accounts" were the same empty list
  * six situational cards said NO SOURCE because a 401 at mount left null and
    nothing retried
  * the blackboard planned everything every tick because a failed lookup
    returned {} and {} means "nothing has ever run"

The fix is never "stop returning a safe value" -- a panel should not crash. It
is that the failure must be RECORDED, so it can be seen in a log or on screen.
"""

import ast
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SKIP_PARTS = {".venv", "__pycache__", "tests", "node_modules"}


def _python_files():
    for path in PROJECT_ROOT.rglob("*.py"):
        if not any(part in SKIP_PARTS for part in path.parts):
            yield path


def test_no_handler_swallows_a_failure_into_an_empty_container():
    """
    `except Exception: return []` tells every caller "there is nothing here"
    and leaves no trace that anything went wrong. Returning the empty value is
    fine; doing it silently is not.
    """
    offenders = []

    for path in _python_files():
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, SyntaxError):
            continue

        for handler in ast.walk(tree):
            if not isinstance(handler, ast.ExceptHandler):
                continue
            segment = ast.get_source_segment(source, handler) or ""
            if any(word in segment for word in
                   ("logger.", "logging.", "print(", "raise")):
                continue
            for node in ast.walk(handler):
                if (isinstance(node, ast.Return)
                        and isinstance(node.value, (ast.List, ast.Dict))
                        and not getattr(node.value, "elts", None)
                        and not getattr(node.value, "keys", None)):
                    offenders.append(
                        f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}")

    assert not offenders, (
        "these handlers return an empty container without logging, so a "
        "failure is indistinguishable from 'nothing there':\n  "
        + "\n  ".join(offenders)
    )


def test_no_handler_reports_a_success_status_it_did_not_achieve():
    """
    Returning {"status": "success"} from an except block is the same lie in a
    louder voice. The stock panel did exactly this with simulated prices.
    """
    success_words = {"success", "ok", "normal", "operational", "live"}
    offenders = []

    for path in _python_files():
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, SyntaxError):
            continue

        for handler in ast.walk(tree):
            if not isinstance(handler, ast.ExceptHandler):
                continue
            for node in ast.walk(handler):
                if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Dict):
                    continue
                for key, value in zip(node.value.keys, node.value.values):
                    if (isinstance(key, ast.Constant)
                            and key.value in ("status", "scrape_status")
                            and isinstance(value, ast.Constant)
                            and value.value in success_words):
                        offenders.append(
                            f"{path.relative_to(PROJECT_ROOT)}:{node.lineno} "
                            f"-> {key.value}={value.value!r}")

    assert not offenders, (
        "these handlers claim success from inside an exception:\n  "
        + "\n  ".join(offenders)
    )


def test_the_credential_vault_never_reports_empty_without_saying_why():
    """
    The most consequential instance. A vault that exists but will not decrypt
    returning {} makes the accounts panel show every platform as unconnected,
    so a user re-enters a password that is already stored -- and nothing
    anywhere records that decryption failed.
    """
    source = (PROJECT_ROOT / "src" / "social" / "vault.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    for name in ("platforms", "describe"):
        fn = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == name
        )
        body = ast.get_source_segment(source, fn) or ""
        assert "logger." in body, (
            f"vault.{name}() swallows a decrypt failure into an empty result"
        )


# --- the same pattern on the client ------------------------------------------

FRONTEND = PROJECT_ROOT.parent / "frontend" / "app"


def test_situational_fetches_mark_a_failure_rather_than_leaving_null():
    """
    `if (res?.ok) setX(...)` with no else left the state at null, and null
    renders as NO SOURCE -- whose tooltip says "There is no readable source for
    this data yet." That is a claim about CEB and CBSL, made because our own
    request failed.
    """
    if not FRONTEND.exists():
        import pytest
        pytest.skip("frontend not present")

    hook = (FRONTEND / "hooks" / "use-roger-data.tsx").read_text(encoding="utf-8")
    start = hook.find("fetchSituationalData")
    assert start != -1, "fetchSituationalData is gone; has it been renamed?"
    body = hook[start:start + 2500]

    assert "scrape_status" in body and "error" in body, (
        "a failed situational fetch no longer marks the panel, so it will "
        "render as NO SOURCE and blame the government site"
    )


def test_list_panels_can_tell_empty_apart_from_failed():
    """
    apiGet returns its fallback on failure, so `{ stories: [] }` means both
    "nothing has happened" and "the request died", and the card draws the same
    empty state. These two panels render exactly such a list.
    """
    if not FRONTEND.exists():
        import pytest
        pytest.skip("frontend not present")

    for rel in ("components/intelligence/StoryFeed.tsx",
                "components/settings/CollectedPosts.tsx"):
        text = (FRONTEND / rel).read_text(encoding="utf-8")
        assert "apiResult" in text, (
            f"{rel} still uses apiGet, so a failed load renders as an empty list"
        )
        assert "Could not load" in text, (
            f"{rel} has no distinct failure state for the reader"
        )


def test_a_failed_situational_fetch_retries_sooner_than_the_slow_loop():
    """
    Marking the failure is not enough on its own. With only the 5-minute
    interval, a backend restart or a cold start leaves six panels reading
    NO SOURCE for the rest of that window -- observed on the live dashboard
    every time the API was restarted during development.
    """
    if not FRONTEND.exists():
        import pytest
        pytest.skip("frontend not present")

    hook = (FRONTEND / "hooks" / "use-roger-data.tsx").read_text(encoding="utf-8")
    assert "RETRY_MS" in hook, (
        "a failed situational fetch waits the full healthy interval, so a "
        "transient outage persists long enough to look permanent"
    )
    assert "HEALTHY_MS" in hook, (
        "the healthy cadence is no longer distinct from the retry cadence"
    )


def test_losing_redis_is_announced_rather_than_silently_degraded():
    """
    Four modules fall back to per-process behaviour when Redis is unreachable.
    The fallback is correct -- a single instance works fine without Redis -- but
    it silently changes what the system guarantees:

        dedup         the same event can be emitted once per replica
        bus           a client only sees events from its own replica
        shared_state  each replica serves its own dashboard snapshot
        ws_tickets    a ticket from one replica is rejected by another

    On the single-machine deployment none of that shows. On the Kubernetes
    overlay every one is a real bug whose only symptom is behaviour that reads
    as something else entirely, which is why it has to be said out loud once.
    """
    modules = {
        "src/runtime/dedup.py": "_shared",
        "src/runtime/bus.py": "_client",
        "src/runtime/shared_state.py": "_shared",
        "auth/ws_tickets.py": "_shared",
    }
    for rel, fn_name in modules.items():
        source = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
        fn = next(
            n for n in ast.walk(ast.parse(source))
            if isinstance(n, ast.FunctionDef) and n.name == fn_name
        )
        body = ast.get_source_segment(source, fn) or ""
        assert "logger." in body, (
            f"{rel}:{fn_name} drops to a per-process fallback without saying so"
        )
        assert "_WARNED_NO_REDIS" in body, (
            f"{rel}:{fn_name} would log on every call; this is a hot path"
        )
