"""
src/preflight.py
What is configured, what isn't, and what that costs you.

This exists because of a specific failure mode this codebase keeps producing:
configuration that is missing degrades silently into something that looks like
it works. A missing DATABASE_URL falls back to a SQLite file on an ephemeral
disk. A missing BOOTSTRAP_ADMIN_EMAIL makes _seed_admin() return early with no
log line, so nobody can ever log in and nothing anywhere says why. A missing
GROQ_API_KEY leaves every event unclassified with severity None.

Each of those is a reasonable local-development default and a production
outage. The difference is not the behaviour -- it is that in production nobody
is watching the logs at boot.

So: one place that knows what each variable buys, reported twice. Once at
startup as ERROR/WARNING lines you cannot miss, and once on /api/status, which
is reachable without shell access and is what you check when the deployed thing
is behaving oddly.

Nothing here raises. Enforcement belongs to auth/config.py, which fails closed
on the settings that must not be defaulted around. This module only reports.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

logger = logging.getLogger("Roger.preflight")

# Load .env here rather than relying on someone else having done it.
#
# This module reports missing configuration, so it must not depend on import
# ordering to see the configuration that exists. It did at first: main.py runs
# the preflight before the auth block, and auth/config.py is what calls
# load_dotenv() -- so a perfectly well configured instance was reported as
# missing GROQ_API_KEY, purely because nothing had read the file yet.
#
# A checker that cries wolf is worse than no checker, because the next real
# warning gets ignored too. Same two paths auth/config.py uses.
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")   # backend/.env
    load_dotenv()                                                   # repo-root .env
except ImportError:  # pragma: no cover
    pass


def _isset(name: str) -> bool:
    return bool((os.getenv(name) or "").strip())


def _flag(name: str, default: str = "0") -> bool:
    return (os.getenv(name, default) or "").strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Check:
    """
    One configuration fact.

    `consequence` is the important field and the reason this is a dataclass
    rather than a list of names: a variable name in an error message tells you
    nothing you could not read off the traceback. What you need at 2am is what
    stopped working.
    """

    key: str
    ok: bool
    consequence: str
    severity: str = "error"      # error | warning | info
    detail: str = ""


@dataclass
class Preflight:
    checks: List[Check] = field(default_factory=list)

    @property
    def failures(self) -> List[Check]:
        return [c for c in self.checks if not c.ok and c.severity == "error"]

    @property
    def warnings(self) -> List[Check]:
        return [c for c in self.checks if not c.ok and c.severity == "warning"]

    @property
    def healthy(self) -> bool:
        return not self.failures

    def as_dict(self) -> dict:
        """Shape served on /api/status. Never includes a value, only whether one exists."""
        return {
            "healthy": self.healthy,
            "failures": [
                {"key": c.key, "consequence": c.consequence, "detail": c.detail}
                for c in self.failures
            ],
            "warnings": [
                {"key": c.key, "consequence": c.consequence, "detail": c.detail}
                for c in self.warnings
            ],
            "configured": sorted(c.key for c in self.checks if c.ok),
        }


def _database_check() -> Check:
    url = (os.getenv("DATABASE_URL") or "").strip()
    if not url:
        # The SQLite fallback is only dangerous where the disk is disposable.
        # On a laptop it is an ordinary file that survives reboots, so calling
        # it data loss would be false -- and a warning that is wrong in your
        # situation is a warning you learn to ignore.
        if _flag("PUBLIC_HOSTING"):
            return Check(
                "DATABASE_URL",
                ok=True,
                consequence=(
                    "Unset, so accounts live in a local SQLite file. Durable on "
                    "this machine -- back up backend/data/auth.db, since it is "
                    "now the only copy."
                ),
            )
        return Check(
            "DATABASE_URL",
            ok=False,
            consequence=(
                "Falling back to SQLite on the container's ephemeral disk. Every "
                "account, exposure profile, story and paired device is destroyed "
                "on the next deploy, restart or spin-down."
            ),
            detail="Set the Supabase transaction-pooler URL (port 6543).",
        )

    # Right database, wrong port is the failure that looks like success: it
    # connects, then throws "prepared statement _pg3_0 already exists" once
    # traffic warms up, which reads as a random intermittent fault.
    if "pooler.supabase.com" in url and ":6543" not in url:
        return Check(
            "DATABASE_URL",
            ok=False,
            severity="warning",
            consequence=(
                "Supabase pooler host on a non-transaction port. Prepared "
                "statements will collide intermittently under load."
            ),
            detail="Use port 6543 so NullPool and prepare_threshold=None engage.",
        )

    return Check("DATABASE_URL", ok=True, consequence="Persistent Postgres in use.")


def _admin_check() -> Check:
    have_email = _isset("BOOTSTRAP_ADMIN_EMAIL")
    have_password = _isset("BOOTSTRAP_ADMIN_PASSWORD")

    if have_email and have_password:
        return Check(
            "BOOTSTRAP_ADMIN_EMAIL",
            ok=True,
            consequence="An initial admin can be seeded into an empty user table.",
        )

    missing = [
        name
        for name, present in (
            ("BOOTSTRAP_ADMIN_EMAIL", have_email),
            ("BOOTSTRAP_ADMIN_PASSWORD", have_password),
        )
        if not present
    ]
    return Check(
        "BOOTSTRAP_ADMIN_EMAIL",
        ok=False,
        # Only fatal when tokens are actually required. With enforcement off the
        # API is open, so nobody being able to log in costs nothing.
        severity="error" if _flag("AUTH_ENFORCED") else "warning",
        consequence=(
            "No user can log in. There is no self-registration, so the first "
            "account can only come from these variables; the seeder returns "
            "early without them and every authenticated route stays 401."
        ),
        detail=f"Missing: {', '.join(missing)}.",
    )


def _secret_check() -> Check:
    secret = (os.getenv("AUTH_SECRET") or "").strip()
    if not secret:
        return Check(
            "AUTH_SECRET",
            ok=False,
            severity="error" if _flag("AUTH_ENFORCED") else "warning",
            consequence=(
                "A random signing key is generated per boot, so every session "
                "is invalidated on every restart -- users are logged out at "
                "unpredictable times with no error to explain it."
            ),
            detail="python -c \"import secrets; print(secrets.token_urlsafe(48))\"",
        )
    if len(secret) < 32:
        return Check(
            "AUTH_SECRET",
            ok=False,
            consequence="Too short for HS256; token signing is weak.",
            detail=f"{len(secret)} chars, needs >= 32.",
        )
    return Check("AUTH_SECRET", ok=True, consequence="Sessions survive restarts.")


def _auth_enforced_check() -> Check:
    if _flag("AUTH_ENFORCED"):
        return Check("AUTH_ENFORCED", ok=True, consequence="API routes require a token.")

    # "Acceptable locally" stops being true the moment localhost is on the
    # internet. Hosting from a laptop behind a tunnel is a reasonable choice --
    # it is the only way to run all four ML models -- but it turns this from a
    # development convenience into an open door on a personal machine.
    public = _flag("PUBLIC_HOSTING")
    return Check(
        "AUTH_ENFORCED",
        ok=False,
        severity="error" if public else "warning",
        consequence=(
            "Every API route is publicly readable AND writable, including the "
            "connector pairing endpoints -- so anyone with the URL can pair "
            "their own connector to this instance."
            if public else
            "Every API route is publicly readable AND writable, including "
            "connector pairing. Acceptable locally; not in production."
        ),
        detail=(
            "PUBLIC_HOSTING=1 means this machine is reachable from the "
            "internet. Set AUTH_ENFORCED=1."
            if public else
            "Set to 1 once the frontend sends tokens."
        ),
    )


def _public_exposure_check() -> Check:
    """
    Extra care when the server is a laptop on a tunnel rather than a container.

    Hosting locally is a legitimate trade-off -- a 512 MB free instance cannot
    hold TensorFlow, so weather, currency and stock predictions only exist on a
    real machine. The cost is that the machine is someone's own, and the blast
    radius of a mistake is their filesystem rather than a disposable container.
    """
    if not _flag("PUBLIC_HOSTING"):
        return Check(
            "PUBLIC_HOSTING",
            ok=True,
            consequence="Not marked as publicly exposed.",
        )

    problems = []
    if not _flag("AUTH_ENFORCED"):
        problems.append("AUTH_ENFORCED is off")
    if not _isset("CORS_ALLOW_ORIGINS"):
        problems.append("CORS_ALLOW_ORIGINS is unset, so CORS falls back to '*'")
    if not _isset("AUTH_SECRET"):
        problems.append("AUTH_SECRET is unset, so sessions die on every restart")

    if problems:
        return Check(
            "PUBLIC_HOSTING",
            ok=False,
            consequence=(
                "This machine is exposed to the internet with: "
                + "; ".join(problems) + "."
            ),
            detail="Fix these before sharing the URL.",
        )

    return Check(
        "PUBLIC_HOSTING",
        ok=True,
        consequence="Exposed publicly, with auth enforced and CORS locked.",
    )


def _groq_check() -> Check:
    if _isset("GROQ_API_KEY"):
        return Check("GROQ_API_KEY", ok=True, consequence="LLM classification active.")
    return Check(
        "GROQ_API_KEY",
        ok=False,
        consequence=(
            "No LLM. Events arrive unclassified -- severity and fake-news score "
            "are null, story briefs are never written, and entity extraction "
            "does not run."
        ),
    )


def _cors_check() -> Check:
    if _isset("CORS_ALLOW_ORIGINS"):
        return Check("CORS_ALLOW_ORIGINS", ok=True, consequence="CORS locked to the frontend origin.")
    return Check(
        "CORS_ALLOW_ORIGINS",
        ok=False,
        severity="warning",
        consequence=(
            "CORS falls back to '*', which forces credentials off -- the "
            "browser will not send auth cookies cross-origin."
        ),
        detail="Set to the deployed frontend origin.",
    )


def _anomaly_check() -> Check:
    """
    The one ML model that genuinely runs on a 512 MB instance.

    Two things have to be true, and the second is the one that bit us: sklearn
    to run the isolation forest, AND an embedder to feed it. The committed
    768-dim models need transformers + torch, which do not fit -- and their
    vectorizer returns zeros rather than failing, so without this check the
    endpoint reports "ml_active" while scoring identical vectors.
    """
    if (os.getenv("ANOMALY_SERVICE_URL") or "").strip():
        return Check("ANOMALY_SERVICE_URL", ok=True, consequence="Anomaly detection runs remotely.")

    try:
        import sklearn  # noqa: F401
    except ImportError:
        return Check(
            "scikit-learn",
            ok=False,
            consequence=(
                "Anomaly detection cannot run, so /api/anomalies falls back to "
                "labelled heuristic scoring and no ML inference runs."
            ),
            detail="Add scikit-learn to requirements-service.txt.",
        )

    from pathlib import Path

    model = (
        Path(__file__).resolve().parent.parent.parent
        / "models" / "anomaly-detection" / "artifacts" / "model_trainer"
        / "isolation_forest_minilm.joblib"
    )
    if not model.exists():
        return Check(
            "anomaly_model",
            ok=False,
            consequence=(
                "No embedding model that this container can compute. The "
                "768-dim forests need transformers+torch; /api/anomalies uses "
                "heuristic scoring instead."
            ),
            detail="python scripts/train_anomaly_minilm.py",
        )

    try:
        from src import embeddings

        if not embeddings.available():
            return Check(
                "onnx_embedder",
                ok=False,
                consequence=(
                    "The MiniLM model is present but its embedder will not "
                    "load, so anomaly detection cannot score anything."
                ),
                detail="chromadb's ONNX all-MiniLM-L6-v2 failed to initialise.",
            )
    except Exception as exc:  # noqa: BLE001
        return Check("onnx_embedder", ok=False,
                     consequence="Embedder unavailable; anomaly detection is off.",
                     detail=str(exc))

    return Check(
        "anomaly_model",
        ok=True,
        consequence="Anomaly detection runs in-process on 384-dim ONNX MiniLM.",
    )


CHECKS: List[Callable[[], Check]] = [
    _database_check,
    _secret_check,
    _admin_check,
    _auth_enforced_check,
    _public_exposure_check,
    _groq_check,
    _cors_check,
    _anomaly_check,
]


_cached: Optional[Preflight] = None


def run(*, force: bool = False) -> Preflight:
    global _cached
    if _cached is not None and not force:
        return _cached

    checks = []
    for check in CHECKS:
        try:
            checks.append(check())
        except Exception as exc:  # noqa: BLE001
            # A broken check must never be the thing that stops startup.
            logger.warning("[preflight] check %s raised: %s", check.__name__, exc)

    _cached = Preflight(checks=checks)
    return _cached


def report(preflight: Optional[Preflight] = None) -> Preflight:
    """
    Log the result. Called once at startup.

    Deliberately noisy about failures: the whole point is that these problems
    are currently invisible.
    """
    pf = preflight or run()

    for check in pf.failures:
        logger.error(
            "[preflight] %s is not configured -- %s%s",
            check.key, check.consequence, f" ({check.detail})" if check.detail else "",
        )
    for check in pf.warnings:
        logger.warning(
            "[preflight] %s -- %s%s",
            check.key, check.consequence, f" ({check.detail})" if check.detail else "",
        )

    if pf.healthy:
        logger.info("[preflight] configuration OK (%d checks)", len(pf.checks))
    else:
        logger.error(
            "[preflight] %d configuration problem(s). The service will start, but "
            "the features above are not working. See /api/status.",
            len(pf.failures),
        )
    return pf


def reset() -> None:
    """Tests."""
    global _cached
    _cached = None
