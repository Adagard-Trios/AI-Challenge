"""
Probes, process roles, and the public-hosting guard.

These are the three things that turn "add replicas" from a scaling change into
an outage.

The probe one is the subtlest and the worst. Most routes in main.py are sync
`def`, which FastAPI runs in AnyIO's threadpool -- 40 threads. rag_chat blocks
on Groq for seconds; predict_anomaly blocks on joblib. Saturate that pool and
every remaining sync route queues behind it, including any health check that is
also a sync def.

Point a Kubernetes livenessProbe at a queued endpoint and the failure
amplifies itself: load -> probe times out -> kubelet kills a HEALTHY pod -> its
traffic moves to the survivors -> they saturate too. Scaling up causes the
outage it was added to prevent, and it presents as "Kubernetes keeps
restarting my pods under load".
"""

import ast
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

MAIN = PROJECT_ROOT / "main.py"


def _route_handlers():
    """{path: FunctionDef|AsyncFunctionDef} for every @app.get route."""
    source = MAIN.read_text(encoding="utf-8")
    tree = ast.parse(source)
    found = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in node.decorator_list:
            if not isinstance(deco, ast.Call):
                continue
            func = deco.func
            if not (isinstance(func, ast.Attribute) and func.attr == "get"):
                continue
            if not (isinstance(func.value, ast.Name) and func.value.id == "app"):
                continue
            if deco.args and isinstance(deco.args[0], ast.Constant):
                found[deco.args[0].value] = node
    return found


@pytest.mark.parametrize("path", ["/healthz", "/readyz"])
def test_the_probe_endpoints_are_async(path):
    """
    THE test in this file.

    A sync probe queues behind the threadpool exactly when the pod is busiest,
    so the orchestrator kills healthy pods under load. Async runs on the event
    loop and cannot queue behind threadpool work.
    """
    handler = _route_handlers().get(path)
    assert handler is not None, f"{path} does not exist"
    assert isinstance(handler, ast.AsyncFunctionDef), (
        f"{path} is a sync def. It will queue behind the 40-thread AnyIO pool "
        f"under load, and an orchestrator probing it will kill healthy pods."
    )


def test_liveness_touches_nothing():
    """
    Liveness answers "is this process alive", not "is the system healthy".
    Checking a dependency here means a database blip restarts every pod, which
    does not fix the database and discards warm processes.
    """
    source = MAIN.read_text(encoding="utf-8")
    handler = _route_handlers()["/healthz"]
    body = ast.get_source_segment(source, handler) or ""
    for forbidden in ("session", "engine", "ping", "storage", "requests.",
                      "current_state"):
        assert forbidden not in body, (
            f"/healthz references {forbidden!r}; liveness must not depend on "
            f"anything that can be slow or down"
        )


def test_readiness_checks_a_dependency_and_can_fail():
    """Readiness that always returns 200 is not readiness."""
    source = MAIN.read_text(encoding="utf-8")
    body = ast.get_source_segment(source, _route_handlers()["/readyz"]) or ""
    assert "503" in body, "/readyz can never report not-ready"
    assert "ping" in body, "/readyz checks no dependency"


def test_readiness_leaks_no_detail_to_an_unauthenticated_caller():
    """
    /healthz and /readyz cannot be gated -- a kubelet presents no credentials --
    so they are world-readable, and must therefore say nothing but booleans.

    The first version of /readyz returned str(exc) from the database check. A
    SQLAlchemy connection error embeds the DSN, which carries the password. The
    reason belongs in the log, not the response body.
    """
    source = MAIN.read_text(encoding="utf-8")
    body = ast.get_source_segment(source, _route_handlers()["/readyz"]) or ""
    assert "str(exc)" not in body, (
        "/readyz puts an exception string in its response; a database "
        "connection error contains the DSN and its password"
    )
    assert "logger" in body, "the failure reason is not logged anywhere"


def test_status_is_documented_as_not_a_probe():
    """
    /api/status is the config report and does real work. It was the obvious
    thing to probe, and probing it is the trap above.
    """
    source = MAIN.read_text(encoding="utf-8")
    handler = _route_handlers()["/api/status"]
    doc = ast.get_docstring(handler) or ""
    assert "NOT a probe" in doc or "not a probe" in doc.lower(), (
        "/api/status does not warn that it must not be used as a probe"
    )


# --- roles ------------------------------------------------------------------

def test_role_gates_both_the_agent_loop_and_the_poller():
    """
    The collection side is single-writer. Two workers means two agent cycles
    against one Groq allowance already at its ceiling, and two schedules
    against one personal social account.

    The poller must be gated too, and on ROLE rather than DISABLE_AGENT_LOOP:
    otherwise every api replica polls storage and broadcasts the same events to
    its own WebSocket clients.
    """
    source = MAIN.read_text(encoding="utf-8")
    tree = ast.parse(source)
    startup = next(
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "startup_event"
    )
    body = ast.get_source_segment(source, startup) or ""

    assert 'os.getenv("ROLE")' in body, "startup does not read ROLE"
    assert "database_polling_loop" in body and "if collects" in body, (
        "the storage poller is not gated on role, so every api replica would "
        "poll and broadcast"
    )


def test_unset_role_keeps_todays_behaviour():
    """A single local process must still do both without configuration."""
    source = MAIN.read_text(encoding="utf-8")
    startup = next(
        n for n in ast.walk(ast.parse(source))
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "startup_event"
    )
    body = ast.get_source_segment(source, startup) or ""
    assert 'role in ("", "worker")' in body, (
        "an unset ROLE must mean 'do both', or running locally silently stops "
        "collecting"
    )


def test_the_loop_interval_is_configurable():
    """
    Adding replicas adds zero tokens against Groq's per-minute limit. The
    interval is the knob that actually reduces spend, and there was no way to
    change it without editing main.py.
    """
    source = MAIN.read_text(encoding="utf-8")
    assert "AGENT_LOOP_INTERVAL_SECONDS" in source


# --- the public guard -------------------------------------------------------

def test_the_public_guard_runs_at_startup_not_only_in_the_cli():
    """
    REGRESSION in waiting. Every one of these checks lived in
    scripts/serve_public.py, which is NOT the container entrypoint -- the image
    runs start_backend.sh. Containerising the API therefore dropped all of them
    at exactly the moment it became internet-facing.
    """
    source = MAIN.read_text(encoding="utf-8")
    assert "enforce_at_startup" in source, (
        "main.py never calls the public-hosting guard, so it applies only when "
        "serve_public.py launches the server"
    )


def test_the_cli_delegates_rather_than_duplicating():
    """Two copies of a safety check drift, and the one that drifts is the one
    nobody is running."""
    cli = (PROJECT_ROOT / "scripts" / "serve_public.py").read_text(encoding="utf-8")
    assert "public_guard" in cli, "serve_public.py does not use the shared module"
    assert "AUTH_ENFORCED is not 1" not in cli, (
        "serve_public.py still carries its own copy of the checks"
    )


def test_the_guard_is_inert_unless_public_hosting_is_declared(monkeypatch):
    """Development on a laptop is not the same risk as being reachable."""
    from src.config.public_guard import enforce_at_startup

    monkeypatch.delenv("PUBLIC_HOSTING", raising=False)
    enforce_at_startup()  # must not raise despite nothing else being set


def test_the_guard_refuses_a_misconfigured_public_instance(monkeypatch):
    from src.config.public_guard import enforce_at_startup

    monkeypatch.setenv("PUBLIC_HOSTING", "1")
    monkeypatch.delenv("AUTH_ENFORCED", raising=False)
    monkeypatch.delenv("AUTH_SECRET", raising=False)

    with pytest.raises(RuntimeError) as excinfo:
        enforce_at_startup()
    assert "AUTH_ENFORCED" in str(excinfo.value)


def test_a_container_bind_does_not_trip_the_host_check(monkeypatch):
    """
    A container binds 0.0.0.0 by necessity and the orchestrator controls
    exposure. Failing every containerised start on that would make the guard
    something people disable.
    """
    from src.config.public_guard import validate

    monkeypatch.setenv("AUTH_ENFORCED", "1")
    monkeypatch.setenv("AUTH_SECRET", "x" * 40)
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://example.com")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "a@b.c")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "a-long-enough-password")

    assert validate("") == []
    assert any("0.0.0.0" in p for p in validate("0.0.0.0"))
