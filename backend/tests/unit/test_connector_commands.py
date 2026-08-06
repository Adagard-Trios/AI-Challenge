"""
The web dashboard driving the connector on the user's machine.

Connecting an account has to happen locally -- the password and the session
cookie must never reach the server -- which meant the only way to do it was a
terminal, while the dashboard could show status and nothing else.

A command queue closes that without moving a secret: the dashboard queues an
INSTRUCTION ("connect linkedin"), and the connector, already polling on its
collect loop, executes it locally using credentials from its own vault. What
crosses the wire is a verb and a platform name.

Two properties these tests exist to hold:

  - the vocabulary is closed, so a command is never a script
  - queued is not done, so a button that queued work against a stopped
    connector says so instead of appearing to have worked
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# The connector lives beside backend/, not inside it.
REPO_ROOT = PROJECT_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# --- the vocabulary is closed ---------------------------------------------

def test_only_three_actions_exist():
    """
    A command must never be a script. Even a fully compromised server should
    only be able to ask a connector to do things it was already willing to do.
    """
    from src.intelligence.commands import ACTIONS

    assert set(ACTIONS) == {"connect", "collect", "disconnect"}


def test_an_unknown_action_is_rejected_at_the_service_layer():
    from src.intelligence.commands import queue

    with pytest.raises(ValueError, match="Unknown action"):
        queue(None, "user1", "rm -rf /", "linkedin")


def test_the_route_validates_action_and_platform():
    """Validation must not live only in the UI."""
    import inspect

    from src.intelligence import command_routes

    source = inspect.getsource(command_routes.queue_command)
    assert "command_service.ACTIONS" in source
    assert "PLATFORMS" in source


def test_the_command_carries_no_credential_field():
    """
    The architectural promise. If a command ever grows a password field, the
    credential stops being device-local and the whole design changes.
    """
    from src.intelligence.command_routes import CommandRequest

    assert set(CommandRequest.model_fields) == {"action", "platform"}


# --- queued is not done ----------------------------------------------------

def test_a_stale_connector_counts_as_not_running():
    """
    Drives the warning banner. A connector that stopped an hour ago must not
    read as alive, or the dashboard promises work that nothing will pick up.
    """
    from src.intelligence.commands import CONNECTOR_ALIVE_WINDOW, connector_is_running

    class FakeDevice:
        revoked_at = None
        user_id = "u1"

        def __init__(self, last_seen):
            self.last_seen_at = last_seen

    class FakeQuery:
        def __init__(self, rows):
            self._rows = rows

        def filter(self, *a, **k):
            return self

        def all(self):
            return self._rows

    class FakeDB:
        def __init__(self, rows):
            self._rows = rows

        def query(self, *a, **k):
            return FakeQuery(self._rows)

    now = datetime.now(timezone.utc)

    fresh = FakeDB([FakeDevice(now - timedelta(seconds=30))])
    assert connector_is_running(fresh, "u1") is True

    stale = FakeDB([FakeDevice(now - CONNECTOR_ALIVE_WINDOW - timedelta(minutes=1))])
    assert connector_is_running(stale, "u1") is False

    never = FakeDB([FakeDevice(None)])
    assert connector_is_running(never, "u1") is False

    assert connector_is_running(FakeDB([]), "u1") is False


def test_a_naive_last_seen_does_not_raise():
    """Rows written before the tz-aware default would compare as naive."""
    from src.intelligence.commands import connector_is_running

    class FakeDevice:
        revoked_at = None
        last_seen_at = datetime.now().replace(tzinfo=None)

    class FakeQuery:
        def filter(self, *a, **k):
            return self

        def all(self):
            return [FakeDevice()]

    class FakeDB:
        def query(self, *a, **k):
            return FakeQuery()

    assert connector_is_running(FakeDB(), "u1") in (True, False)


def test_the_response_tells_the_user_whether_anything_will_run():
    """
    The failure this codebase keeps producing is a control that appears to work
    and silently does nothing. The queue response has to distinguish them.
    """
    import inspect

    from src.intelligence import command_routes

    source = inspect.getsource(command_routes.queue_command)
    assert "connector_running" in source
    assert "no connector is running" in source


@pytest.mark.skipif(
    not (REPO_ROOT / "frontend").exists(), reason="frontend not present"
)
def test_the_dashboard_warns_before_the_click_not_after():
    card = (
        REPO_ROOT / "frontend" / "app" / "components" / "settings"
        / "ConnectedAccounts.tsx"
    )
    src = card.read_text(encoding="utf-8")

    assert "connectorRunning === false" in src, (
        "the dashboard does not warn when no connector is running"
    )
    assert "python -m connector run" in src, (
        "the warning does not say how to start one"
    )


# --- the two sides never share auth ---------------------------------------

def test_browser_and_connector_endpoints_use_different_dependencies():
    """
    A stolen device token must not be able to queue work, and a browser session
    must not be able to claim it.
    """
    import ast

    source = (
        PROJECT_ROOT / "src" / "intelligence" / "command_routes.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)

    deps = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        found = set()
        for default in node.args.defaults:
            if (isinstance(default, ast.Call)
                    and isinstance(default.func, ast.Name)
                    and default.func.id == "Depends"
                    and default.args
                    and isinstance(default.args[0], ast.Name)):
                found.add(default.args[0].id)
        if found:
            deps[node.name] = found

    assert "require_user" in deps["queue_command"]
    assert "require_device" not in deps["queue_command"]

    assert "require_device" in deps["claim_commands"]
    assert "require_user" not in deps["claim_commands"]

    assert "require_device" in deps["report_result"]


def test_completing_a_command_is_scoped_to_the_owning_user():
    """A device must not be able to close another user's command."""
    import inspect

    from src.intelligence import commands

    source = inspect.getsource(commands.complete)
    assert "user_id=user_id" in source


# --- the connector side ----------------------------------------------------

def test_the_connector_uses_its_own_vault_not_the_command():
    """
    Credentials come from the LOCAL vault. If run_command ever read them off
    the command payload, the server would be handling passwords.
    """
    import inspect

    from connector.collect import Collector

    source = inspect.getsource(Collector.run_command)
    assert "CredentialVault" in source
    assert 'command.get("password")' not in source
    assert 'command["password"]' not in source


def test_commands_are_polled_faster_than_the_collect_interval():
    """
    The 15-minute collect cadence protects the account. Applying it to a button
    press protects nothing and makes Connect feel broken.
    """
    from connector.collect import COMMAND_POLL_SECONDS

    assert COMMAND_POLL_SECONDS <= 60


def test_an_old_server_without_the_queue_is_not_an_error():
    """
    A 404 means the server predates this feature. Collection still works; the
    buttons just do nothing. That must not spam errors or stop the loop.
    """
    import inspect

    from connector.collect import Collector

    source = inspect.getsource(Collector.claim_commands)
    assert "404" in source
    assert "return []" in source


def test_unclaimed_commands_expire():
    """
    A browser window opening unprompted an hour after a forgotten click is
    alarming, not helpful.
    """
    from src.intelligence.commands import COMMAND_TTL

    assert COMMAND_TTL <= timedelta(hours=1)
