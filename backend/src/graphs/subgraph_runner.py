"""
src/graphs/subgraph_runner.py
Invoke a compiled subgraph as a node without double-applying reducers.

The bug this fixes
------------------
Every domain graph wrapped its subgraphs like this:

    main_graph.add_node("feed_generation_module",
                        lambda state: feed_subgraph.invoke(state))

``subgraph.invoke()`` returns the **whole** subgraph state, including fields the
subgraph only read. Several of those fields carry reducers -- ``worker_results``
is ``Annotated[List, operator.add]`` -- so returning them re-applies the reducer
against the value the parent already holds:

    parent has        [T, S, U]
    subgraph returns  [T, S, U]      (it only read them)
    operator.add  ->  [T, S, U, T, S, U]

By the time ``feed_aggregator`` ran, every scraped post appeared twice. It was
written to the CSV twice and to ChromaDB twice, and ``unique_posts`` in the
printed stats was double the truth. The ML training set was 100% duplicated
rows.

It was masked whenever Neo4j was reachable, because the URL-uniqueness
constraint absorbed the repeat -- but ``NEO4J_ENABLED`` is false by default, and
``db_manager.py:143`` returns "not duplicate" when the driver is absent. So the
masking was off precisely in the configuration everyone runs.

The fix
-------
Return only what the subgraph actually *added*. For an accumulator field we know
how long it was on the way in, so anything beyond that is new and anything else
is a pass-through to be dropped.

This is deliberately a shared helper rather than five copies: the original bug
existed five times because the wrapper was written five times.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict

logger = logging.getLogger("Roger.graphs.subgraph")

# Fields declared with a reducer in any of the agent states. Returning one of
# these unchanged from a subgraph is what double-applies the reducer.
#
# Keep in sync with src/states/*AgentState.py -- test_subgraph_runner.py asserts
# this list matches the Annotated fields actually declared there, so a new
# reducer field cannot silently reintroduce the bug.
ACCUMULATOR_FIELDS = frozenset({
    "worker_results",
    "latest_worker_results",
    "social_media_results",
    "domain_insights",
    "feed_history",
})


def subgraph_node(subgraph, name: str = "subgraph") -> Callable[[Dict], Dict]:
    """
    Wrap a compiled subgraph as a graph node.

    Returns only the delta: for accumulator fields, the items the subgraph
    appended; for everything else, whatever it produced.
    """

    def run(state: Dict[str, Any]) -> Dict[str, Any]:
        before = {
            field: len(state.get(field) or [])
            for field in ACCUMULATOR_FIELDS
            if isinstance(state.get(field), list)
        }

        result = subgraph.invoke(state)
        if not isinstance(result, dict):
            return result

        delta: Dict[str, Any] = {}
        for key, value in result.items():
            if key in ACCUMULATOR_FIELDS and isinstance(value, list):
                prior = before.get(key, 0)
                if len(value) > prior:
                    # Only the newly appended items -- the reducer adds these to
                    # what the parent already has.
                    delta[key] = value[prior:]
                elif len(value) < prior:
                    # A subgraph that shrank an accumulator is doing something
                    # the reducer cannot express (operator.add only grows).
                    # Surface it rather than silently picking a behaviour.
                    logger.warning(
                        "[%s] returned a shorter %r (%d -> %d); reducers only "
                        "append, so the removal will not take effect",
                        name, key, prior, len(value),
                    )
                # equal length -> pass-through, omit so it is not re-added
            else:
                delta[key] = value

        return delta

    run.__name__ = f"{name}_node"
    return run
