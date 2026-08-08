"""
Route gating: AUTH_ENFORCED=1 must actually protect the legacy routes.

The auth package shipped before this and gated only its own endpoints -- all 38
pre-existing routes stayed wide open, so enforcing auth would have produced a
login wall in front of an API anyone could still read. These tests fail if that
regresses.

Run in their own process because AUTH_ENFORCED is read at import.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

pytestmark = pytest.mark.slow

# Public by design.
#   /api/status is render.yaml's healthCheckPath -- gating it kills every deploy.
#   /healthz and /readyz are orchestrator probes. A kubelet presents no
#     credentials, so gating them means every probe 401s and the pod is killed
#     as unhealthy while being perfectly fine. They are also deliberately
#     information-free for exactly this reason: /healthz returns {"ok": true}
#     and nothing else, and /readyz returns booleans about reachability, never
#     a hostname, DSN or version.
PUBLIC = ["/", "/api/status", "/api/models/health", "/healthz", "/readyz"]

# Representative gated routes across the surface.
GATED = ["/api/dashboard", "/api/feed", "/api/rivernet", "/api/anomalies",
         "/api/intel/config", "/api/trending"]

SCRIPT = r'''
import json, os, sys
os.chdir(r"{root}")
sys.path.insert(0, r"{root}")
from fastapi.testclient import TestClient
import main

out = {{"public": {{}}, "gated": {{}}}}
with TestClient(main.app) as c:
    for p in {public!r}:
        out["public"][p] = c.get(p).status_code
    for p in {gated!r}:
        out["gated"][p] = c.get(p).status_code
print("RESULT" + json.dumps(out))
'''


def _run(enforced: bool, tmp_path) -> dict:
    env = {
        **os.environ,
        "AUTH_ENFORCED": "1" if enforced else "0",
        "AUTH_SECRET": "g" * 48,
        "DATABASE_URL": f"sqlite:///{(tmp_path / 'gate.db').as_posix()}",
        "DISABLE_AUTO_TRAIN": "1",
        "DISABLE_AGENT_LOOP": "1",
        "GROQ_API_KEY": "dummy",
    }
    code = SCRIPT.format(root=str(PROJECT_ROOT), public=PUBLIC, gated=GATED)
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, env=env, timeout=300,
    )
    line = next((l for l in proc.stdout.splitlines() if l.startswith("RESULT")), None)
    assert line, f"no result\nstdout:\n{proc.stdout[-2000:]}\nstderr:\n{proc.stderr[-2000:]}"
    import json
    return json.loads(line[len("RESULT"):])


def test_enforced_gates_legacy_routes_but_not_the_health_check(tmp_path):
    """
    THE regression. Every data route must 401 without a token, and
    /api/status must still answer -- Render polls it and a 401 fails the deploy.
    """
    res = _run(True, tmp_path)

    assert res["public"]["/api/status"] == 200, (
        "/api/status must stay public; render.yaml uses it as healthCheckPath"
    )
    for path in PUBLIC:
        assert res["public"][path] != 401, f"{path} should be public"

    for path, status in res["gated"].items():
        assert status == 401, f"{path} returned {status}, expected 401 when enforced"


def test_not_enforced_leaves_everything_working(tmp_path):
    """
    With AUTH_ENFORCED=0 the existing frontend must keep working untouched --
    that is what makes the cutover a one-env-var change rather than a big bang.
    """
    res = _run(False, tmp_path)
    for path, status in {**res["public"], **res["gated"]}.items():
        assert status != 401, f"{path} returned 401 with enforcement off"


def test_every_route_is_either_gated_or_deliberately_public():
    """
    Static guard: a new @app route added without a dependency would silently be
    public. Catches that at review time rather than in production.
    """
    import ast

    # Parsed, not line-matched. The previous version checked only the single
    # line following the decorator, so a handler whose signature wrapped across
    # lines -- which any route with more than one dependency ends up doing --
    # was reported as ungated even though it was not. A guard that fires on
    # formatting teaches people to ignore it.
    source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    ungated = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        paths = []
        for decorator in node.decorator_list:
            if (isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and isinstance(decorator.func.value, ast.Name)
                    and decorator.func.value.id == "app"
                    and decorator.func.attr in ("get", "post", "delete", "put")
                    and decorator.args
                    and isinstance(decorator.args[0], ast.Constant)):
                paths.append(decorator.args[0].value)

        if not paths:
            continue

        # Any parameter defaulting to Depends(require_user), wherever it sits
        # in the signature.
        gated = any(
            isinstance(default, ast.Call)
            and isinstance(default.func, ast.Name)
            and default.func.id == "Depends"
            and default.args
            and isinstance(default.args[0], ast.Name)
            and default.args[0].id == "require_user"
            for default in [*node.args.defaults, *node.args.kw_defaults]
            if default is not None
        )

        if not gated:
            ungated.extend(p for p in paths if p not in PUBLIC)

    assert not ungated, (
        f"routes with no auth dependency: {ungated}. Add "
        "Depends(require_user), or add the path to PUBLIC here if it is "
        "genuinely meant to be open."
    )
