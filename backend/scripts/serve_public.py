"""
backend/scripts/serve_public.py
Serve this machine to the internet, with the settings that make that safe.

WHY HOST LOCALLY AT ALL
-----------------------
Render's free tier is 512 MB. The API and TensorFlow cannot both fit, so the
weather (LSTM), currency (GRU) and stock models report `unavailable` there. On
a real machine all four models run in-process -- verified on 14.8 GB:

    weather    status=success
    currency   status=success

That is three dashboard cards going from "not running on this deployment" to
live predictions, plus no 15-minute spin-down and no ~50 s cold start.

THE COST, STATED PLAINLY
------------------------
The submission requirement is "a live URL where the application functions as
intended". A laptop satisfies that only while it is awake, online, and running
this process. If judging happens overnight, or on the venue wifi, or a day
later, the link is dead and the requirement is simply failed. Keep the hosted
deployment alive as a fallback and record a video -- neither costs anything.

WHAT THIS SCRIPT IS FOR
-----------------------
Five settings are easy to forget and each one is quietly serious when the
server is a personal machine on a public URL:

  AUTH_ENFORCED=1      without it, anyone with the URL can write to the API and
                       pair their own connector to your instance
  AUTH_SECRET          without it a random key is minted per boot, so every
                       session dies on restart
  CORS_ALLOW_ORIGINS   without it CORS falls back to '*'
  DATABASE_URL         optional here -- a local SQLite file is durable on a
                       laptop, unlike on Render
  host binding         a tunnel reaches 127.0.0.1 fine; 0.0.0.0 also exposes
                       this to everyone on the local network, which at a venue
                       means everyone at the venue

It refuses to start on the dangerous combinations rather than warning about
them, because a warning scrolls past.

    python scripts/serve_public.py --check      # validate and exit
    python scripts/serve_public.py              # validate, then serve
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# Bind to loopback by default. cloudflared/ngrok run on this machine and connect
# outward, so they reach 127.0.0.1 perfectly well -- and unlike 0.0.0.0 it does
# not also hand the API to every other device on the network.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def _flag(name: str) -> bool:
    return (os.getenv(name, "") or "").strip().lower() in ("1", "true", "yes", "on")


def _isset(name: str) -> bool:
    return bool((os.getenv(name) or "").strip())


def validate(host: str) -> list[str]:
    """Blocking problems. Empty list means it is safe to serve."""
    problems: list[str] = []

    if not _flag("AUTH_ENFORCED"):
        problems.append(
            "AUTH_ENFORCED is not 1.\n"
            "      Every route would be publicly writable, including the "
            "connector pairing\n"
            "      endpoints -- anyone with the URL could attach their own "
            "connector."
        )

    secret = (os.getenv("AUTH_SECRET") or "").strip()
    if not secret:
        problems.append(
            "AUTH_SECRET is unset.\n"
            "      A random key would be minted per boot, logging everyone out "
            "on restart.\n"
            '      python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )
    elif len(secret) < 32:
        problems.append(f"AUTH_SECRET is {len(secret)} chars; HS256 needs >= 32.")

    if not _isset("CORS_ALLOW_ORIGINS"):
        problems.append(
            "CORS_ALLOW_ORIGINS is unset, so CORS falls back to '*'.\n"
            "      Set it to your frontend origin."
        )

    if not _isset("BOOTSTRAP_ADMIN_EMAIL") or not _isset("BOOTSTRAP_ADMIN_PASSWORD"):
        problems.append(
            "BOOTSTRAP_ADMIN_EMAIL / BOOTSTRAP_ADMIN_PASSWORD are not both set.\n"
            "      There is no self-registration, so with an empty user table "
            "nobody can log in\n"
            "      and every authenticated route stays 401."
        )

    if host == "0.0.0.0":
        problems.append(
            "Binding 0.0.0.0 exposes this API to every device on the local "
            "network.\n"
            "      A tunnel does not need it -- it connects outward from this "
            "machine.\n"
            "      Pass --host 0.0.0.0 --i-mean-it if you really want LAN "
            "access."
        )

    return problems


def report_config() -> None:
    """What this instance will actually be able to do."""
    os.environ.setdefault("PUBLIC_HOSTING", "1")

    from src import preflight

    pf = preflight.run(force=True)
    print("\nConfiguration")
    print("-" * 68)
    for check in pf.checks:
        mark = "ok  " if check.ok else ("FAIL" if check.severity == "error" else "warn")
        print(f"  [{mark}] {check.key}")
        if not check.ok:
            print(f"         {check.consequence}")
            if check.detail:
                print(f"         {check.detail}")

    # The reason to host locally in the first place -- worth confirming rather
    # than assuming, since a missing artifact degrades silently.
    print("\nML models")
    print("-" * 68)
    import importlib.util as iu

    tf = iu.find_spec("tensorflow") is not None
    sk = iu.find_spec("sklearn") is not None
    print(f"  tensorflow  {'yes' if tf else 'NO'}   -> weather, currency, stock "
          f"{'run in-process' if tf else 'will report unavailable'}")
    print(f"  scikit-learn {'yes' if sk else 'NO'}  -> anomaly detection "
          f"{'active' if sk else 'falls back to heuristic'}")
    if not tf:
        print("\n  NOTE: install the FULL set for local hosting -- that is the "
              "whole point.\n        pip install -r requirements.txt   "
              "(not requirements-service.txt)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--check", action="store_true",
                        help="validate and exit without serving")
    parser.add_argument("--i-mean-it", action="store_true",
                        help="allow --host 0.0.0.0")
    args = parser.parse_args()

    os.chdir(BACKEND)
    os.environ["PUBLIC_HOSTING"] = "1"

    problems = validate(args.host)
    if args.i_mean_it:
        problems = [p for p in problems if "0.0.0.0" not in p]

    report_config()

    if problems:
        print("\nRefusing to serve")
        print("-" * 68)
        for problem in problems:
            print(f"  !  {problem}")
        print(
            "\nThese are blocking because the server is a personal machine on a\n"
            "public URL. A warning here scrolls past; a refusal does not.\n"
            "See HOSTING.md for a working .env.\n"
        )
        return 1

    print("\n  All checks passed.\n")
    if args.check:
        return 0

    print(f"Serving on http://{args.host}:{args.port}")
    print("Expose it with:  cloudflared tunnel --url "
          f"http://{args.host}:{args.port}\n")

    import uvicorn

    uvicorn.run("main:app", host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
