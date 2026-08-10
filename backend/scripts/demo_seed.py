#!/usr/bin/env python
"""
scripts/demo_seed.py
Populate a running install with illustrative data for a recorded demo.

THIS WRITES DATA THAT NOBODY COLLECTED. Every row it creates carries
DEMO_MARKER in its event_id or content, and `--remove` deletes exactly those
rows and nothing else, so the install returns to whatever it genuinely holds.

    python scripts/demo_seed.py --email demo@roger.lk --password <pw>
    python scripts/demo_seed.py --remove

The account is created if missing. Feeds, stories and the dashboard snapshot
are install-wide rather than per-user -- see main.py's /api/feeds and
/api/dashboard, which take a user only to require one -- so they appear for any
signed-in account. Collected posts ARE per user and are attached to the demo
account specifically.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("demo-seed")

# The one string that makes this reversible. It is embedded in every event_id
# so removal is an exact match rather than a guess at which rows looked fake.
DEMO_MARKER = "demo-seed"


def _now():
    return datetime.now(timezone.utc)


# Written to read like the pipeline's own output: a summary, a domain, a
# severity, and entities, because the UI ranks and filters on those.
EVENTS = [
    dict(domain="weather", severity="high", impact_type="risk", confidence=0.88,
         summary="Heavy rainfall warning issued for Western and Sabaragamuwa provinces; "
                 "Kelani basin levels rising through the next 24 hours.",
         entities=[{"name": "Kelani River", "type": "location"},
                   {"name": "Colombo", "type": "district"}]),
    dict(domain="power", severity="high", impact_type="risk", confidence=0.82,
         summary="CEB signals load-shedding risk in Gampaha and Kalutara as a "
                 "substation is taken offline for emergency repair.",
         entities=[{"name": "CEB", "type": "organisation"},
                   {"name": "Gampaha", "type": "district"}]),
    dict(domain="fuel", severity="medium", impact_type="risk", confidence=0.74,
         summary="CEYPETCO distribution to up-country stations delayed; queues "
                 "reported at Kandy and Nuwara Eliya outlets.",
         entities=[{"name": "CEYPETCO", "type": "organisation"},
                   {"name": "Kandy", "type": "district"}]),
    dict(domain="economy", severity="medium", impact_type="risk", confidence=0.79,
         summary="Rupee weakens against the dollar for a third consecutive session; "
                 "importers advised to review forward cover.",
         entities=[{"name": "LKR", "type": "currency"}]),
    dict(domain="economy", severity="low", impact_type="opportunity", confidence=0.71,
         summary="Tea auction prices firm on strong Middle East demand, lifting "
                 "margins for smallholder exporters.",
         entities=[{"name": "Colombo Tea Auction", "type": "market"}]),
    dict(domain="transport", severity="high", impact_type="risk", confidence=0.85,
         summary="Section of the A1 near Kadugannawa restricted after a landslip; "
                 "freight advised to route via Kurunegala.",
         entities=[{"name": "A1", "type": "route"},
                   {"name": "Kadugannawa", "type": "location"}]),
    dict(domain="water", severity="medium", impact_type="risk", confidence=0.68,
         summary="Water Board announces supply interruption across parts of Colombo "
                 "and Dehiwala for scheduled main repairs.",
         entities=[{"name": "NWSDB", "type": "organisation"},
                   {"name": "Dehiwala", "type": "district"}]),
    dict(domain="health", severity="medium", impact_type="risk", confidence=0.72,
         summary="Dengue case counts rising in Western Province; workplaces urged to "
                 "clear standing water on premises.",
         entities=[{"name": "Western Province", "type": "region"}]),
    dict(domain="market", severity="low", impact_type="opportunity", confidence=0.66,
         summary="Apparel export orders from the EU recover quarter on quarter, "
                 "with buyers shortening lead times.",
         entities=[{"name": "EU", "type": "market"}]),
    dict(domain="competitor", severity="low", impact_type="signal", confidence=0.64,
         summary="A competing logistics operator announces additional cold-chain "
                 "capacity in Katunayake from next month.",
         entities=[{"name": "Katunayake", "type": "location"}]),
]

DASHBOARD = {
    "total_events": len(EVENTS),
    "critical_count": 1,
    "risk_events": 7,
    "opportunity_events": 2,
    "active_domains": 8,
    "indices": [
        {"name": "Flood risk", "value": 72, "trend": "up", "domain": "weather"},
        {"name": "Power stability", "value": 41, "trend": "down", "domain": "power"},
        {"name": "Fuel availability", "value": 58, "trend": "down", "domain": "fuel"},
        {"name": "Currency pressure", "value": 66, "trend": "up", "domain": "economy"},
        {"name": "Transport continuity", "value": 47, "trend": "down", "domain": "transport"},
    ],
    "generated_at": _now().isoformat(),
    "source": DEMO_MARKER,
}

POSTS = [
    ("linkedin", "Port of Colombo reports a second day of berth congestion; "
                 "carriers are advising 48-hour delays on transhipment."),
    ("linkedin", "Chamber of Commerce briefing: importers should expect tighter "
                 "LC terms through the quarter."),
    ("twitter", "Kelani river level at Nagalagam Street continues to climb. "
                "Businesses along the bank should move stock now."),
    ("facebook", "Kandy depot confirms fuel bowsers delayed until tomorrow morning."),
]


def _get_or_create_user(email: str, password: str):
    from auth.db import session_scope
    from auth.models import DEFAULT_ROLE, User
    from auth.passwords import hash_password

    with session_scope() as db:
        user = db.query(User).filter(User.email == email.lower()).first()
        if user is None:
            user = User(email=email.lower(), password_hash=hash_password(password),
                        display_name="Demo", role=DEFAULT_ROLE)
            db.add(user)
            db.commit()
            logger.info("created demo account %s", email)
        else:
            user.password_hash = hash_password(password)
            user.role = DEFAULT_ROLE
            db.commit()
            logger.info("reset password for existing account %s", email)
        return user.id


def seed(email: str, password: str) -> None:
    user_id = _get_or_create_user(email, password)

    from src.storage.storage_manager import StorageManager

    store = StorageManager()

    base = _now()
    for i, ev in enumerate(EVENTS):
        event_id = f"{DEMO_MARKER}-{i:02d}"
        try:
            store.store_event(
                event_id=event_id,
                summary=ev["summary"],
                domain=ev["domain"],
                severity=ev["severity"],
                impact_type=ev["impact_type"],
                confidence_score=ev["confidence"],
                timestamp=(base - timedelta(minutes=7 * i)).isoformat(),
                metadata={"region": "sri_lanka", "llm_filtered": True,
                          "fake_news_score": 0.05, "source": DEMO_MARKER},
                entities=ev.get("entities"),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("event %s not stored: %s", event_id, exc)
    logger.info("stored %d events", len(EVENTS))

    # Dashboard snapshot lives in Redis as one JSON document, so it can be set
    # from here; the API reads it within about a second.
    try:
        from src.runtime import shared_state

        shared_state.update({"risk_dashboard_snapshot": DASHBOARD,
                             "run_count": 1, "first_run_complete": True,
                             "status": "idle"})
        logger.info("dashboard snapshot written")
    except Exception as exc:  # noqa: BLE001
        logger.warning("dashboard snapshot not written: %s", exc)

    # Collected posts ARE per user, so these attach to the demo account.
    try:
        from auth.db import session_scope
        from auth.models import User
        from src.social.routes import _store

        with session_scope() as db:
            user = db.get(User, user_id)
            payload = [{"platform": p, "text": t, "poster": "Roger demo",
                        "url": f"https://example.invalid/{DEMO_MARKER}/{i}",
                        "posted_at": (base - timedelta(hours=i)).isoformat(),
                        "likes": 12 + i, "comments": 2 + i, "shares": i}
                       for i, (p, t) in enumerate(POSTS)]
            stored = _store(db, user, payload)
            logger.info("stored %s collected posts for %s", stored, email)
    except Exception as exc:  # noqa: BLE001
        logger.warning("collected posts not stored: %s", exc)


def remove() -> None:
    """Delete exactly what seed() created."""
    from src.storage.storage_manager import StorageManager

    store = StorageManager()
    removed = 0
    for i in range(len(EVENTS)):
        event_id = f"{DEMO_MARKER}-{i:02d}"
        for attr in ("delete_event", "remove_event"):
            fn = getattr(store, attr, None)
            if fn:
                try:
                    fn(event_id)
                    removed += 1
                except Exception:  # noqa: BLE001
                    pass
                break
    logger.info("removed %d events (where the store supports deletion)", removed)

    try:
        from auth.db import session_scope
        from auth.models import IngestedPost

        with session_scope() as db:
            n = (db.query(IngestedPost)
                 .filter(IngestedPost.url.like(f"%{DEMO_MARKER}%")).delete(
                     synchronize_session=False))
            db.commit()
            logger.info("removed %d collected posts", n)
    except Exception as exc:  # noqa: BLE001
        logger.warning("collected posts not removed: %s", exc)

    try:
        from src.runtime import shared_state

        snap = shared_state.get("risk_dashboard_snapshot", {}) or {}
        if snap.get("source") == DEMO_MARKER:
            shared_state.update({"risk_dashboard_snapshot": {}})
            logger.info("cleared the demo dashboard snapshot")
        else:
            logger.info("dashboard snapshot is not the demo one; left alone")
    except Exception as exc:  # noqa: BLE001
        logger.warning("dashboard snapshot not cleared: %s", exc)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--email", default="demo@roger.lk")
    ap.add_argument("--password", default="")
    ap.add_argument("--remove", action="store_true")
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT.parent / ".env")
    except Exception:  # noqa: BLE001
        pass

    if args.remove:
        remove()
        return 0

    if not args.password:
        logger.error("--password is required when seeding")
        return 2
    seed(args.email, args.password)
    print()
    print("  Demo account:", args.email)
    print("  Sign in at  : https://roger.nivakaran.dev/login")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
