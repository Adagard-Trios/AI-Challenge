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
PUBLIC = ["/", "/api/status", "/api/models/health"]

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
    import re

    source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    lines = source.splitlines()
    ungated = []

    for i, line in enumerate(lines):
        m = re.match(r'^@app\.(get|post|delete|put)\("([^"]+)"', line)
        if not m:
            continue
        path = m.group(2)
        if path in PUBLIC:
            continue
        j = i + 1
        while j < len(lines) and lines[j].lstrip().startswith("@"):
            j += 1
        if j < len(lines) and "Depends(require_user)" not in lines[j]:
            ungated.append(path)

    assert not ungated, (
        f"routes with no auth dependency: {ungated}. Add "
        "Depends(require_user), or add the path to PUBLIC here if it is "
        "genuinely meant to be open."
    )
