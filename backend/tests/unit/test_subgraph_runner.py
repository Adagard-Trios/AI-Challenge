"""
Tests for src/graphs/subgraph_runner.py

Every scraped post was being stored twice. The five domain graphs wrapped their
subgraphs as `lambda state: subgraph.invoke(state)`, which returns the WHOLE
subgraph state -- including reducer-backed fields the subgraph merely read.
Returning `worker_results` unchanged re-applies `operator.add` against the value
the parent already holds, so the list doubles.

It was masked whenever Neo4j was up, because the URL-uniqueness constraint
absorbed the repeat. NEO4J_ENABLED is false by default and db_manager returns
"not a duplicate" when the driver is absent -- so the masking was off in exactly
the configuration everyone runs. CSV rows and ChromaDB chunks were duplicated,
and the ML training set was 100% dupes.
"""

import ast
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.graphs.subgraph_runner import ACCUMULATOR_FIELDS, subgraph_node  # noqa: E402


class _FakeSubgraph:
    """Returns whatever it is told to, like a compiled subgraph would."""

    def __init__(self, result):
        self._result = result
        self.seen = None

    def invoke(self, state):
        self.seen = state
        return self._result


# --- the headline bug ------------------------------------------------------

def test_passthrough_accumulator_is_not_returned():
    """
    THE regression. A subgraph that only READ worker_results returns it
    unchanged; re-returning it would double the parent's list.
    """
    state = {"worker_results": [{"a": 1}, {"b": 2}, {"c": 3}]}
    sub = _FakeSubgraph({"worker_results": [{"a": 1}, {"b": 2}, {"c": 3}],
                         "domain_insights": []})

    delta = subgraph_node(sub, "feed")(state)

    assert "worker_results" not in delta, (
        "an unchanged accumulator was returned; operator.add would double it"
    )


def test_only_newly_appended_items_are_returned():
    """A subgraph that appends must return ONLY its additions."""
    state = {"worker_results": [{"a": 1}]}
    sub = _FakeSubgraph({"worker_results": [{"a": 1}, {"new": 2}, {"new": 3}]})

    delta = subgraph_node(sub, "collect")(state)

    assert delta["worker_results"] == [{"new": 2}, {"new": 3}]


def test_end_to_end_through_a_real_graph_does_not_double():
    """
    The property that matters, through LangGraph itself rather than a stub:
    a read-only subgraph downstream of producers must not double the list.
    """
    import operator
    from typing import Annotated, Any, Dict, List

    from langgraph.graph import END, START, StateGraph
    from typing_extensions import TypedDict

    class S(TypedDict, total=False):
        worker_results: Annotated[List[Dict[str, Any]], operator.add]
        note: str

    inner = StateGraph(S)
    inner.add_node("readonly", lambda s: {"note": f"saw {len(s['worker_results'])}"})
    inner.set_entry_point("readonly")
    inner.add_edge("readonly", END)
    compiled = inner.compile()

    outer = StateGraph(S)
    outer.add_node("produce", lambda s: {"worker_results": [{"i": 1}, {"i": 2}]})
    outer.add_node("consume", subgraph_node(compiled, "inner"))
    outer.add_edge(START, "produce")
    outer.add_edge("produce", "consume")
    outer.add_edge("consume", END)

    final = outer.compile().invoke({"worker_results": []})

    assert len(final["worker_results"]) == 2, (
        f"expected 2 items, got {len(final['worker_results'])} -- "
        "the accumulator was double-applied"
    )
    assert final["note"] == "saw 2"


def test_the_old_pattern_would_have_doubled():
    """
    Documents the failure so the reason for the helper stays understood: the
    naive lambda really does double, it was not a theoretical concern.
    """
    import operator
    from typing import Annotated, Any, Dict, List

    from langgraph.graph import END, START, StateGraph
    from typing_extensions import TypedDict

    class S(TypedDict, total=False):
        worker_results: Annotated[List[Dict[str, Any]], operator.add]

    inner = StateGraph(S)
    inner.add_node("readonly", lambda s: {})
    inner.set_entry_point("readonly")
    inner.add_edge("readonly", END)
    compiled = inner.compile()

    outer = StateGraph(S)
    outer.add_node("produce", lambda s: {"worker_results": [{"i": 1}, {"i": 2}]})
    outer.add_node("consume", lambda s: compiled.invoke(s))    # the OLD pattern
    outer.add_edge(START, "produce")
    outer.add_edge("produce", "consume")
    outer.add_edge("consume", END)

    final = outer.compile().invoke({"worker_results": []})
    assert len(final["worker_results"]) == 4, "the old pattern should double"


# --- coverage of the field list -------------------------------------------

def test_accumulator_list_matches_the_declared_reducers():
    """
    ACCUMULATOR_FIELDS must cover every Annotated field in the states. A new
    reducer field left out of the list silently reintroduces the doubling.
    """
    declared = set()
    for state_file in (PROJECT_ROOT / "src" / "states").glob("*AgentState.py"):
        tree = ast.parse(state_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)):
                continue
            ann = node.annotation
            if isinstance(ann, ast.Subscript) and isinstance(ann.value, ast.Name) \
                    and ann.value.id == "Annotated":
                declared.add(node.target.id)

    missing = declared - set(ACCUMULATOR_FIELDS)
    assert not missing, (
        f"reducer-backed field(s) missing from ACCUMULATOR_FIELDS: {sorted(missing)}. "
        "Any subgraph that passes one through will double it."
    )


def test_no_graph_still_uses_the_raw_lambda():
    """The original pattern existed in five files; make sure none came back."""
    offenders = []
    for graph_file in (PROJECT_ROOT / "src" / "graphs").glob("*.py"):
        # subgraph_runner.py quotes the broken pattern in its own docstring to
        # explain what it exists to prevent.
        if graph_file.name == "subgraph_runner.py":
            continue
        src = graph_file.read_text(encoding="utf-8")
        for i, line in enumerate(src.splitlines(), 1):
            if "lambda state:" in line and ".invoke(state)" in line:
                offenders.append(f"{graph_file.name}:{i}")
    assert not offenders, (
        "raw subgraph invocation reintroduced (doubles reducer fields) at: "
        + ", ".join(offenders) + " -- use subgraph_node() instead"
    )


# --- behaviour preservation ------------------------------------------------

def test_non_accumulator_keys_pass_through():
    sub = _FakeSubgraph({"llm_summary": "hello", "structured_feed": {"x": 1}})
    delta = subgraph_node(sub, "feed")({})
    assert delta == {"llm_summary": "hello", "structured_feed": {"x": 1}}


def test_subgraph_receives_the_full_parent_state():
    """Filtering is on the way OUT only -- the subgraph still sees everything."""
    sub = _FakeSubgraph({})
    state = {"worker_results": [{"a": 1}], "llm_summary": "ctx"}
    subgraph_node(sub, "x")(state)
    assert sub.seen == state


def test_shrinking_an_accumulator_is_reported(caplog):
    """operator.add cannot remove items; silently ignoring that would confuse."""
    import logging
    state = {"worker_results": [{"a": 1}, {"b": 2}]}
    sub = _FakeSubgraph({"worker_results": [{"a": 1}]})
    with caplog.at_level(logging.WARNING):
        delta = subgraph_node(sub, "shrinker")(state)
    assert "worker_results" not in delta
    assert "shorter" in caplog.text


def test_non_dict_result_is_passed_through():
    sub = _FakeSubgraph(None)
    assert subgraph_node(sub, "x")({}) is None
