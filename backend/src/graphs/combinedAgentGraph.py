"""
combinedAgentGraph.py - Main entry point for the Combined Agent System.

The orchestrator. main.py runs this one, and it is now the only one.

Each domain agent is wrapped in a Python function that calls subgraph.invoke({})
on a FRESH state and catches its exceptions, so one failing agent degrades to
zero insights rather than failing the whole cycle. Five agents.

A second orchestrator lived in RogerGraph.py until 4914bc4: same class name
(CombinedAgentGraphBuilder), different topology, six agents, subgraphs added
directly as LangGraph nodes so a raising agent aborted the run. Which one you
got depended on which module you imported -- main.py took this one, app.py the
other. app.py was referenced by no Dockerfile, script or blueprint, so that
topology had never actually run in production. Both are in git history if the
fan-out-with-DataRetrievalAgent shape is ever wanted back.
"""

from __future__ import annotations
from typing import Dict, Any
import logging

from langgraph.graph import StateGraph, START, END

from src.llms.groqllm import GroqLLM
from src.states.combinedAgentState import CombinedAgentState
from src.nodes.combinedAgentNode import CombinedAgentNode

try:
    from src.config.langsmith_config import LangSmithConfig

    _langsmith = LangSmithConfig()
    _langsmith.configure()
except ImportError:
    pass

from src.graphs.socialAgentGraph import SocialGraphBuilder
from src.graphs.intelligenceAgentGraph import IntelligenceGraphBuilder
from src.graphs.economicalAgentGraph import EconomicalGraphBuilder
from src.graphs.politicalAgentGraph import PoliticalGraphBuilder
from src.graphs.meteorologicalAgentGraph import MeteorologicalGraphBuilder

logger = logging.getLogger("main_graph")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(ch)


class CombinedAgentGraph:
    def __init__(self, llm):
        self.llm = llm

    def build_graph(self):
        social_graph = SocialGraphBuilder(self.llm).build_graph()
        intelligence_graph = IntelligenceGraphBuilder(self.llm).build_graph()
        economical_graph = EconomicalGraphBuilder(self.llm).build_graph()
        political_graph = PoliticalGraphBuilder(self.llm).build_graph()
        meteorological_graph = MeteorologicalGraphBuilder(self.llm).build_graph()

        def run_social_agent(state: CombinedAgentState) -> Dict[str, Any]:
            logger.info("[CombinedGraph] Invoking SocialAgent...")
            try:
                result = social_graph.invoke({})
                insights = result.get("domain_insights", [])
                logger.info(
                    f"[CombinedGraph] SocialAgent returned {len(insights)} insights"
                )
                return {"domain_insights": insights}
            except Exception as e:
                logger.error(f"[CombinedGraph] SocialAgent FAILED: {e}")
                return {"domain_insights": []}

        def run_intelligence_agent(state: CombinedAgentState) -> Dict[str, Any]:
            logger.info("[CombinedGraph] Invoking IntelligenceAgent...")
            try:
                result = intelligence_graph.invoke({})
                insights = result.get("domain_insights", [])
                logger.info(
                    f"[CombinedGraph] IntelligenceAgent returned {len(insights)} insights"
                )
                return {"domain_insights": insights}
            except Exception as e:
                logger.error(f"[CombinedGraph] IntelligenceAgent FAILED: {e}")
                return {"domain_insights": []}

        def run_economical_agent(state: CombinedAgentState) -> Dict[str, Any]:
            logger.info("[CombinedGraph] Invoking EconomicalAgent...")
            try:
                result = economical_graph.invoke({})
                insights = result.get("domain_insights", [])
                logger.info(
                    f"[CombinedGraph] EconomicalAgent returned {len(insights)} insights"
                )
                return {"domain_insights": insights}
            except Exception as e:
                logger.error(f"[CombinedGraph] EconomicalAgent FAILED: {e}")
                return {"domain_insights": []}

        def run_political_agent(state: CombinedAgentState) -> Dict[str, Any]:
            logger.info("[CombinedGraph] Invoking PoliticalAgent...")
            try:
                result = political_graph.invoke({})
                insights = result.get("domain_insights", [])
                logger.info(
                    f"[CombinedGraph] PoliticalAgent returned {len(insights)} insights"
                )
                return {"domain_insights": insights}
            except Exception as e:
                logger.error(f"[CombinedGraph] PoliticalAgent FAILED: {e}")
                return {"domain_insights": []}

        def run_meteorological_agent(state: CombinedAgentState) -> Dict[str, Any]:
            logger.info("[CombinedGraph] Invoking MeteorologicalAgent...")
            try:
                result = meteorological_graph.invoke({})
                insights = result.get("domain_insights", [])
                logger.info(
                    f"[CombinedGraph] MeteorologicalAgent returned {len(insights)} insights"
                )
                return {"domain_insights": insights}
            except Exception as e:
                logger.error(f"[CombinedGraph] MeteorologicalAgent FAILED: {e}")
                return {"domain_insights": []}

        orchestrator = CombinedAgentNode(self.llm)
        workflow = StateGraph(CombinedAgentState)

        workflow.add_node("SocialAgent", run_social_agent)
        workflow.add_node("IntelligenceAgent", run_intelligence_agent)
        workflow.add_node("EconomicalAgent", run_economical_agent)
        workflow.add_node("PoliticalAgent", run_political_agent)
        workflow.add_node("MeteorologicalAgent", run_meteorological_agent)

        workflow.add_node("GraphInitiator", orchestrator.graph_initiator)
        workflow.add_node("FeedAggregatorAgent", orchestrator.feed_aggregator_agent)
        workflow.add_node("DataRefresherAgent", orchestrator.data_refresher_agent)
        workflow.add_node("DataRefreshRouter", orchestrator.data_refresh_router)

        workflow.add_edge(START, "GraphInitiator")

        sub_agents = [
            "SocialAgent",
            "IntelligenceAgent",
            "EconomicalAgent",
            "PoliticalAgent",
            "MeteorologicalAgent",
        ]
        for agent in sub_agents:
            workflow.add_edge("GraphInitiator", agent)
            workflow.add_edge(agent, "FeedAggregatorAgent")

        workflow.add_edge("FeedAggregatorAgent", "DataRefresherAgent")
        workflow.add_edge("DataRefresherAgent", "DataRefreshRouter")

        # data_refresh_router returns {"route": "END"} unconditionally -- the
        # 60s cadence is driven externally by main.py's run_graph_loop, not by
        # looping inside the graph. The old conditional edge kept a
        # "GraphInitiator" branch that nothing could select; had anything ever
        # selected it, the graph would have re-entered itself and died on
        # LangGraph's recursion limit rather than looping usefully.
        workflow.add_edge("DataRefreshRouter", END)

        return workflow.compile()


_graph = None


def __getattr__(name):
    """
    Build the graph on first access instead of at import (PEP 562).

    Importing this module used to build the entire system as a side effect, and
    it imports the five domain builders -- each of which did the same. So a
    single `import main` constructed ten domain graphs: five when the builder
    modules were imported, five more inside build_graph(). Every one of those
    brings up its own agents, ToolSets and Neo4j/ChromaDB managers, which is a
    large part of why the 512 MB instance ran out of memory.

    Deferring keeps `langgraph.json` (which references `...py:graph`) and
    `from ... import graph` working unchanged, while importers that only want
    the builder class now pay nothing.
    """
    if name == "graph":
        global _graph
        if _graph is None:
            logger.info("Building Combined Agent Graph...")
            _graph = CombinedAgentGraph(GroqLLM().get_llm()).build_graph()
            logger.info("Combined Agent Graph ready")
        return _graph
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
