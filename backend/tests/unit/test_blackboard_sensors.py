"""
Foci: the board saying "look here".

Nothing consumes these yet, deliberately. This stage exists to answer, with
evidence, whether opportunistic control is worth building: foci are written
from real signals, the log records what a controller WOULD have prioritised,
and that can be compared against what the fixed schedule actually collected.

If the foci turn out uninformative, the right answer is to stop and keep the
earlier stages. Finding that out before building a scheduler is much cheaper
than after, which is the entire reason this is a stage rather than a step.
"""

import sys
import uuid
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def sensors():
    from src.blackboard import sensors as module
    from src.blackboard.store import BoardStore

    try:
        from auth.db import init_db

        init_db()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no database: {exc}")
    if not BoardStore().available():
        pytest.skip("board unavailable")

    yield module

    from auth.db import session_scope
    from src.blackboard.models import BoardFocus

    with session_scope() as session:
        session.query(BoardFocus).delete()


def _region():
    return f"TestRegion{uuid.uuid4().hex[:6]}"


# --- rivernet ---------------------------------------------------------------

def test_a_flooding_river_becomes_a_district_focus(sensors):
    """
    The head of the one genuine cross-domain chain already latent in this
    codebase: a rising Kelani should send collection to Ratnapura rather than
    the five hardcoded districts it visits regardless.
    """
    region = _region()
    written = sensors.from_rivernet({"alerts": [
        {"river": "Kelani Ganga", "region": region, "severity": "critical",
         "message": "Kelani Ganga: 8.2m (rising)"},
    ]})
    assert len(written) == 1

    focus = next(f for f in sensors.current_foci(limit=20) if f["value"] == region)
    assert focus["kind"] == "district"
    assert focus["urgency"] >= 0.9


def test_severity_orders_the_foci(sensors):
    """
    The operational difference between "warning" and "critical" is not
    proportional to centimetres, so urgency is mapped rather than scaled.
    """
    bad, mild = _region(), _region()
    sensors.from_rivernet({"alerts": [
        {"region": bad, "severity": "critical", "message": "x"},
        {"region": mild, "severity": "warning", "message": "y"},
    ]})
    foci = {f["value"]: f["urgency"] for f in sensors.current_foci(limit=20)}
    assert foci[bad] > foci[mild]


def test_a_station_that_stopped_reporting_is_signal_not_silence(sensors):
    """
    A gauge going dark DURING a flood is information. Treating it as "no alert"
    is how a system reports calm at the worst moment -- and the scraper already
    surfaces it rather than dropping it.
    """
    region = _region()
    assert sensors.from_rivernet({"alerts": [
        {"region": region, "severity": "no_data",
         "message": "Gin: station not reporting"},
    ]})
    assert any(f["value"] == region for f in sensors.current_foci(limit=20))


def test_an_unrecognised_severity_writes_nothing(sensors):
    """Guessing an urgency for a reading we do not understand would put
    collection budget somewhere on the strength of a typo."""
    assert sensors.from_rivernet({"alerts": [
        {"region": _region(), "severity": "banana", "message": "?"},
    ]}) == []


# --- reinforcement ----------------------------------------------------------

def test_repeated_alerts_reinforce_one_focus_rather_than_stacking(sensors):
    """
    focus_key is unique and reinforced on conflict. Without it, three flood
    alerts in one district are three rows competing for the same attention,
    and the table grows with every cycle.
    """
    region = _region()
    for _ in range(3):
        sensors.from_rivernet({"alerts": [
            {"region": region, "severity": "warning", "message": "rising"},
        ]})

    matching = [f for f in sensors.current_foci(limit=50) if f["value"] == region]
    assert len(matching) == 1


def test_urgency_takes_the_maximum_not_the_latest(sensors):
    """
    THE subtle one. A critical reading followed by a warning reading is still a
    critical situation; letting the newer, milder signal overwrite it would
    quietly de-prioritise the thing that mattered.
    """
    region = _region()
    sensors.from_rivernet({"alerts": [
        {"region": region, "severity": "critical", "message": "8.2m"}]})
    sensors.from_rivernet({"alerts": [
        {"region": region, "severity": "warning", "message": "6.1m"}]})

    focus = next(f for f in sensors.current_foci(limit=50) if f["value"] == region)
    assert focus["urgency"] >= 0.9, (
        "a milder later reading downgraded an ongoing critical situation"
    )


# --- other sensors ----------------------------------------------------------

def test_a_trending_spike_becomes_a_focus(sensors):
    topic = f"topic-{uuid.uuid4().hex[:6]}"
    assert sensors.from_trending([{"topic": topic, "momentum": 50}])
    focus = next(f for f in sensors.current_foci(limit=50) if f["value"] == topic)
    assert focus["kind"] == "topic"


def test_trending_urgency_saturates(sensors):
    """
    20x and 50x are both "a lot". Unbounded, one noisy topic would outrank a
    flood.
    """
    hot, hotter = f"t-{uuid.uuid4().hex[:6]}", f"t-{uuid.uuid4().hex[:6]}"
    sensors.from_trending([{"topic": hot, "momentum": 20},
                           {"topic": hotter, "momentum": 500}])
    foci = {f["value"]: f["urgency"] for f in sensors.current_foci(limit=50)}
    assert foci[hotter] <= 0.85
    assert foci[hotter] - foci[hot] < 0.3


def test_only_moving_stories_become_foci(sensors):
    """A resolved story is not somewhere to spend collection budget."""
    written = sensors.from_stories([
        {"id": "s-escalating", "state": "escalating", "title": "Kelani flood"},
        {"id": "s-resolved", "state": "resolved", "title": "old news"},
        {"id": "s-quiet", "state": "quiet", "title": "nothing happening"},
    ])
    assert len(written) == 1
    values = {f["value"] for f in sensors.current_foci(limit=50)}
    assert "s-escalating" in values
    assert "s-resolved" not in values


# --- the properties that make this auditable --------------------------------

def test_every_focus_can_say_why_it_exists(sensors):
    """
    "Why did it look there" is the first question anyone asks of a scheduling
    decision. A focus without a reason cannot be argued with, and this codebase
    already treats an unexplained score as a number with authority and no
    accountability.
    """
    sensors.from_rivernet({"alerts": [
        {"region": _region(), "severity": "critical", "message": "8.2m rising"}]})
    for focus in sensors.current_foci(limit=50):
        assert focus["reason"], f"{focus['value']} has no reason"
        assert focus["source_ks"], f"{focus['value']} has no provenance"


def test_nothing_schedules_on_foci_yet():
    """
    The honest gate.

    WRITING foci is expected -- the aggregator is the producer, and that wiring
    is the whole point of the stage. What must not exist yet is a CONSUMER:
    code that reads the focus list to decide what to collect. If something
    started scheduling on these before they had been observed, this stage would
    have lost its purpose, which is proving the signals are worth acting on
    BEFORE acting on them.

    So this forbids reading `current_foci` outside the blackboard package, and
    permits the producer calls. The distinction matters enough to be stated:
    an earlier version of this test failed on the producer and would have
    pushed me to weaken the wiring rather than the assertion.
    """
    src = PROJECT_ROOT / "src"
    consumers = []
    for path in src.rglob("*.py"):
        if "blackboard" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "current_foci(" in text:
            consumers.append(str(path.relative_to(src)))

    assert not consumers, (
        f"{consumers} read the focus list; this stage exists to observe foci "
        f"before anything depends on them"
    )


def test_a_sensor_failure_never_breaks_the_cycle(sensors):
    """Malformed input writes nothing and raises nothing."""
    assert sensors.from_rivernet({}) == []
    assert sensors.from_rivernet({"alerts": [None, "nonsense", {}]}) == []
    assert sensors.from_trending(None) == []
    assert sensors.from_stories([{"no_id": True}]) == []
