"""
intelligenceAgentGraph.py - Intelligence Agent Graph with Subgraph Architecture
"""

import uuid
from langgraph.graph import StateGraph, END
from src.states.intelligenceAgentState import IntelligenceAgentState
from src.nodes.intelligenceAgentNode import IntelligenceAgentNode
from src.llms.groqllm import GroqLLM


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
            "profile_monitoring_module", lambda state: profile_subgraph.invoke(state)
        )
        main_graph.add_node(
            "competitive_intelligence_module",
            lambda state: intelligence_subgraph.invoke(state),
        )
        main_graph.add_node(
            "feed_generation_module", lambda state: feed_subgraph.invoke(state)
        )
        main_graph.add_node("feed_aggregator", node.aggregate_and_store_feeds)

        main_graph.set_entry_point("profile_monitoring_module")
        main_graph.set_entry_point("competitive_intelligence_module")

        main_graph.add_edge("profile_monitoring_module", "feed_generation_module")
        main_graph.add_edge("competitive_intelligence_module", "feed_generation_module")
        main_graph.add_edge("feed_generation_module", "feed_aggregator")
        main_graph.add_edge("feed_aggregator", END)

        return main_graph.compile()


llm = GroqLLM().get_llm()
graph = IntelligenceGraphBuilder(llm).build_graph()
