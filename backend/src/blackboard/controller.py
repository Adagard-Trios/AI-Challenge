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


def _controller_lock():
    """
    A cluster-wide lock around one planning tick, or None when unavailable.

    Distinct from the per-source claim. The claim stops two replicas RUNNING
    the same source; this stops two replicas PLANNING at once and both writing
    a full agenda to the ledger — which would not double-collect, but would
    double the ledger and skew the shadow comparison the ledger exists for.

    pg_advisory_lock is used because it is held by the SESSION and released the
    moment that session closes, including when the process dies. A lock table
    would need its own expiry and its own cleanup, and a crashed holder would
    block every replica until someone noticed.

    Postgres only. SQLite is single-writer anyway, so on a laptop there is
    nothing to coordinate.
    """
    try:
        from sqlalchemy import text

        from auth.db import engine, session_scope

        if engine().dialect.name != "postgresql":
            return None

        class _Lock:
            def __enter__(self):
                self._scope = session_scope()
                self._session = self._scope.__enter__()
                # try_advisory_lock, not advisory_lock: blocking would queue
                # ticks behind each other and turn a 60-second loop into a
                # backlog. A replica that cannot get it simply skips this tick.
                got = self._session.execute(
                    text("SELECT pg_try_advisory_lock(:k)"),
                    {"k": 0x1207B0A2},   # arbitrary, constant, this app's
                ).scalar()
                self.acquired = bool(got)
                return self

            def __exit__(self, *exc):
                try:
                    self._session.execute(
                        text("SELECT pg_advisory_unlock(:k)"),
                        {"k": 0x1207B0A2},
                    )
                finally:
                    self._scope.__exit__(*exc)
                return False

        return _Lock()
    except Exception as exc:  # noqa: BLE001
        logger.debug("[controller] advisory lock unavailable: %s", exc)
        return None


def tick() -> Dict[str, Any]:
    """
    One planning pass. In shadow mode it records the agenda and runs nothing.

    Returns a summary so a caller can log it -- a scheduler whose decisions are
    invisible cannot be checked, and checking it is the whole purpose of this
    stage.
    """
    result = {"mode": mode(), "planned": 0, "deferred": 0, "executed": 0}

    lock = _controller_lock()
    if lock is not None:
        with lock as held:
            if not held.acquired:
                # Another replica is planning this tick. Skipping is correct:
                # the agenda it produces is the same one this replica would
                # have produced, from the same board.
                result["skipped"] = "another replica holds the controller lock"
                return result
            return _tick_locked(result)

    return _tick_locked(result)


def _tick_locked(result: Dict[str, Any]) -> Dict[str, Any]:
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

    from .knowledge_sources import REGISTRY

    records = []
    for activation in agenda:
        skipped = None
        if activation.est_tokens:
            if activation.est_tokens > max(0, budget - reserve):
                skipped = "budget"
            else:
                budget -= activation.est_tokens

        # Claim only when this would actually run. Claiming in shadow mode
        # would hold slots against a controller that executes nothing, and
        # starve the real one if both were ever enabled at once.
        if skipped is None and mode() == "active":
            source = REGISTRY.get(activation.ks_name)
            interval = (source.min_interval.total_seconds() if source else 60.0)
            if not claim(activation.ks_name, interval_seconds=interval):
                skipped = "claimed_elsewhere"

        executed = False
        duration_ms = None
        if skipped is None and mode() == "active":
            source = REGISTRY.get(activation.ks_name)
            if source is not None and source.executable:
                executed, duration_ms = _execute(source, activation)
                if executed:
                    result["executed"] += 1
                    if activation.est_tokens:
                        charge_tokens(activation.est_tokens)
                else:
                    skipped = "failed"
            else:
                # Recorded, not pretended. A source with no run() is still
                # worth having on the agenda in shadow, but reporting it as
                # executed would make the ledger lie -- and the ledger is the
                # only evidence the scheduler's judgement can be checked
                # against.
                skipped = "not_executable"

        if skipped:
            result["deferred"] += 1
        records.append((activation, skipped, executed, duration_ms))

    _record(tick_id, records)

    if agenda:
        top = ", ".join(
            f"{r[0].ks_name}({r[0].priority:.2f})" for r in records[:5]
        )
        logger.info(
            "[controller] %s: would run %d, defer %d -- %s",
            result["mode"], result["planned"] - result["deferred"],
            result["deferred"], top,
        )
    return result


def replica_id() -> str:
    """
    Who this process is, for the claim record.

    HOSTNAME is what Kubernetes sets to the pod name, so in a cluster this is
    already meaningful and needs no configuration.
    """
    return (os.getenv("REPLICA_ID") or os.getenv("HOSTNAME")
            or f"pid-{os.getpid()}")[:64]


def claim(ks_name: str, *, interval_seconds: float) -> bool:
    """
    Take the right to run this source, or return False because someone else
    has it.

    Needed because the controller runs in every replica that collects. Without
    a claim, three replicas each decide `met.district_social` is due and all
    three scrape it -- which is the same class of mistake as the unshared
    pacing gate, and against social sources it is the same consequence.

    Redis when available: SET NX PX is atomic in one round trip, so the
    check-then-set race cannot happen. Note this could NOT be done by comparing
    stored timestamps -- the deciding process and the claiming process may be
    different, and their clocks are not comparable.

    FAILS OPEN, unlike the social pacing gate, and the difference is
    deliberate. If the claim is unavailable the cost is a duplicated scrape;
    if the PACING gate were unavailable the cost is a banned account. Refusing
    to collect at all because a coordination hint is down would trade a real
    outage for a hypothetical duplicate.
    """
    try:
        from src.runtime.redis_client import configured, get_client

        if not configured():
            return True     # single process; nothing to coordinate with
        client = get_client()
        if client is None:
            logger.debug("[controller] no claim store; proceeding unclaimed")
            return True

        key = f"roger:ks:{ks_name}"
        acquired = client.set(key, replica_id(), nx=True,
                              px=int(max(1.0, interval_seconds) * 1000))
        return bool(acquired)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[controller] claim failed for %s: %s", ks_name, exc)
        return True


def _execute(source, activation) -> tuple:
    """
    Run one knowledge source. Returns (succeeded, duration_ms).

    A failure here is contained to the source: the rest of the agenda still
    runs. One broken collector must not silence a cycle, which is the failure
    the fan-out already guards against by catching per agent.
    """
    started = time.monotonic()
    try:
        source.run(dict(activation.params or {}))
        duration = int((time.monotonic() - started) * 1000)
        logger.info("[controller] ran %s in %dms (%s)",
                    source.name, duration, activation.reason)
        return True, duration
    except Exception as exc:  # noqa: BLE001
        duration = int((time.monotonic() - started) * 1000)
        logger.warning("[controller] %s failed after %dms: %s",
                       source.name, duration, exc)
        return False, duration


def _record(tick_id: str, records) -> None:
    """
    Write the agenda to the ledger.

    In shadow every row is executed=False, which is what makes this a record of
    INTENT rather than of action -- and what lets the comparison be made
    honestly later. In active mode it records what actually ran, so the same
    table answers both "what would it have done" and "what did it do".
    """
    try:
        from auth.db import session_scope

        from .models import KSActivation

        with session_scope() as session:
            for activation, skipped, executed, duration_ms in records:
                session.add(KSActivation(
                    id=uuid.uuid4().hex,
                    ks_name=activation.ks_name,
                    tick_id=tick_id,
                    decided_at=utcnow(),
                    executed=bool(executed),
                    skipped_reason=skipped or ("shadow" if mode() == "shadow"
                                               else None),
                    priority=activation.priority,
                    trigger_reason=activation.reason,
                    est_tokens=activation.est_tokens or 0,
                    duration_ms=duration_ms,
                    claimed_by=replica_id() if executed else None,
                    claimed_at=utcnow() if executed else None,
                ))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[controller] could not record the agenda: %s", exc)
