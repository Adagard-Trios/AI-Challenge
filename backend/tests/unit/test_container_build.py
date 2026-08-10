"""
The container build is buildable.

`docker compose up` had never succeeded. The compose file was broken in four
independent ways, any one of which fails the first build, and the most
important of them was that `frontend/Dockerfile` did not exist at all -- so the
build aborted before anything ran.

These are static guards rather than a real build, because Docker is not
available on every machine that runs this suite and a test that skips is not a
guard. They assert the specific things that were wrong, so the same four
mistakes cannot come back quietly.
"""

import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).parent.parent.parent.parent
COMPOSE = REPO / "docker-compose.yml"
COMPOSE_PROD = REPO / "docker-compose.prod.yml"


def _load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", [COMPOSE, COMPOSE_PROD])
def test_every_referenced_dockerfile_exists(path):
    """
    REGRESSION, and the fatal one. compose pointed at frontend/Dockerfile for
    months; the file did not exist, so the build failed before any service
    started.
    """
    config = _load(path)
    for name, service in config.get("services", {}).items():
        build = service.get("build")
        if not isinstance(build, dict):
            continue
        context = (REPO / build.get("context", ".")).resolve()
        dockerfile = context / build.get("dockerfile", "Dockerfile")
        assert dockerfile.is_file(), (
            f"{path.name} service {name!r} builds from {dockerfile}, "
            f"which does not exist"
        )


@pytest.mark.parametrize("path", [COMPOSE, COMPOSE_PROD])
def test_no_service_mounts_or_runs_a_path_that_does_not_exist(path):
    """
    REGRESSION. `command: python backend/api/main.py` resolved to
    /app/backend/backend/api/main.py because the image ends with
    WORKDIR /app/backend, and `volumes: ./src:/app/src` referenced a directory
    that lives at backend/src. Docker creates missing bind sources silently, so
    neither failed loudly.
    """
    config = _load(path)
    for name, service in config.get("services", {}).items():
        for mount in service.get("volumes", []) or []:
            if not isinstance(mount, str) or ":" not in mount:
                continue
            host = mount.split(":")[0]
            if not host.startswith("."):
                continue  # named volume, not a bind
            # A missing RUNTIME STATE directory is fine -- Docker creates it on
            # first run and it is gitignored by design. A missing SOURCE
            # directory is the bug: `./src:/app/src` silently mounted an empty
            # directory over nothing, because src/ lives at backend/src.
            if "/data/" in f"{host}/" or host.rstrip("/").endswith("/data"):
                continue
            assert (REPO / host).exists(), (
                f"{path.name} service {name!r} bind-mounts {host!r}, "
                f"which does not exist in the repo"
            )

        command = service.get("command")
        if isinstance(command, str) and "main.py" in command:
            assert "backend/api" not in command, (
                f"{path.name} service {name!r} runs {command!r}; there is no "
                f"backend/api/main.py"
            )


@pytest.mark.parametrize("path", [COMPOSE, COMPOSE_PROD])
def test_next_public_vars_are_build_args_not_runtime_env(path):
    """
    REGRESSION, and the subtlest of the four.

    Next inlines NEXT_PUBLIC_* into the client bundle at BUILD time. Supplying
    them as `environment` does precisely nothing, so the frontend shipped
    pointing at whatever was baked in -- and it fails as an opaque CORS error
    rather than anything naming the cause.

    Both names are required: eight components read NEXT_PUBLIC_API_URL while
    AnomalyDetection.tsx and StockPredictions.tsx read NEXT_PUBLIC_API_BASE.
    """
    config = _load(path)
    frontend = config.get("services", {}).get("frontend")
    if frontend is None:
        pytest.skip(f"{path.name} defines no frontend service")

    env = frontend.get("environment") or []
    env_names = [
        (e.split("=")[0] if isinstance(e, str) else e) for e in env
    ] if isinstance(env, list) else list(env)
    leaked = [n for n in env_names if str(n).startswith("NEXT_PUBLIC_")]
    assert not leaked, (
        f"{path.name} sets {leaked} as runtime environment; Next inlines "
        f"NEXT_PUBLIC_* at build time, so this has no effect"
    )

    args = (frontend.get("build") or {}).get("args") or {}
    for required in ("NEXT_PUBLIC_API_URL", "NEXT_PUBLIC_API_BASE"):
        assert required in args, (
            f"{path.name} frontend does not pass {required} as a build arg; "
            f"the panels reading it will call localhost in the container"
        )


def test_the_frontend_image_can_actually_be_assembled():
    """
    The Dockerfile depends on output:"standalone", and standalone does NOT
    include .next/static or public/. Copying only the standalone directory
    yields a server that returns HTML with no CSS or JS -- which reads as a
    broken build rather than a missing COPY.
    """
    config = (REPO / "frontend" / "next.config.ts").read_text(encoding="utf-8")
    assert '"standalone"' in config or "'standalone'" in config, (
        "frontend/Dockerfile copies .next/standalone, but next.config.ts does "
        "not set output:'standalone', so that directory is never produced"
    )

    dockerfile = (REPO / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    for required in (".next/standalone", ".next/static", "public"):
        assert required in dockerfile, (
            f"frontend/Dockerfile never copies {required}"
        )


def test_container_scripts_are_lf_not_crlf():
    """
    REGRESSION, and it only ever broke locally, which is why it survived.

    git stores these with LF, so Render -- which builds from the git checkout
    -- always worked. But core.autocrlf=true rewrites them to CRLF on Windows
    checkout, and `docker build` copies the WORKING TREE. A local image
    therefore got a CRLF entrypoint and died with

        /bin/bash^M: bad interpreter: No such file or directory

    .gitattributes now pins *.sh to eol=lf.
    """
    attributes = (REPO / ".gitattributes").read_text(encoding="utf-8")
    assert "*.sh text eol=lf" in attributes, (
        ".gitattributes does not pin shell scripts to LF, so a Windows "
        "checkout will hand CRLF to the container build"
    )

    entrypoint = REPO / "backend" / "scripts" / "start_backend.sh"
    body = entrypoint.read_bytes()
    assert b"\r" not in body, (
        f"{entrypoint.name} contains carriage returns; the container "
        f"entrypoint will fail with 'bad interpreter'"
    )
