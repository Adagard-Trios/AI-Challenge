"""
intelligenceAgentGraph.py - Intelligence Agent Graph with Subgraph Architecture
"""

from langgraph.graph import StateGraph, END
from src.states.intelligenceAgentState import IntelligenceAgentState
from src.nodes.intelligenceAgentNode import IntelligenceAgentNode
from src.llms.groqllm import GroqLLM
from .subgraph_runner import subgraph_node


class IntelligenceGraphBuilder:
    def __init__(self, llm):
        self.llm = llm

    def build_profile_monitoring_subgraph(
        self, node: IntelligenceAgentNode
    ) -> StateGraph:
        subgraph = StateGraph(IntelligenceAgentState)
        subgraph.add_node("monitor_profiles", node.collect_profile_activity)
        subgraph.set_entry_point("monitor_profiles")
        subgraph.add_edge("monitor_profiles", END)
        return subgraph.compile()

    def build_competitive_intelligence_subgraph(
        self, node: IntelligenceAgentNode
    ) -> StateGraph:
        subgraph = StateGraph(IntelligenceAgentState)

        subgraph.add_node("competitor_mentions", node.collect_competitor_mentions)
        subgraph.add_node("product_reviews", node.collect_product_reviews)
        subgraph.add_node("market_intelligence", node.collect_market_intelligence)

        subgraph.set_entry_point("competitor_mentions")
        subgraph.set_entry_point("product_reviews")
        subgraph.set_entry_point("market_intelligence")

        subgraph.add_edge("competitor_mentions", END)
        subgraph.add_edge("product_reviews", END)
        subgraph.add_edge("market_intelligence", END)

        return subgraph.compile()

    def build_feed_generation_subgraph(self, node: IntelligenceAgentNode) -> StateGraph:
        subgraph = StateGraph(IntelligenceAgentState)

        subgraph.add_node("categorize", node.categorize_intelligence)
        subgraph.add_node("llm_summary", node.generate_llm_summary)
        subgraph.add_node("format_output", node.format_final_output)

        subgraph.set_entry_point("categorize")
        subgraph.add_edge("categorize", "llm_summary")
        subgraph.add_edge("llm_summary", "format_output")
        subgraph.add_edge("format_output", END)

        return subgraph.compile()

    def build_graph(self):
        node = IntelligenceAgentNode(self.llm)

        profile_subgraph = self.build_profile_monitoring_subgraph(node)
        intelligence_subgraph = self.build_competitive_intelligence_subgraph(node)
        feed_subgraph = self.build_feed_generation_subgraph(node)

        main_graph = StateGraph(IntelligenceAgentState)

        main_graph.add_node(
            "profile_monitoring_module", subgraph_node(profile_subgraph, "profile")
        )
        main_graph.add_node(
            "competitive_intelligence_module",
            subgraph_node(intelligence_subgraph, "intelligence"),
        )
        main_graph.add_node(
            "feed_generation_module", subgraph_node(feed_subgraph, "feed")
        )
        main_graph.add_node("feed_aggregator", node.aggregate_and_store_feeds)

        main_graph.set_entry_point("profile_monitoring_module")
        main_graph.set_entry_point("competitive_intelligence_module")

        main_graph.add_edge("profile_monitoring_module", "feed_generation_module")
        main_graph.add_edge("competitive_intelligence_module", "feed_generation_module")
        main_graph.add_edge("feed_generation_module", "feed_aggregator")
        main_graph.add_edge("feed_aggregator", END)

        return main_graph.compile()

_graph = None


def __getattr__(name):
    """
    Build the graph on first access instead of at import (PEP 562).

    This module is imported for its builder class by both orchestrators, and
    building at import meant every such import constructed a full graph -- with
    its agents, ToolSet and Neo4j/ChromaDB managers -- that the importer then
    threw away and rebuilt. Deferring keeps `langgraph.json` (which references
    `...py:graph`) working unchanged.
    """
    if name == "graph":
        global _graph
        if _graph is None:
            _graph = IntelligenceGraphBuilder(GroqLLM().get_llm()).build_graph()
        return _graph
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
