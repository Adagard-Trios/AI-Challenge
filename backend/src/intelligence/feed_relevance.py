"""
src/intelligence/feed_relevance.py
Attach relevance to a feed, for one caller.

Sits between the pure scorer (relevance.py, no I/O) and the API. Its whole job
is to fetch the two things the scorer needs -- the caller's exposure profile and
the entities behind each event -- and to fail in a way that leaves the feed
usable.

The failure rule matters more than the happy path. If the profile cannot be
read, or the entity store is down, or the caller is anonymous, every event gets
``relevance: None`` and the feed is returned in its existing order. It must
never return a feed scored entirely zero, because that is indistinguishable
from "nothing today concerns you" and would quietly hide the whole product.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .relevance import Exposure, is_relevant, score_event

logger = logging.getLogger("feed_relevance")


def load_exposure(db, user) -> Optional[Exposure]:
    """
    The caller's exposure, or None when there is nothing to score against.

    None covers every "do not rank" case -- anonymous caller, no profile, empty
    profile, database error -- because they all mean the same thing to the
    caller and none of them should change what the user sees beyond leaving the
    order alone.
    """
    if user is None or db is None:
        return None

    try:
        from .exposure_routes import get_profile

        profile = get_profile(db, user.id)
        if profile is None:
            return None

        exposure = Exposure.from_profile(profile)
        return None if exposure.is_empty() else exposure
    except Exception as exc:
        logger.warning("[feed_relevance] could not load exposure: %s", exc)
        return None


def _entities_for(events: List[Dict[str, Any]]) -> Dict[str, List[dict]]:
    """
    Entities per event.

    Prefers what the event already carries -- the in-memory feed keeps them
    from the cycle that produced it -- and only queries the store for events
    that do not, which is the database-backed path.
    """
    inline = {}
    missing = []

    for event in events:
        event_id = event.get("event_id")
        if event.get("entities"):
            inline[event_id] = event["entities"]
        elif event_id:
            missing.append(event_id)

    if not missing:
        return inline

    try:
        from .entity_store import get_entity_store

        inline.update(get_entity_store().entities_for(missing))
    except Exception as exc:
        logger.warning("[feed_relevance] entity lookup failed: %s", exc)

    return inline


def annotate(
    events: List[Dict[str, Any]],
    exposure: Optional[Exposure],
    *,
    only_relevant: bool = False,
) -> List[Dict[str, Any]]:
    """
    Add ``relevance`` to each event and sort by it.

    With no exposure the list is returned untouched, in its original order,
    with ``relevance: None`` on every event -- an explicit "not scored", not a
    score of zero.

    ``only_relevant`` is the user's own filter toggle. It is off by default and
    never applied when there is nothing to score against, so the platform can
    never decide on its own to hide something.
    """
    if not events:
        return events

    # Copy every event before touching it.
    #
    # /api/feed serves current_state["final_ranked_feed"] -- global, shared
    # across requests, and broadcast over the websocket. Writing `relevance`
    # onto those dicts in place would stamp one user's exposure matches onto
    # the state every other user reads, which is a cross-tenant leak of exactly
    # the kind the RAG instance cache already had. Sorting in place would also
    # reorder the global feed to suit whoever asked last.
    events = [dict(event) for event in events]

    # Hydrate entities before anything else, and for everyone.
    #
    # Two reasons this is not inside the exposure branch. First, the entity
    # chips are "what is this event about", which is worth showing whether or
    # not a profile exists. Second, /api/feeds rebuilds events from the database
    # through a field whitelist that cannot carry entities -- they live in the
    # entity store, not in the SQLite row -- so without this the same event
    # showed chips when it arrived over the websocket and none after a page
    # reload. That is the same inconsistency the whitelist comment in main.py
    # already describes for region and fake_news_score, one field later.
    entities_by_event = _entities_for(events)

    for event in events:
        if not event.get("entities"):
            hydrated = entities_by_event.get(event.get("event_id"))
            if hydrated:
                event["entities"] = hydrated
                # The model did run -- these came from it, via the store.
                event.setdefault("entities_extracted", True)

    if exposure is None:
        for event in events:
            event["relevance"] = None
        return events

    for event in events:
        scored = score_event(
            entities_by_event.get(event.get("event_id"), []),
            exposure,
            summary=str(event.get("summary", "")),
        )
        event["relevance"] = scored.as_dict() if scored else None

    if only_relevant:
        kept = [
            e for e in events
            if is_relevant(_as_relevance(e.get("relevance")))
        ]
        # Never hand back an empty feed because of a filter the user can see
        # but may not remember enabling. Better to show everything and let the
        # badge explain than to show a blank page that reads as "no news".
        events = kept if kept else events

    # Highest relevance first, stable within a tier so the existing
    # confidence ordering is preserved for events that score the same.
    events.sort(
        key=lambda e: (e.get("relevance") or {}).get("score", 0.0),
        reverse=True,
    )
    return events


def _as_relevance(payload):
    """Rehydrate just enough for is_relevant()."""
    if payload is None:
        return None

    from .relevance import Relevance

    return Relevance(
        score=float(payload.get("score", 0.0)),
        matched_on=tuple(payload.get("matched_on") or ()),
    )
