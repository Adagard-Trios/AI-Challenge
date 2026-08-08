"""
src/blackboard/sensors.py
Cheap signals that say WHERE to look next.

THE POINT OF THIS STAGE
-----------------------
A focus is the board saying "something is happening here". Nothing consumes
them yet -- deliberately. This is the stage that answers, with evidence,
whether opportunistic control is worth building at all:

  - foci are written from real signals every cycle
  - the log records what a controller WOULD have prioritised
  - that can be compared against what the fixed schedule actually collected

If the foci turn out to be uninformative, the answer is to stop here and keep
stages 0-2, which stand on their own. Building the scheduler first and finding
that out afterwards is the expensive order.

WHY THESE THREE SENSORS
-----------------------
They are the cheap, structured, no-LLM signals this system already computes and
then uses only for display:

  rivernet    a station at warning/alert/critical is the single highest-signal
              input available, costs one HTTP call, and already carries a
              region. It is also the head of the one genuine cross-domain chain
              latent in the code: flood -> district -> emergency gazette.
  trending    a topic at >3x normal volume is literally the data saying "look
              here", and today it only renders a badge.
  stories     a thread whose severity has RISEN is a developing situation by
              definition, and StoryTracker already computes that.

Everything here is best-effort. A sensor that cannot read its source writes no
focus and says so; it never guesses.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Roger.blackboard.sensors")

# How long a focus lives before it must be re-justified by a fresh signal. A
# focus is an instruction to spend collection budget somewhere; a stale one is
# worse than none, because it spends it where nothing is happening.
FOCUS_TTL_HOURS = 6

# Urgency by how bad the reading is. Deliberately not linear in the river
# level: the operational difference between "warning" and "critical" is not
# proportional to centimetres.
RIVER_URGENCY = {
    "critical": 0.95,
    "alert": 0.8,
    "warning": 0.6,
    "no_data": 0.4,   # a station that stopped reporting DURING a flood is signal
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def upsert_focus(
    *,
    kind: str,
    value: str,
    urgency: float,
    reason: str,
    source_ks: str,
) -> Optional[str]:
    """
    Create a focus, or reinforce the one that already exists.

    focus_key is unique and reinforced on conflict. That is what stops this
    table growing: three flood alerts in Ratnapura are ONE focus with rising
    urgency, not three rows competing for the same attention.

    Urgency takes the MAXIMUM rather than the latest. A critical reading
    followed by a warning reading is still a critical situation, and letting
    the newer, milder signal overwrite it would quietly de-prioritise the thing
    that mattered.
    """
    if not value:
        return None

    try:
        from auth.db import session_scope

        from .models import BoardFocus
    except Exception:  # noqa: BLE001
        return None

    focus_key = f"{kind}:{str(value).strip().lower()}"

    try:
        with session_scope() as session:
            existing = (
                session.query(BoardFocus)
                .filter(BoardFocus.focus_key == focus_key)
                .one_or_none()
            )
            now = utcnow()
            if existing is not None:
                existing.urgency = max(float(existing.urgency or 0), float(urgency))
                existing.last_reinforced = now
                existing.expires_at = now + timedelta(hours=FOCUS_TTL_HOURS)
                existing.reason = reason
                return existing.id

            focus = BoardFocus(
                id=uuid.uuid4().hex,
                focus_key=focus_key,
                kind=kind,
                value=str(value)[:120],
                urgency=float(urgency),
                reason=reason,
                source_ks=source_ks,
                created_at=now,
                last_reinforced=now,
                expires_at=now + timedelta(hours=FOCUS_TTL_HOURS),
            )
            session.add(focus)
            return focus.id
    except Exception as exc:  # noqa: BLE001
        logger.warning("[sensors] could not write focus %s: %s", focus_key, exc)
        return None


def from_rivernet(river_status: Dict[str, Any]) -> List[str]:
    """
    Flooding rivers become district foci.

    The head of the one real cross-domain chain already latent in this
    codebase: a rising Kelani should send the meteorological agent to Ratnapura
    and Kegalle rather than the five hardcoded districts it visits regardless,
    and an emergency gazette usually follows a flood.
    """
    written = []
    for alert in (river_status or {}).get("alerts", []) or []:
        if not isinstance(alert, dict):
            continue
        region = alert.get("region") or alert.get("river")
        severity = (alert.get("severity") or "").lower()
        urgency = RIVER_URGENCY.get(severity)
        if not region or urgency is None:
            continue

        focus_id = upsert_focus(
            kind="district",
            value=region,
            urgency=urgency,
            # Human-readable and specific. A focus that cannot say why it
            # exists cannot be argued with, and "why did it look there" is the
            # first question anyone asks of a scheduling decision.
            reason=f"rivernet: {alert.get('message') or severity}",
            source_ks="sensor.rivernet",
        )
        if focus_id:
            written.append(focus_id)
    return written


def from_trending(spikes: List[Dict[str, Any]]) -> List[str]:
    """
    A topic at several times its normal volume is the data asking for
    attention. Today it renders a badge and nothing else.
    """
    written = []
    for spike in (spikes or [])[:5]:
        if not isinstance(spike, dict):
            continue
        topic = spike.get("topic")
        if not topic:
            continue
        momentum = float(spike.get("momentum") or 0)
        # Saturating: 20x and 50x are both "a lot", and letting momentum run
        # away would let one noisy topic outrank a flood.
        urgency = min(0.85, 0.4 + momentum / 40.0)

        focus_id = upsert_focus(
            kind="topic",
            value=str(topic),
            urgency=urgency,
            reason=f"trending: {momentum:.0f}x normal volume",
            source_ks="sensor.trending",
        )
        if focus_id:
            written.append(focus_id)
    return written


def from_stories(stories: List[Dict[str, Any]]) -> List[str]:
    """
    An escalating story is a developing situation by definition, and
    StoryTracker already derives that from the timeline rather than storing a
    judgement.
    """
    written = []
    for story in (stories or [])[:10]:
        if not isinstance(story, dict):
            continue
        state = (story.get("state") or "").lower()
        if state not in ("escalating", "developing"):
            continue
        story_id = story.get("id")
        if not story_id:
            continue

        focus_id = upsert_focus(
            kind="story",
            value=str(story_id),
            urgency=0.75 if state == "escalating" else 0.55,
            reason=f"story {state}: {(story.get('title') or '')[:80]}",
            source_ks="sensor.stories",
        )
        if focus_id:
            written.append(focus_id)
    return written


def current_foci(limit: int = 10) -> List[Dict[str, Any]]:
    """The board's current attention, most urgent first."""
    try:
        from auth.db import session_scope

        from .models import BoardFocus

        with session_scope() as session:
            rows = (
                session.query(BoardFocus)
                .order_by(BoardFocus.urgency.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "kind": r.kind,
                    "value": r.value,
                    "urgency": round(float(r.urgency or 0), 3),
                    "reason": r.reason,
                    "source_ks": r.source_ks,
                }
                for r in rows
            ]
    except Exception as exc:  # noqa: BLE001
        logger.debug("[sensors] could not read foci: %s", exc)
        return []


def report_what_control_would_do() -> None:
    """
    Log the decision a controller WOULD make, without making it.

    This is the whole value of the stage. It costs one query per cycle and it
    is the difference between building a scheduler on evidence and building one
    on the assumption that opportunistic control helps.
    """
    foci = current_foci(limit=5)
    if not foci:
        return
    summary = ", ".join(
        f"{f['kind']}={f['value']}({f['urgency']:.2f})" for f in foci
    )
    logger.info("[Blackboard] board attention would prioritise: %s", summary)
