"""
The risk indices reach the dashboard.

DataRefresherAgent computes a full snapshot every cycle -- logistics_friction,
compliance_volatility, market_instability, opportunity_index, and the driver
events behind each -- and returns it as `risk_dashboard_snapshot`.

Nothing in main.py ever read it. There were exactly two mentions of that key in
the whole file: the zeroed literal it is initialised with, and the line
/api/dashboard serves it from. So the dashboard reported

    logistics_friction:     0.0
    compliance_volatility:  0.0
    market_instability:     0.0

for the entire lifetime of the process, on every deployment, while a perfectly
good snapshot was computed and discarded sixty seconds apart.

This is the shape of bug this codebase keeps producing: a feature that works on
one path and is silently dropped on the other. It is invisible because zero is
a plausible number for a risk index -- it reads as "nothing is happening"
rather than "nothing is connected".
"""

import ast
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

MAIN = PROJECT_ROOT / "main.py"


def test_the_graph_loop_captures_the_snapshot_it_is_sent():
    """
    REGRESSION. Asserted against the source rather than by running a cycle,
    because reproducing it live needs a full agent cycle and a Groq key -- and
    a test that is skipped on CI is not a guard.
    """
    source = MAIN.read_text(encoding="utf-8")
    tree = ast.parse(source)

    loop = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "run_graph_loop"
    )
    body = ast.get_source_segment(source, loop) or ""

    assert "risk_dashboard_snapshot" in body, (
        "run_graph_loop never mentions risk_dashboard_snapshot, so the "
        "snapshot DataRefresherAgent computes is discarded and /api/dashboard "
        "serves its zeroed initial value forever"
    )
    assert "shared_state.update" in body, (
        "the snapshot is read from the node output but never written into the "
        "shared state, which is what /api/dashboard actually serves"
    )


def test_the_snapshot_is_merged_not_replaced():
    """
    A node that reports only part of the snapshot must not blank the rest.
    Replacement would make the dashboard flicker between full and partial
    depending on which node emitted last.
    """
    source = MAIN.read_text(encoding="utf-8")
    tree = ast.parse(source)
    loop = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "run_graph_loop"
    )
    body = ast.get_source_segment(source, loop) or ""

    assert '**shared_state.get("risk_dashboard_snapshot", {})' in body, (
        "the snapshot is assigned wholesale rather than merged over what is "
        "already there"
    )


def test_the_dashboard_route_still_serves_that_key():
    """The two halves must agree on the key; renaming one silently breaks it."""
    source = MAIN.read_text(encoding="utf-8")
    assert 'shared_state.get("risk_dashboard_snapshot", {})' in source, (
        "/api/dashboard no longer reads risk_dashboard_snapshot"
    )


def test_zero_is_a_plausible_reading_so_the_write_is_logged():
    """
    An index of 0.0 reads as "nothing is happening", not "nothing is wired".
    That is exactly why this survived, so the write says so in the log.
    """
    source = MAIN.read_text(encoding="utf-8")
    assert "updated the risk snapshot" in source, (
        "nothing logs that the snapshot was applied, so a future regression "
        "would again be silent"
    )


def test_a_cycle_with_no_new_events_does_not_blank_the_dashboard():
    """
    REGRESSION, and the most misleading kind.

    A cycle whose events are all suppressed by dedup is the NORMAL outcome when
    the sources have published nothing since the last run. DataRefresherAgent
    used to return zero metrics for that, and those zeros overwrote a perfectly
    good snapshot. Observed on a real run that reported "0 unique, 11 exact
    dups":

        before   compliance 0.53, market 0.52, 2 high priority
        after    all zeros

    A reader cannot tell that apart from "the country is calm", which is the
    opposite of what an intelligence dashboard is for. "No new events" is not
    "no risk".
    """
    from src.nodes.combinedAgentNode import CombinedAgentNode
    from src.runtime import shared_state

    shared_state.update({"risk_dashboard_snapshot": {
        "compliance_volatility": 0.53, "market_instability": 0.52,
        "total_events": 7, "high_priority_count": 2,
        "last_updated": "2026-08-08T10:00:00",
    }})

    node = CombinedAgentNode.__new__(CombinedAgentNode)

    class EmptyState:
        final_ranked_feed = []

    snapshot = CombinedAgentNode.data_refresher_agent(
        node, EmptyState())["risk_dashboard_snapshot"]

    assert snapshot["compliance_volatility"] == 0.53, (
        "a quiet cycle blanked the risk indices; the dashboard now claims "
        "nothing is happening rather than nothing changed"
    )
    assert snapshot["total_events"] == 7
    # Marked, and the timestamp is the one it was actually computed at, so
    # "nothing changed" shows as an ageing last_updated rather than hiding
    # behind a fresh one.
    assert snapshot.get("stale") is True
    assert snapshot["last_updated"] == "2026-08-08T10:00:00"


def test_zeros_are_still_reported_when_nothing_has_ever_been_computed():
    """Carrying forward must not invent a history that does not exist."""
    from src.nodes.combinedAgentNode import CombinedAgentNode
    from src.runtime import redis_client, shared_state

    client = redis_client.get_client()
    if client is not None:
        client.delete(shared_state.STATE_KEY)
    shared_state.reset()

    node = CombinedAgentNode.__new__(CombinedAgentNode)

    class EmptyState:
        final_ranked_feed = []

    snapshot = CombinedAgentNode.data_refresher_agent(
        node, EmptyState())["risk_dashboard_snapshot"]

    assert snapshot["total_events"] == 0
    assert snapshot.get("stale") is None
