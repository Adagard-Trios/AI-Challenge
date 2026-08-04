"""
combinedAgentGraph.py - Main entry point for the Combined Agent System.
"""

from __future__ import annotations
from typing import Dict, Any
import logging
from datetime import datetime

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


class CombinedAgentGraphBuilder:
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

        workflow.add_conditional_edges(
            "DataRefreshRouter",
            lambda x: x.route if x.route else "END",
            {"GraphInitiator": "GraphInitiator", "END": END},
        )

        return workflow.compile()


print("Building Combined Agent Graph...")
llm = GroqLLM().get_llm()
builder = CombinedAgentGraphBuilder(llm)
graph = builder.build_graph()
print("Combined Graph ready")
