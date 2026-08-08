#!/usr/bin/env python
"""
scripts/collector.py
The credentialed half, on your own machine.

WHY THIS EXISTS
---------------
Social collection cannot run in the cluster, at any memory size. Connecting an
account opens a VISIBLE browser so a human can complete 2FA, and the session is
encrypted to that machine's OS keyring. A pod has neither, and
src/social/routes.py now refuses with a 503 that points here rather than
failing somewhere inside Playwright.

So the split is:

    cluster   read path and reasoning path. Holds NO credentials.
    host      this. Credentialed write path.

They share Redis and Postgres and nothing else, which is also the honest
security story: the internet-facing half has nothing worth stealing.

WHAT IT DOES NOT DO
-------------------
It does not log in. Connecting an account is still a human sitting in front of
a browser, done once from the dashboard on this machine. This collects with
sessions that already exist, on a schedule, and stops when there are none.

THE SAFETY PROPERTIES IT MUST NOT BYPASS
----------------------------------------
It collects through the same registry the agents use, so it passes the same
pacing gate, the same daily budget and the same challenge backoff. With
REDIS_URL set those are SHARED with the cluster, so the host and the worker
cannot each spend a full allowance against one account without the other
noticing. Scraping "directly" from here would be one line shorter and is
exactly how an account gets banned.

    python scripts/collector.py                # loop, every 15 minutes
    python scripts/collector.py --once         # one pass and exit
    python scripts/collector.py --check        # report and exit, collect nothing
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("collector")

# Matches the pacing gate's own minimum. Collecting more often than the gate
# allows would simply be refused, so a shorter loop is wasted wakeups; longer
# is fine and safer.
DEFAULT_INTERVAL_SECONDS = 900


def _load_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT / ".env")
    except Exception:  # noqa: BLE001
        pass


def describe_environment() -> dict:
    """What this process can actually reach. Printed before anything runs."""
    from src.runtime.redis_client import configured as redis_configured

    facts = {
        "database": "shared (DATABASE_URL)" if (os.getenv("DATABASE_URL") or "").strip()
        else "LOCAL SQLite -- posts will not reach the cluster",
        "pacing": "shared via Redis" if redis_configured()
        else "PER-PROCESS -- unsafe if the cluster also collects",
    }

    try:
        import playwright.sync_api  # noqa: F401

        facts["playwright"] = "installed"
    except Exception:  # noqa: BLE001
        facts["playwright"] = "MISSING -- install the full requirements.txt"

    try:
        from src.social.service import get_service

        # accounts() returns a LIST of per-platform dicts, not a mapping.
        facts["connected"] = ", ".join(
            a["platform"] for a in (get_service().accounts() or [])
            if isinstance(a, dict) and a.get("connected")
        ) or "none"
    except Exception as exc:  # noqa: BLE001
        facts["connected"] = f"could not read the session store: {exc}"

    return facts


def collect_once() -> dict:
    """
    One pass over every connected account.

    Goes through registry.run, NOT the scrapers directly, so the pacing gate,
    the daily budget and the challenge backoff all apply. A platform inside its
    cooling-off window returns "paced", which is a normal answer and not a
    failure -- that distinction cost a day to find once already.
    """
    from src.scrapers import registry
    from src.social.service import get_service

    # Point the scrapers at the encrypted session store this machine owns.
    #
    # Without this the registry uses NullCredentialStore -- its default, and
    # the right default for a server that should hold no credentials -- and
    # reports "No account connected" for an account that IS connected. main.py
    # calls this at startup; a script does not get that for free, and the two
    # disagreeing is precisely the bug shape this project keeps producing: one
    # path reads the session store, the other asks somewhere else.
    from src.social import credential_bridge

    credential_bridge.install()

    results: dict = {}
    try:
        accounts = get_service().accounts() or []
    except Exception as exc:  # noqa: BLE001
        logger.error("could not read connected accounts: %s", exc)
        return results

    connected = [a["platform"] for a in accounts
                 if isinstance(a, dict) and a.get("connected")]
    if not connected:
        logger.info("no connected accounts; nothing to collect")
        return results

    for platform in connected:
        tool = f"scrape_{platform}"
        if tool not in registry.REGISTRY:
            continue
        try:
            outcome = registry.run(tool, "sri lanka", max_items=10)
            status = outcome.get("status")
            count = outcome.get("count", 0)
            results[platform] = {"status": status, "count": count}
            if status == "paced":
                logger.info("%s: paced, ~%ss remaining -- the account is "
                            "connected and working", platform,
                            outcome.get("retry_after_seconds", "?"))
            elif status == "ok":
                logger.info("%s: collected %d posts", platform, count)
            else:
                logger.warning("%s: %s -- %s", platform, status,
                               outcome.get("reason", ""))
        except Exception as exc:  # noqa: BLE001
            logger.error("%s: collection failed: %s", platform, exc)
            results[platform] = {"status": "error", "error": str(exc)}

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="one pass, then exit")
    parser.add_argument("--check", action="store_true",
                        help="report the environment and exit")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_SECONDS,
                        help=f"seconds between passes (default "
                             f"{DEFAULT_INTERVAL_SECONDS})")
    args = parser.parse_args()

    _load_env()

    # This process IS the machine that holds sessions, so the flag the cluster
    # sets must not be inherited from a shared .env.
    if (os.getenv("DISABLE_LOCAL_SOCIAL_SESSIONS") or "").strip().lower() in (
            "1", "true", "yes", "on"):
        logger.info("DISABLE_LOCAL_SOCIAL_SESSIONS is set in this environment; "
                    "clearing it for this process -- it is meant for the "
                    "cluster, and this is the machine that holds the sessions")
        os.environ.pop("DISABLE_LOCAL_SOCIAL_SESSIONS", None)

    print("\nRoger collector -- the credentialed half\n" + "-" * 44)
    for key, value in describe_environment().items():
        print(f"  {key:<11} {value}")
    print()

    if args.check:
        return 0

    if args.once:
        collect_once()
        return 0

    logger.info("collecting every %ss; Ctrl-C to stop", args.interval)
    try:
        while True:
            collect_once()
            time.sleep(args.interval)
    except KeyboardInterrupt:
        logger.info("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
