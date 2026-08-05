"""
src/intelligence/stories.py
Events that belong together.

The dedup pipeline throws away the most useful signal it computes. When a new
event semantically matches a prior one, is_duplicate() returns the matched
event's id and a similarity score -- and the aggregator passes that to
link_similar_events(), which writes to Neo4j, which render.yaml disables. Then
it drops the event. So a flood developing over three days is either forty
disconnected events or thirty-nine silently discarded ones, and there is no
object anywhere representing "the Kelani flood".

Dataminr's ReGenAI distils an event into a brief and regenerates it as the
event unfolds. That is the shape worth having, and the signal for it is already
being computed on every cycle.

A Story is the thread; StoryEvent is a link. The brief is regenerated in
batches, never per story, and a story whose brief could not be regenerated
keeps the old text and says so rather than showing a stale brief as current.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("stories")

# Ordered. Used to decide whether a story escalated.
SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}

# Derived, never invented. Times are since the story last gained an event.
QUIET_AFTER = timedelta(hours=6)
RESOLVED_AFTER = timedelta(hours=24)

# A brief is only worth regenerating when the story has actually moved. Both
# conditions are cheap to check and keep the LLM cost to one call per cycle.
REGENERATE_AFTER_EVENTS = 2


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def severity_rank(severity: Optional[str]) -> int:
    return SEVERITY_RANK.get(str(severity or "").lower(), 0)


def derive_state(
    *,
    last_seen: Optional[datetime],
    escalated: bool,
    now: Optional[datetime] = None,
) -> str:
    """
    What is happening to this story.

    Derived from the timeline, not stored as a judgement -- so it cannot drift
    out of step with the events underneath it.

      escalating  severity rose since the story started
      developing  gained an event recently
      quiet       nothing for 6h
      resolved    nothing for 24h
    """
    now = now or utcnow()

    if last_seen is None:
        return "developing"

    # Rows written before a timezone-aware default would compare as naive.
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)

    age = now - last_seen

    if age >= RESOLVED_AFTER:
        return "resolved"
    if escalated:
        return "escalating"
    if age >= QUIET_AFTER:
        return "quiet"
    return "developing"


class StoryTracker:
    """
    Threads events into stories.

    Deliberately tolerant of having no database: without one it degrades to the
    previous behaviour (the event is simply dropped as a duplicate) rather than
    failing a cycle. What it must never do is claim to have threaded something
    it did not -- attach() returns None on failure and the caller logs it.
    """

    def __init__(self, session_factory=None):
        self._session_factory = session_factory
        self._unavailable = False

    def _sessions(self):
        if self._unavailable:
            return None
        if self._session_factory is None:
            try:
                from auth.db import session_factory

                self._session_factory = session_factory()
            except Exception as exc:
                logger.warning(
                    "[stories] no database available (%s); duplicates will be "
                    "dropped as before instead of threaded",
                    exc,
                )
                self._unavailable = True
                return None
        return self._session_factory

    def attach(
        self,
        *,
        event_id: str,
        matched_event_id: str,
        summary: str,
        severity: str,
        domain: str,
        similarity: float = 0.0,
    ) -> Optional[str]:
        """
        Add this event to the story its match belongs to, creating one if the
        match is not yet threaded. Returns the story id, or None on failure.
        """
        factory = self._sessions()
        if factory is None:
            return None

        from .models import Story, StoryEvent

        try:
            with factory() as session:
                link = (
                    session.query(StoryEvent)
                    .filter_by(event_id=matched_event_id)
                    .one_or_none()
                )

                if link is None:
                    # The matched event is the start of a thread nobody has
                    # threaded yet. Seed the story from it, then add this one.
                    story = Story(
                        title=summary[:200],
                        brief=summary,
                        domain=domain,
                        peak_severity=severity,
                        first_seen=utcnow(),
                        last_seen=utcnow(),
                    )
                    session.add(story)
                    session.flush()
                    session.add(
                        StoryEvent(story_id=story.id, event_id=matched_event_id)
                    )
                else:
                    story = session.get(Story, link.story_id)
                    if story is None:
                        return None

                already = (
                    session.query(StoryEvent)
                    .filter_by(story_id=story.id, event_id=event_id)
                    .one_or_none()
                )
                if already is None:
                    session.add(
                        StoryEvent(
                            story_id=story.id,
                            event_id=event_id,
                            similarity=float(similarity or 0.0),
                        )
                    )
                    story.event_count = (story.event_count or 1) + 1
                    story.pending_events = (story.pending_events or 0) + 1

                story.last_seen = utcnow()
                if severity_rank(severity) > severity_rank(story.peak_severity):
                    story.peak_severity = severity
                    story.escalated = True

                session.commit()
                return story.id

        except Exception as exc:
            logger.error("[stories] could not attach %s: %s", event_id, exc)
            return None

    def stories_needing_a_brief(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Stories that have moved enough to be worth an LLM call.

        Gated so brief regeneration stays at one batched call per cycle rather
        than growing with the number of live stories.
        """
        factory = self._sessions()
        if factory is None:
            return []

        from .models import Story

        try:
            with factory() as session:
                rows = (
                    session.query(Story)
                    .filter(Story.pending_events >= REGENERATE_AFTER_EVENTS)
                    .order_by(Story.last_seen.desc())
                    .limit(limit)
                    .all()
                )
                return [
                    {
                        "id": s.id,
                        "title": s.title,
                        "brief": s.brief,
                        "domain": s.domain,
                        "event_count": s.event_count,
                        "peak_severity": s.peak_severity,
                    }
                    for s in rows
                ]
        except Exception as exc:
            logger.error("[stories] could not list stories: %s", exc)
            return []

    def save_brief(self, story_id: str, brief: Optional[str]) -> bool:
        """
        Store a regenerated brief.

        A None brief means the model did not produce one. The old text is kept
        -- a story with no brief is worse than a slightly old one -- and marked
        stale so the UI can say which it is showing.
        """
        factory = self._sessions()
        if factory is None:
            return False

        from .models import Story

        try:
            with factory() as session:
                story = session.get(Story, story_id)
                if story is None:
                    return False

                if brief:
                    story.brief = brief[:4000]
                    story.brief_stale = False
                    story.pending_events = 0
                else:
                    story.brief_stale = True

                session.commit()
                return bool(brief)
        except Exception as exc:
            logger.error("[stories] could not save brief for %s: %s", story_id, exc)
            return False

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Live stories, newest activity first, with derived state."""
        factory = self._sessions()
        if factory is None:
            return []

        from .models import Story, StoryEvent

        try:
            with factory() as session:
                rows = (
                    session.query(Story)
                    .order_by(Story.last_seen.desc())
                    .limit(limit)
                    .all()
                )
                out = []
                for story in rows:
                    event_ids = [
                        link.event_id
                        for link in session.query(StoryEvent)
                        .filter_by(story_id=story.id)
                        .order_by(StoryEvent.added_at.asc())
                        .all()
                    ]
                    out.append({
                        "id": story.id,
                        "title": story.title,
                        "brief": story.brief,
                        "brief_stale": bool(story.brief_stale),
                        "domain": story.domain,
                        "peak_severity": story.peak_severity,
                        "event_count": story.event_count,
                        "event_ids": event_ids,
                        "first_seen": story.first_seen.isoformat() if story.first_seen else None,
                        "last_seen": story.last_seen.isoformat() if story.last_seen else None,
                        "state": derive_state(
                            last_seen=story.last_seen,
                            escalated=bool(story.escalated),
                        ),
                    })
                return out
        except Exception as exc:
            logger.error("[stories] could not list recent stories: %s", exc)
            return []


_tracker: Optional[StoryTracker] = None


def get_story_tracker() -> StoryTracker:
    global _tracker
    if _tracker is None:
        _tracker = StoryTracker()
    return _tracker


def set_story_tracker(tracker) -> None:
    """Tests."""
    global _tracker
    _tracker = tracker
