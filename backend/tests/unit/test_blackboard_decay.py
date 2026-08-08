"""
Relevance decay: "keeps only the relevant things for the present".

Pure maths, so these are exhaustive and fast. They exist because the obvious
implementation -- delete anything older than N hours -- is wrong in BOTH
directions here: an escalating flood eight hours old matters more than a tweet
from five minutes ago, and a low-severity note nothing has repeated is not
worth a day of board space just for being recent.

The eviction rules are also the ones that decide what a user stops seeing, so
getting them wrong is not a performance bug, it is a wrong answer.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

NOW = datetime(2026, 8, 8, 12, 0, 0, tzinfo=timezone.utc)


def _ago(hours):
    return NOW - timedelta(hours=hours)


# --- the shape of decay -----------------------------------------------------

def test_a_fresh_entry_keeps_its_salience():
    from src.blackboard.decay import decayed_salience

    assert decayed_salience(0.8, "high", NOW, now=NOW) == pytest.approx(0.8)


def test_one_half_life_halves_it():
    from src.blackboard.decay import decayed_salience, HALF_LIFE_HOURS

    value = decayed_salience(0.8, "high", _ago(HALF_LIFE_HOURS["high"]), now=NOW)
    assert value == pytest.approx(0.4, abs=1e-6)


def test_severity_decides_how_long_something_stays_relevant():
    """
    A critical event is still worth knowing about tomorrow because acting on it
    takes longer. A low one is background by lunchtime.
    """
    from src.blackboard.decay import decayed_salience

    critical = decayed_salience(0.8, "critical", _ago(8), now=NOW)
    low = decayed_salience(0.8, "low", _ago(8), now=NOW)
    assert critical > low
    assert low < 0.1, "a low-severity entry is still prominent after 8 hours"


def test_an_unknown_severity_does_not_crash_or_live_forever():
    from src.blackboard.decay import decayed_salience, DEFAULT_HALF_LIFE_HOURS

    value = decayed_salience(0.8, None, _ago(DEFAULT_HALF_LIFE_HOURS), now=NOW)
    assert value == pytest.approx(0.4, abs=1e-6)


# --- evidence ---------------------------------------------------------------

def test_corroboration_makes_an_entry_harder_to_evict():
    """
    THE behavioural point. Today a semantic duplicate is DROPPED and the
    corroboration count is computed, used once for a confidence bump, and
    forgotten -- so six outlets reporting one flood are worth exactly as much
    as one tweet.
    """
    from src.blackboard.decay import decayed_salience

    alone = decayed_salience(0.5, "medium", _ago(6), now=NOW, corroborations=0)
    corroborated = decayed_salience(0.5, "medium", _ago(6), now=NOW,
                                    corroborations=4)
    assert corroborated > alone


def test_corroboration_saturates():
    """
    The difference between one and three sources is large; between eight and
    ten it is not. Unbounded, a busy topic would pin itself to the board.
    """
    from src.blackboard.decay import decayed_salience, MAX_CORROBORATION_BOOST

    many = decayed_salience(0.2, "medium", _ago(6), now=NOW, corroborations=50)
    some = decayed_salience(0.2, "medium", _ago(6), now=NOW, corroborations=3)
    assert many - some <= MAX_CORROBORATION_BOOST
    assert many <= 1.0


@pytest.mark.parametrize("hours,corr", [(0, 0), (100, 0), (3, 99), (0, 99)])
def test_salience_stays_within_bounds(hours, corr):
    """
    Above 1.0 one entry outranks everything forever; below 0 it sorts beneath
    things that should already be gone.
    """
    from src.blackboard.decay import decayed_salience

    value = decayed_salience(0.9, "high", _ago(hours), now=NOW, corroborations=corr)
    assert 0.0 <= value <= 1.0


# --- eviction ---------------------------------------------------------------

def test_a_faded_entry_is_evicted():
    from src.blackboard.decay import should_evict

    assert should_evict(0.01, story_id=None, created_at=_ago(5), now=NOW) is True


def test_an_entry_held_by_a_story_is_never_evicted_on_salience():
    """
    The story is the long-term memory of a developing situation. Deleting its
    contributing events leaves a thread whose evidence has vanished -- "44
    events" with nothing behind it.
    """
    from src.blackboard.decay import should_evict

    assert should_evict(0.001, story_id="story-1", created_at=_ago(5),
                        now=NOW) is False


def test_the_hard_lifetime_floor_applies_even_to_a_story():
    """
    Otherwise a permanently busy topic pins rows forever and the board stops
    describing the present -- which is the requirement, not an optimisation.
    """
    from src.blackboard.decay import should_evict, MAX_LIFETIME_HOURS

    assert should_evict(0.9, story_id="story-1",
                        created_at=_ago(MAX_LIFETIME_HOURS + 1), now=NOW) is True


def test_a_recent_high_salience_entry_survives():
    from src.blackboard.decay import should_evict

    assert should_evict(0.7, story_id=None, created_at=_ago(1), now=NOW) is False


# --- foci -------------------------------------------------------------------

def test_a_focus_decays_faster_than_the_event_that_created_it():
    """
    A focus is an instruction to look somewhere. A stale one is worse than
    none: it spends collection budget on a place nothing is happening.
    """
    from src.blackboard.decay import (
        FOCUS_HALF_LIFE_HOURS, HALF_LIFE_HOURS, focus_urgency, decayed_salience,
    )

    assert FOCUS_HALF_LIFE_HOURS < HALF_LIFE_HOURS["high"]

    hours = 6
    assert focus_urgency(0.9, _ago(hours), now=NOW) < decayed_salience(
        0.9, "high", _ago(hours), now=NOW)


def test_expiry_is_bounded():
    from src.blackboard.decay import expiry_for, MAX_LIFETIME_HOURS

    for severity in ("low", "medium", "high", "critical", None, "nonsense"):
        expiry = expiry_for(severity, now=NOW)
        assert NOW < expiry <= NOW + timedelta(hours=MAX_LIFETIME_HOURS)


# --- the shape of the data --------------------------------------------------

def test_naive_timestamps_do_not_raise():
    """
    SQLite returns naive datetimes even for timezone-aware columns, and
    subtracting mixed awareness raises TypeError. That would surface as the
    decay pass dying on the deployed instance only.
    """
    from src.blackboard.decay import decayed_salience

    naive = datetime(2026, 8, 8, 6, 0, 0)     # no tzinfo
    assert 0.0 <= decayed_salience(0.5, "high", naive, now=NOW) <= 1.0


def test_decay_is_pure():
    """
    No I/O and no clock read, so it is deterministic and testable without
    freezing time. Same inputs, same answer, every time.
    """
    from src.blackboard import decay

    source = (PROJECT_ROOT / "src" / "blackboard" / "decay.py").read_text(
        encoding="utf-8")
    for forbidden in ("session", "import requests", "engine(", "client"):
        assert forbidden not in source, f"decay.py touches {forbidden!r}"

    args = (0.6, "high", _ago(3))
    assert decay.decayed_salience(*args, now=NOW) == decay.decayed_salience(
        *args, now=NOW)
