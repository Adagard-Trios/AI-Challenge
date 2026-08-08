"""
src/blackboard/controller.py
The agenda, recorded but not acted on.

WHAT SHADOW MODE IS FOR
-----------------------
The controller computes what it WOULD run each cycle and writes that to
ks_activations with executed=False. The existing fan-out keeps running,
unchanged, and collects exactly what it always did.

That gives the one thing needed before handing collection to a scheduler: a
record of what it would have skipped, checkable against what those runs
actually produced. If a source the controller wanted to skip consistently
yielded high-salience entries, the TRIGGER IS WRONG -- and it is much better to
learn that from a table than from a feed that quietly went thin.

The risk being managed is specific. Opportunistic control produces LESS data,
not obviously smarter data, and "the feed looks dead" is a failure this project
has hit repeatedly and taken a while to notice each time. Every collector
therefore has a max_interval floor, so the worst case degrades to a slower
fixed schedule rather than to silence.

TOKENS
------
The budget window is deliberately shared through Redis rather than counted per
process. With three replicas and a per-process counter you attempt 24,000
tokens a minute against an 8,000 ceiling and everyone gets 413 -- which is a
worse failure than the one it was meant to prevent.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("Roger.blackboard.controller")

# Groq free tier. Shared with everything else the process does, so the
# controller never plans to spend all of it.
TOKENS_PER_MINUTE = int(os.getenv("LLM_TOKENS_PER_MINUTE", "8000"))

# Fraction held back for classification, whose output the user actually sees.
# Without it a chatty summariser can starve the feed of the one LLM call that
# turns raw posts into intelligence.
CLASSIFY_RESERVE = 0.25


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def mode() -> str:
    """
    shadow | active. Shadow by default, and an env var rather than a code
    change so it can be turned off without a redeploy -- a switch that needs a
    deploy is not one you can use when something is wrong.
    """
    value = (os.getenv("BLACKBOARD_CONTROL") or "shadow").strip().lower()
    return value if value in ("shadow", "active") else "shadow"


def tokens_remaining() -> int:
    """
    How much of this minute's allowance is left.

    Shared through Redis when configured. Falls back to the full budget when
    not, which is correct for one process and is what a laptop runs.
    """
    try:
        from src.runtime.redis_client import configured, get_client

        if not configured():
            return TOKENS_PER_MINUTE
        client = get_client()
        if client is None:
            # Cannot see the shared counter. Assume spent rather than free:
            # planning against a budget we cannot verify is how the 413s
            # happened in the first place.
            return 0
        used = client.get(_window_key())
        return max(0, TOKENS_PER_MINUTE - int(used or 0))
    except Exception:  # noqa: BLE001
        return 0


def _window_key() -> str:
    # One key per wall-clock minute, expiring on its own. Simpler than a
    # sliding window and close enough for a per-minute cap.
    return f"roger:llm:{int(time.time() // 60)}"


def charge_tokens(count: int) -> None:
    """Record spend against the shared window. Best-effort."""
    if count <= 0:
        return
    try:
        from src.runtime.redis_client import configured, get_client

        if not configured():
            return
        client = get_client()
        if client is None:
            return
        key = _window_key()
        if int(client.incrby(key, int(count))) == int(count):
            client.expire(key, 120)
    except Exception:  # noqa: BLE001
        pass


def build_digest() -> Optional[Any]:
    """
    One board read per tick, shared by every trigger.

    Twenty-five sources each querying to decide whether to run would cost more
    than running them, which is why trigger() takes a digest and does no I/O.
    """
    try:
        from .knowledge_sources import BoardDigest
        from .sensors import current_foci
        from .store import BoardStore
    except Exception:  # noqa: BLE001
        return None

    store = BoardStore()
    if not store.available():
        return None

    severity_rank = {"critical": 1.0, "high": 0.75, "medium": 0.45, "low": 0.2}
    by_domain: Dict[str, float] = {}
    for entry in store.top_entries(limit=100):
        domain = entry.get("domain")
        if not domain:
            continue
        rank = severity_rank.get((entry.get("severity") or "").lower(), 0.2)
        # Strongest thing on the board per domain, weighted by how salient it
        # still is -- an old critical event should not keep a domain hot.
        by_domain[domain] = max(by_domain.get(domain, 0.0),
                                rank * float(entry.get("salience") or 0))

    return BoardDigest(
        foci=current_foci(limit=20),
        severity_by_domain=by_domain,
        last_run=_last_run_ages(),
        tokens_remaining=tokens_remaining(),
    )


def _last_run_ages() -> Dict[str, float]:
    """
    Seconds since each source last ran, from the shared ledger rather than
    process memory -- otherwise every replica thinks everything is overdue and
    the starvation rule fires constantly.
    """
    try:
        from auth.db import session_scope

        from .models import KSActivation

        ages: Dict[str, float] = {}
        now = utcnow()
        with session_scope() as session:
            rows = (
                session.query(KSActivation)
                .filter(KSActivation.executed.is_(True))
                .order_by(KSActivation.decided_at.desc())
                .limit(400)
                .all()
            )
            for row in rows:
                if row.ks_name in ages:
                    continue
                decided = row.decided_at
                if decided.tzinfo is None:
                    decided = decided.replace(tzinfo=timezone.utc)
                ages[row.ks_name] = (now - decided).total_seconds()
        return ages
    except Exception:  # noqa: BLE001
        return {}


def tick() -> Dict[str, Any]:
    """
    One planning pass. In shadow mode it records the agenda and runs nothing.

    Returns a summary so a caller can log it -- a scheduler whose decisions are
    invisible cannot be checked, and checking it is the whole purpose of this
    stage.
    """
    result = {"mode": mode(), "planned": 0, "deferred": 0, "executed": 0}

    digest = build_digest()
    if digest is None:
        return result

    try:
        from .knowledge_sources import build_agenda
    except Exception:  # noqa: BLE001
        return result

    agenda = build_agenda(digest)
    result["planned"] = len(agenda)

    tick_id = uuid.uuid4().hex[:16]
    budget = digest.tokens_remaining
    reserve = int(TOKENS_PER_MINUTE * CLASSIFY_RESERVE)

    records = []
    for activation in agenda:
        skipped = None
        if activation.est_tokens:
            if activation.est_tokens > max(0, budget - reserve):
                skipped = "budget"
            else:
                budget -= activation.est_tokens

        if skipped:
            result["deferred"] += 1
        records.append((activation, skipped))

    _record(tick_id, records)

    if agenda:
        top = ", ".join(
            f"{a.ks_name}({a.priority:.2f})" for a, _ in records[:5]
        )
        logger.info(
            "[controller] %s: would run %d, defer %d -- %s",
            result["mode"], result["planned"] - result["deferred"],
            result["deferred"], top,
        )
    return result


def _record(tick_id: str, records) -> None:
    """
    Write the agenda to the ledger.

    executed=False throughout in shadow mode, which is what makes this a record
    of intent rather than of action -- and what lets the comparison be made
    honestly later.
    """
    try:
        from auth.db import session_scope

        from .models import KSActivation

        with session_scope() as session:
            for activation, skipped in records:
                session.add(KSActivation(
                    id=uuid.uuid4().hex,
                    ks_name=activation.ks_name,
                    tick_id=tick_id,
                    decided_at=utcnow(),
                    executed=False,
                    skipped_reason=skipped or ("shadow" if mode() == "shadow"
                                               else None),
                    priority=activation.priority,
                    trigger_reason=activation.reason,
                    est_tokens=activation.est_tokens or 0,
                ))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[controller] could not record the agenda: %s", exc)
