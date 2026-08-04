"""
RogerGraph.py - Main Roger Graph with Fan-Out/Fan-In Architecture
"""

from __future__ import annotations
import logging
from langgraph.graph import StateGraph, START, END

from src.states.combinedAgentState import CombinedAgentState
from src.nodes.combinedAgentNode import CombinedAgentNode
from src.graphs.dataRetrievalAgentGraph import DataRetrievalAgentGraph
from src.graphs.meteorologicalAgentGraph import MeteorologicalGraphBuilder
from src.graphs.politicalAgentGraph import PoliticalGraphBuilder
from src.graphs.economicalAgentGraph import EconomicalGraphBuilder
from src.graphs.intelligenceAgentGraph import IntelligenceGraphBuilder
from src.graphs.socialAgentGraph import SocialGraphBuilder
from src.llms.groqllm import GroqLLM

logger = logging.getLogger("Roger_graph")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(ch)


class CombinedAgentGraphBuilder:
    def __init__(self, llm):
        self.llm = llm

    def build_graph(self):
        logger.info("Building Roger Combined Agent Graph")

        social_builder = SocialGraphBuilder(self.llm)
        intelligence_builder = IntelligenceGraphBuilder(self.llm)
        economical_builder = EconomicalGraphBuilder(self.llm)
        political_builder = PoliticalGraphBuilder(self.llm)
        meteorological_builder = MeteorologicalGraphBuilder(self.llm)
        data_retrieval_builder = DataRetrievalAgentGraph(self.llm)

        orchestrator = CombinedAgentNode(self.llm)
        workflow = StateGraph(CombinedAgentState)

        workflow.add_node("GraphInitiator", orchestrator.graph_initiator)
        workflow.add_node("FeedAggregatorAgent", orchestrator.feed_aggregator_agent)
        workflow.add_node("DataRefresherAgent", orchestrator.data_refresher_agent)
        workflow.add_node("DataRefreshRouter", orchestrator.data_refresh_router)

        workflow.add_node("SocialAgent", social_builder.build_graph())
        workflow.add_node("IntelligenceAgent", intelligence_builder.build_graph())
        workflow.add_node("EconomicalAgent", economical_builder.build_graph())
        workflow.add_node("PoliticalAgent", political_builder.build_graph())
        workflow.add_node("MeteorologicalAgent", meteorological_builder.build_graph())
        workflow.add_node(
            "DataRetrievalAgent",
            data_retrieval_builder.build_data_retrieval_agent_graph(),
        )

        workflow.add_edge(START, "GraphInitiator")

        domain_agents = [
            "SocialAgent",
            "IntelligenceAgent",
            "EconomicalAgent",
            "PoliticalAgent",
            "MeteorologicalAgent",
            "DataRetrievalAgent",
        ]

        for agent in domain_agents:
            workflow.add_edge("GraphInitiator", agent)

        for agent in domain_agents:
            workflow.add_edge(agent, "FeedAggregatorAgent")

        workflow.add_edge("FeedAggregatorAgent", "DataRefresherAgent")
        workflow.add_edge("DataRefresherAgent", "DataRefreshRouter")

        def route_decision(state):
            route = getattr(state, "route", [])
            if route is None or route == "":
                return END
            if route == "GraphInitiator":
                return "GraphInitiator"
            return END

        workflow.add_conditional_edges(
            "DataRefreshRouter",
            route_decision,
            {"GraphInitiator": "GraphInitiator", END: END},
        )

        graph = workflow.compile()
        logger.info("Roger Graph compiled successfully")
        return graph


llm = GroqLLM().get_llm()
builder = CombinedAgentGraphBuilder(llm)
graph = builder.build_graph()
