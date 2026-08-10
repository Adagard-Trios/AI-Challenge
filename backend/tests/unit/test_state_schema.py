"""
Guard against silently dropped state keys.

LangGraph discards any key a node returns that is not declared in the state
schema -- with no warning and no error:

    # langgraph/graph/state.py:985
    return [(k, v) for k, v in input.items() if k in output_keys]

That makes this class of bug invisible by construction. A node returns
`{"river_data": ...}`, the write silently drops it, the consumer reads
`state.get("river_data", {})` and gets `{}`, and the run reports success. The
only symptom is a feature that quietly does nothing.

Three real cases were found this way. `river_data` was referenced 15 times
across the meteorological node and declared zero times, which meant the entire
rivernet scraper -- network cost included -- produced flood data that was thrown
away before anything could read it.

This test walks each node module's AST, collects every key returned in a dict
literal, and asserts the state schema declares it. It is the only thing standing
between us and the next silently dropped field.
"""

import ast
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

NODES = PROJECT_ROOT / "src" / "nodes"
STATES = PROJECT_ROOT / "src" / "states"

# node module -> state module. combinedAgentNode uses a Pydantic model rather
# than a TypedDict and is checked separately.
NODE_TO_STATE = {
    "socialAgentNode.py": "socialAgentState.py",
    "politicalAgentNode.py": "politicalAgentState.py",
    "economicalAgentNode.py": "economicalAgentState.py",
    "meteorologicalAgentNode.py": "meteorologicalAgentState.py",
    "intelligenceAgentNode.py": "intelligenceAgentState.py",
    "dataRetrievalAgentNode.py": "dataRetrievalAgentState.py",
}

# Keys that are deliberately local -- returned by helpers that feed other code
# rather than being written to graph state. Keep this list SHORT and justified;
# every entry is a place the guard is switched off.
EXEMPT = {
    # Scraper/tool payloads and per-post records, not state writes.
    "source", "poster", "text", "url", "timestamp", "error", "status",
    "results", "count", "platform", "reason", "query", "total_found",
    "fetched_at", "summary", "severity", "impact_type", "confidence",
    "category", "subcategory", "content", "title", "district", "region",
    "keep", "fake_news_score", "enhanced_summary", "insight", "score",
    "name", "value", "type", "id", "data", "message", "detail", "keywords",
    "profile", "raw_content", "source_tool", "domain", "metadata",
    "risk_score", "opportunity_score", "location", "level", "trend",
}


def _declared_keys(state_file: Path) -> set:
    """Every field name declared on a TypedDict/BaseModel in the state module."""
    tree = ast.parse(state_file.read_text(encoding="utf-8"))
    declared = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    declared.add(stmt.target.id)
    return declared


def _returned_keys(node_file: Path) -> dict:
    """
    Keys returned in a dict literal, mapped to the line they appear on.

    Only `return {...}` at the top level of a function is considered -- that is
    what LangGraph filters. Nested dicts inside a returned value are payload,
    not state.
    """
    tree = ast.parse(node_file.read_text(encoding="utf-8"))
    found = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Dict):
            continue
        for key in node.value.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                found.setdefault(key.value, node.lineno)
    return found


@pytest.mark.parametrize("node_name,state_name", sorted(NODE_TO_STATE.items()))
def test_returned_keys_are_declared_in_state(node_name, state_name):
    """
    Every key a node returns must exist in its state schema, or LangGraph drops
    it silently.
    """
    node_file, state_file = NODES / node_name, STATES / state_name
    if not node_file.exists() or not state_file.exists():
        pytest.skip(f"{node_name} or {state_name} not present")

    declared = _declared_keys(state_file)
    returned = _returned_keys(node_file)

    undeclared = {
        key: line for key, line in returned.items()
        if key not in declared and key not in EXEMPT
    }

    assert not undeclared, (
        f"{node_name} returns key(s) that {state_name} does not declare, so "
        f"LangGraph will DISCARD them silently:\n"
        + "\n".join(f"    {k!r} returned at {node_name}:{line}"
                    for k, line in sorted(undeclared.items(), key=lambda kv: kv[1]))
        + f"\n\n  Add them to {state_name}, or add to EXEMPT in this test if the "
          f"dict genuinely is not a state write."
    )


def test_consumed_keys_are_declared():
    """
    The other direction: a node reading state.get("x") for an undeclared "x"
    always gets the default. That is exactly how river_data read {} fifteen
    times while the scraper ran successfully every cycle.
    """
    problems = []
    for node_name, state_name in NODE_TO_STATE.items():
        node_file, state_file = NODES / node_name, STATES / state_name
        if not node_file.exists() or not state_file.exists():
            continue
        declared = _declared_keys(state_file)
        tree = ast.parse(node_file.read_text(encoding="utf-8"))

        for call in ast.walk(tree):
            # match  state.get("key", ...)
            if not isinstance(call, ast.Call):
                continue
            fn = call.func
            if not (isinstance(fn, ast.Attribute) and fn.attr == "get"):
                continue
            if not (isinstance(fn.value, ast.Name) and fn.value.id == "state"):
                continue
            if not call.args or not isinstance(call.args[0], ast.Constant):
                continue
            key = call.args[0].value
            if isinstance(key, str) and key not in declared and key not in EXEMPT:
                problems.append(f"{node_name}:{call.lineno} reads state.get({key!r}) "
                                f"but {state_name} does not declare it")

    assert not problems, (
        "Nodes read state keys their schema does not declare, so the read always "
        "returns the default:\n    " + "\n    ".join(sorted(problems))
    )


def test_every_node_has_a_state_module():
    """A new node without a mapping here would skip the guard entirely."""
    actual = {p.name for p in NODES.glob("*AgentNode.py")}
    mapped = set(NODE_TO_STATE)
    unmapped = actual - mapped - {"combinedAgentNode.py"}
    assert not unmapped, (
        f"node module(s) not covered by the schema guard: {sorted(unmapped)}. "
        "Add them to NODE_TO_STATE."
    )


def test_parallel_written_lists_have_reducers():
    """
    A list field written by several parallel nodes needs an Annotated reducer,
    or LangGraph raises InvalidUpdateError at runtime -- and inconsistency
    between agents means the same field behaves differently per domain.
    """
    import re

    inconsistent = []
    for field in ("worker_results", "domain_insights"):
        annotated = {}
        for state_file in STATES.glob("*AgentState.py"):
            src = state_file.read_text(encoding="utf-8")
            # Pydantic BaseModel states declare merge behaviour differently
            # (Field(default_factory=...)), so comparing them against
            # TypedDict Annotated reducers is apples-to-oranges.
            if "Field(default_factory" in src:
                continue
            m = re.search(rf"^\s*{field}\s*:\s*(.+)$", src, re.M)
            if m:
                annotated[state_file.name] = "Annotated" in m.group(1)
        if annotated and len(set(annotated.values())) > 1:
            inconsistent.append(
                f"{field}: " + ", ".join(f"{k}={'reducer' if v else 'NO reducer'}"
                                         for k, v in sorted(annotated.items()))
            )

    assert not inconsistent, (
        "the same field has a reducer in some agents but not others, so it "
        "accumulates in one and last-write-wins in another:\n    "
        + "\n    ".join(inconsistent)
    )
