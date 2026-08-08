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

    @staticmethod
    def _controller_is_collecting() -> bool:
        """
        Whether the blackboard controller has taken over collection.

        When it has, the five closures below must stand down or everything is
        collected TWICE -- twice the scraping against one social account,
        twice the LLM spend against a per-minute limit this project already
        hits. The two cannot both run.

        Read per cycle rather than captured at build time, so switching back to
        the fan-out is an env var and a restart rather than a redeploy. Shadow
        is the default; see src/blackboard/controller.py for why.
        """
        try:
            from src.blackboard.controller import mode

            return mode() == "active"
        except Exception:  # noqa: BLE001
            # Cannot tell -- keep collecting. An unreadable flag must not stop
            # the pipeline that works today.
            return False

    def build_graph(self):
        social_graph = SocialGraphBuilder(self.llm).build_graph()
        intelligence_graph = IntelligenceGraphBuilder(self.llm).build_graph()
        economical_graph = EconomicalGraphBuilder(self.llm).build_graph()
        political_graph = PoliticalGraphBuilder(self.llm).build_graph()
        meteorological_graph = MeteorologicalGraphBuilder(self.llm).build_graph()

        def run_social_agent(state: CombinedAgentState) -> Dict[str, Any]:
            if self._controller_is_collecting():
                logger.info(
                    "[CombinedGraph] SocialAgent standing down; the blackboard "
                    "controller is collecting"
                )
                return {"domain_insights": []}
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
            if self._controller_is_collecting():
                logger.info(
                    "[CombinedGraph] IntelligenceAgent standing down; the blackboard "
                    "controller is collecting"
                )
                return {"domain_insights": []}
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
            if self._controller_is_collecting():
                logger.info(
                    "[CombinedGraph] EconomicalAgent standing down; the blackboard "
                    "controller is collecting"
                )
                return {"domain_insights": []}
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
            if self._controller_is_collecting():
                logger.info(
                    "[CombinedGraph] PoliticalAgent standing down; the blackboard "
                    "controller is collecting"
                )
                return {"domain_insights": []}
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
            if self._controller_is_collecting():
                logger.info(
                    "[CombinedGraph] MeteorologicalAgent standing down; the blackboard "
                    "controller is collecting"
                )
                return {"domain_insights": []}
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

        # Straight to END.
        #
        # There was a DataRefreshRouter node here whose entire body returned
        # {"route": "END"} unconditionally and whose only edge went to END. It
        # was the remains of a conditional edge with a "GraphInitiator" branch
        # that nothing could select -- and had anything selected it, the graph
        # would have re-entered itself and died on LangGraph's recursion limit
        # rather than looping usefully.
        #
        # The 60-second cadence is driven externally by main.py's
        # run_graph_loop, so nothing inside the graph needs to decide whether
        # to continue. A node that always returns the same answer is not a
        # decision; it is a comment with a scheduling cost.
        workflow.add_edge("DataRefresherAgent", END)

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
