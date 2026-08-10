"""
Guards for graph construction, orchestrator identity and storage separation.

These four defects shared a shape: the system did a great deal of work at import
time, under names that did not mean what they said, and wrote two unrelated
corpora into one place. None of them raised.
"""

import ast
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

GRAPHS = PROJECT_ROOT / "src" / "graphs"
NODES = PROJECT_ROOT / "src" / "nodes"
STATES = PROJECT_ROOT / "src" / "states"

# Modules that compile and expose a `graph`. Excludes __init__.py and
# subgraph_runner.py, which are helpers rather than graph definitions.
GRAPH_MODULES = sorted(
    p for p in GRAPHS.glob("*.py")
    if p.name.endswith("AgentGraph.py")
)


def _module_level_calls(tree):
    """Every Call node reachable from a top-level statement."""
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call):
                yield node


def _callee_name(call):
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


# --- import-time graph construction ---------------------------------------

@pytest.mark.parametrize("path", sorted(GRAPHS.glob("*.py")), ids=lambda p: p.name)
def test_graphs_are_not_built_at_import(path):
    """
    REGRESSION. Every graph module ended in

        llm = GroqLLM().get_llm()
        graph = SomeGraphBuilder(llm).build_graph()

    so merely importing a module for its builder class constructed a whole
    graph -- with each node's agents, ToolSet and Neo4j/ChromaDB managers.
    combinedAgentGraph imports the five domain builders and then builds them
    again inside build_graph(), so `import main` compiled 43 graphs and took
    ~70s before uvicorn could bind a socket. Measured after the fix: 0.

    The module-level `graph` name still exists for langgraph.json, but it is
    served lazily by a PEP 562 module __getattr__.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders = [
        _callee_name(c)
        for c in _module_level_calls(tree)
        if _callee_name(c).startswith("build_") or _callee_name(c) == "get_llm"
    ]
    assert not offenders, (
        f"{path.name} builds at import time: {offenders}. Serve `graph` from a "
        "module __getattr__ instead."
    )


@pytest.mark.parametrize("path", GRAPH_MODULES, ids=lambda p: p.name)
def test_graph_modules_still_expose_graph(path):
    """The laziness must not break langgraph.json, which references `...py:graph`."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert "__getattr__" in names, (
        f"{path.name} has no module __getattr__, so `from {path.stem} import graph` "
        "and langgraph.json would break"
    )


def test_main_does_not_import_the_graph_at_module_scope():
    """
    REGRESSION. `from src.graphs.combinedAgentGraph import graph` at main.py's
    top level put the entire graph build on uvicorn's startup path, which is
    what failed Render's 5s health check. run_graph_loop imports it in the
    worker thread instead.
    """
    tree = ast.parse((PROJECT_ROOT / "main.py").read_text(encoding="utf-8"))
    for stmt in tree.body:
        if isinstance(stmt, ast.ImportFrom) and "graphs" in (stmt.module or ""):
            pytest.fail(
                f"main.py:{stmt.lineno} imports {stmt.module} at module scope; "
                "building the graph must not block the API from serving"
            )


def test_langgraph_json_names_match_their_files():
    """
    REGRESSION. The key "RogerGraph" pointed at combinedAgentGraph.py, so
    LangGraph Studio and production ran different graphs under one name.
    """
    cfg = json.loads((PROJECT_ROOT / "langgraph.json").read_text(encoding="utf-8"))
    stems = {p.stem.lower() for p in GRAPH_MODULES}

    seen = {}
    for name, ref in cfg["graphs"].items():
        target = ref.split(":")[0]
        assert (PROJECT_ROOT / target).exists(), f"{ref} does not exist"

        stem = Path(target).stem.lower()
        normalised = name.replace("_", "").lower()

        # The precise defect: a key that IS the name of a different graph
        # module. "RogerGraph" pointing at combinedAgentGraph.py meant asking
        # Studio for RogerGraph silently ran the other topology.
        if normalised in stems:
            assert normalised == stem, (
                f'langgraph.json exposes "{name}" -- the name of another graph '
                f"module -- but points at {Path(target).name}"
            )

        assert target not in seen, (
            f'"{name}" and "{seen[target]}" both point at {Path(target).name}'
        )
        seen[target] = name


# --- orchestrator identity -------------------------------------------------

def test_there_is_exactly_one_orchestrator():
    """
    REGRESSION, now resolved by deletion. CombinedAgentGraphBuilder was defined
    in BOTH RogerGraph.py and combinedAgentGraph.py with different topologies
    and different agent counts; main.py imported one and app.py the other, so
    which graph ran depended entirely on the import path. Renaming them made
    that visible, but two orchestrators drifting apart is a fork waiting to
    happen -- and app.py was referenced by no Dockerfile, script or blueprint,
    so RogerFullGraph had never run in production at all.
    """
    orchestrators = [
        p for p in GRAPHS.glob("*.py")
        if "CombinedAgentNode" in p.read_text(encoding="utf-8")
    ]
    assert len(orchestrators) == 1, (
        f"expected one orchestrator, found: {[p.name for p in orchestrators]}"
    )
    assert orchestrators[0].name == "combinedAgentGraph.py"


def test_the_dead_orchestrator_is_gone():
    """Deleted, not merely unreferenced -- dead code that looks alive is the
    whole problem this project keeps hitting."""
    assert not (GRAPHS / "RogerGraph.py").exists()
    assert not (PROJECT_ROOT / "app.py").exists()


def test_no_unreachable_loop_branch():
    """
    There was a conditional edge whose "GraphInitiator" branch could never be
    selected -- data_refresh_router returned {"route": "END"} unconditionally --
    and if it ever had been, the graph would have re-entered itself and hit
    LangGraph's recursion limit rather than looping.

    The router node has since been deleted outright: a node whose entire body
    returns one constant is not a decision. The assertion stays, because the
    cadence is still driven by main.py's run_graph_loop and a conditional edge
    reappearing here would mean someone had tried to loop inside the graph
    again.
    """
    for name in ("combinedAgentGraph.py",):
        src = (GRAPHS / name).read_text(encoding="utf-8")
        assert "add_conditional_edges" not in src, (
            f"{name} loops inside the graph; the 60s cadence belongs to "
            f"main.py's run_graph_loop"
        )


def test_the_no_op_router_is_gone():
    """
    REGRESSION. DataRefreshRouter was a node, an edge and a state field whose
    only job was to return the same answer every time.
    """
    src = (GRAPHS / "combinedAgentGraph.py").read_text(encoding="utf-8")
    node = (PROJECT_ROOT / "src" / "nodes" / "combinedAgentNode.py").read_text(
        encoding="utf-8")
    state = (PROJECT_ROOT / "src" / "states" / "combinedAgentState.py").read_text(
        encoding="utf-8")

    assert 'add_node("DataRefreshRouter"' not in src
    assert "def data_refresh_router" not in node
    assert "route: Optional[str] = Field" not in state, (
        "the route field outlived the router that wrote it"
    )


# --- storage separation ----------------------------------------------------

def test_event_store_and_rag_corpus_use_different_collections():
    """
    REGRESSION. storage/config.CHROMADB_COLLECTION and
    utils/db_manager.ChromaDBManager both defaulted to "Roger_feeds".
    ChromaDBStore.find_similar queries that collection with n_results=1 and no
    filter to decide whether an event is a duplicate -- so its nearest
    neighbour was typically the raw post the event had been summarised FROM,
    which scored far above threshold and got the event discarded as a duplicate
    of its own source.
    """
    from src.storage.config import config
    from src.utils.db_manager import ChromaDBManager
    import inspect

    rag_default = inspect.signature(ChromaDBManager.__init__).parameters[
        "collection_name"
    ].default

    assert config.CHROMADB_COLLECTION != rag_default, (
        f"both stores write to {rag_default!r}"
    )


def test_similarity_search_is_restricted_to_this_stores_records():
    """
    Defence in depth: CHROMADB_COLLECTION is env-overridable, so it can still be
    pointed at the RAG corpus. The query must filter to records this store
    wrote, and add_event must write the marker it filters on.
    """
    src = (PROJECT_ROOT / "src" / "storage" / "chromadb_store.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(src)

    queries = [
        c for c in ast.walk(tree)
        if isinstance(c, ast.Call) and _callee_name(c) == "query"
    ]
    assert queries, "no collection.query call found"
    for call in queries:
        assert any(kw.arg == "where" for kw in call.keywords), (
            f"chromadb_store.py:{call.lineno} queries without a `where` filter"
        )

    from src.storage.chromadb_store import RECORD_TYPE
    assert 'safe_metadata["record_type"] = RECORD_TYPE' in src, (
        "add_event does not stamp the marker find_similar filters on, so nothing "
        "will ever match"
    )
    assert RECORD_TYPE


# --- political severity ----------------------------------------------------

def test_political_severity_branches_are_distinct():
    """
    REGRESSION. The if and the elif both assigned "high", so the elif was a
    no-op and routine governance vocabulary ("parliament", "policy", "bill")
    scored the same as unrest. Since severity now drives the confidence score
    directly, that would have put every political post over the high-priority
    threshold.
    """
    src = (NODES / "politicalAgentNode.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or not node.orelse:
            continue
        assigned = []
        for branch in (node.body, node.orelse):
            for stmt in branch:
                if (isinstance(stmt, ast.Assign)
                        and isinstance(stmt.targets[0], ast.Name)
                        and stmt.targets[0].id == "severity"
                        and isinstance(stmt.value, ast.Constant)):
                    assigned.append(stmt.value.value)
        if len(assigned) == 2:
            assert assigned[0] != assigned[1], (
                f"politicalAgentNode.py:{node.lineno} -- both branches assign "
                f"severity={assigned[0]!r}, so the second is dead"
            )


def test_political_can_report_an_opportunity():
    """impact_type was hardcoded "risk", so that domain could only ever warn."""
    src = (NODES / "politicalAgentNode.py").read_text(encoding="utf-8")
    assert '"impact_type": "impact"' not in src
    assert 'impact = "opportunity"' in src, (
        "political insights still hardcode impact_type, so the domain can never "
        "surface an opportunity"
    )


# --- dead state field ------------------------------------------------------

def test_change_detected_is_gone():
    """
    Declared in all five states, read in one node, written by none -- so the
    read was permanently False and implied a cross-cycle comparison that never
    happened.
    """
    offenders = []
    for path in list(STATES.glob("*.py")) + list(NODES.glob("*.py")):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "change_detected: bool" in stripped or 'get("change_detected"' in stripped:
                offenders.append(f"{path.name}:{i}")
    assert not offenders, f"phantom field is back: {offenders}"
