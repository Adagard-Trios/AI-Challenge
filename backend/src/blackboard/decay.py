"""
src/blackboard/decay.py
"Keeps only the relevant things for the present."

Pure functions, no I/O, no database. That is deliberate: this is the part
easiest to get subtly wrong and cheapest to test exhaustively, and mixing it
with storage would make every test need a database.

WHY TIME ALONE IS THE WRONG ANSWER
----------------------------------
The obvious implementation is "delete anything older than N hours". It is
wrong here in both directions. An escalating flood story eight hours old is
more relevant than a tweet from five minutes ago, and a low-severity note that
nothing has repeated is not worth keeping for a day just because it is recent.

So relevance has three inputs:

  1. TIME, weighted by severity. A critical event stays relevant far longer
     than a low one, because acting on it takes longer.
  2. EVIDENCE. Every independent corroboration pushes salience back up. Today
     a semantic duplicate is DROPPED and the corroboration is computed, used
     once for a confidence bump, and forgotten -- so six outlets reporting one
     flood are worth exactly as much as one tweet.
  3. A HARD FLOOR. Reinforcement must not be able to keep something alive
     forever, or a busy topic never leaves the board and the board stops
     describing the present.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Optional

# Half-life per severity: how long until an unreinforced entry is worth half
# what it was. Scaled to how long the thing plausibly matters for -- a critical
# event is still worth knowing about tomorrow; a low one is background by
# lunchtime.
HALF_LIFE_HOURS = {
    "critical": 24.0,
    "high": 12.0,
    "medium": 6.0,
    "low": 2.0,
}
DEFAULT_HALF_LIFE_HOURS = 6.0

# A focus decays faster than the event that created it. It is an instruction to
# look somewhere, and a stale instruction is worse than none -- it spends
# collection budget on a place nothing is happening any more.
FOCUS_HALF_LIFE_HOURS = 3.0

# Below this an entry is evicted, unless a story is holding it.
EVICTION_THRESHOLD = 0.05

# Each independent corroboration is worth this much salience, added back at the
# moment of reinforcement. Deliberately sub-linear via a cap: the difference
# between one and three sources is large, between eight and ten it is not.
CORROBORATION_BOOST = 0.15
MAX_CORROBORATION_BOOST = 0.45

# Nothing lives longer than this regardless of reinforcement.
MAX_LIFETIME_HOURS = 72.0


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def half_life_for(severity: Optional[str]) -> float:
    return HALF_LIFE_HOURS.get((severity or "").lower(), DEFAULT_HALF_LIFE_HOURS)


def _hours_between(later: datetime, earlier: datetime) -> float:
    if earlier is None or later is None:
        return 0.0
    # Tolerate naive datetimes: SQLite hands them back without tzinfo even for
    # a timezone-aware column, and subtracting mixed awareness raises.
    if earlier.tzinfo is None:
        earlier = earlier.replace(tzinfo=timezone.utc)
    if later.tzinfo is None:
        later = later.replace(tzinfo=timezone.utc)
    return max(0.0, (later - earlier).total_seconds() / 3600.0)


def decayed_salience(
    base_salience: float,
    severity: Optional[str],
    last_reinforced: datetime,
    now: Optional[datetime] = None,
    corroborations: int = 0,
) -> float:
    """
    Current salience of an entry.

    Exponential rather than linear because relevance does not fall off a cliff:
    something is worth a bit less each hour, not everything until a deadline
    and nothing after it.

    `now` is a parameter rather than being read inside so this is
    deterministic and testable without freezing the clock.
    """
    now = now or utcnow()
    elapsed = _hours_between(now, last_reinforced)
    half_life = half_life_for(severity)

    decayed = float(base_salience) * math.pow(0.5, elapsed / half_life)

    boost = min(MAX_CORROBORATION_BOOST,
                max(0, int(corroborations or 0)) * CORROBORATION_BOOST)

    # Clamped to [0, 1]. A salience above 1 would let one heavily corroborated
    # entry outrank everything forever, and a negative one would sort below
    # entries that should already have been evicted.
    return max(0.0, min(1.0, decayed + boost))


def focus_urgency(
    base_urgency: float,
    last_reinforced: datetime,
    now: Optional[datetime] = None,
) -> float:
    now = now or utcnow()
    elapsed = _hours_between(now, last_reinforced)
    value = float(base_urgency) * math.pow(0.5, elapsed / FOCUS_HALF_LIFE_HOURS)
    return max(0.0, min(1.0, value))


def should_evict(
    salience: float,
    story_id: Optional[str],
    created_at: Optional[datetime] = None,
    now: Optional[datetime] = None,
) -> bool:
    """
    Whether an entry has stopped describing the present.

    An entry attached to a story is NEVER evicted on salience alone. The story
    is the long-term memory of a developing situation, and deleting its
    contributing events would leave a thread whose evidence has vanished --
    "44 events" with nothing behind it.
    """
    now = now or utcnow()

    if created_at is not None and _hours_between(now, created_at) > MAX_LIFETIME_HOURS:
        # The hard floor. Applies even to a story-held entry, or a permanently
        # busy topic would pin rows forever.
        return True

    if story_id:
        return False

    return float(salience) < EVICTION_THRESHOLD


def expiry_for(severity: Optional[str], now: Optional[datetime] = None) -> datetime:
    """
    When an entry expires regardless of what happens to it.

    Four half-lives, capped at MAX_LIFETIME_HOURS: by then an unreinforced
    entry is at ~6% of its original salience, which is already below the
    eviction threshold for anything that started at a normal value.
    """
    now = now or utcnow()
    hours = min(MAX_LIFETIME_HOURS, half_life_for(severity) * 4)
    return now + timedelta(hours=hours)
