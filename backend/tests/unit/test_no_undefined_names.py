"""
Static guard: no undefined names anywhere in the shipped source.

Motivation, from this codebase:

  - main.py:1572 read `_anomaly_model`; the global is `_anomaly_models`. Every
    call to /api/model/status raised NameError, caught by a broad `except` and
    returned as a generic error.
  - combinedAgentNode.py referenced `political_scores` after a refactor removed
    its assignment, so building the risk snapshot raised NameError on any cycle
    that produced a feed.

Both survived a 280-test suite, because a name that only resolves at runtime is
invisible to tests that never execute that exact line. pyflakes finds them in
about a second, and unlike a type checker it has no false-positive tax to pay
down first -- the codebase was already at zero when this test was written.
"""

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent

TARGETS = ["src", "main.py", "app.py", "auth", "connector"]


@pytest.fixture(scope="module")
def pyflakes_output():
    try:
        import pyflakes  # noqa: F401
    except ImportError:
        pytest.skip("pyflakes not installed")

    proc = subprocess.run(
        [sys.executable, "-m", "pyflakes", *TARGETS],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    return proc.stdout + proc.stderr


def test_no_undefined_names(pyflakes_output):
    offenders = [
        line for line in pyflakes_output.splitlines()
        if "undefined name" in line.lower()
    ]
    assert not offenders, (
        "undefined name(s) -- these are NameErrors waiting for the right code "
        "path:\n    " + "\n    ".join(offenders)
    )


# Deliberately NOT asserting on "redefinition of unused". Every current hit is
# a false positive -- the _optional_user auth fallback stub that a conditional
# import is meant to replace, a Pydantic field named `status`, and a redundant
# import inside `if __name__ == "__main__"`. Enforcing it would produce
# suppressions rather than safety.


def test_no_fstring_missing_placeholders(pyflakes_output):
    """An f-string with no placeholders is usually a forgotten interpolation."""
    offenders = [
        line for line in pyflakes_output.splitlines()
        if "f-string is missing placeholders" in line.lower()
    ]
    assert not offenders, "suspect f-string(s):\n    " + "\n    ".join(offenders)
