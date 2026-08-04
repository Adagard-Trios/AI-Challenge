"""
meteorologicalAgentGraph.py - Meteorological Agent Graph with Subgraph Architecture
"""

import uuid
from langgraph.graph import StateGraph, END
from src.states.meteorologicalAgentState import MeteorologicalAgentState
from src.nodes.meteorologicalAgentNode import MeteorologicalAgentNode
from src.llms.groqllm import GroqLLM


class MeteorologicalGraphBuilder:
    def __init__(self, llm):
        self.llm = llm

    def build_official_sources_subgraph(
        self, node: MeteorologicalAgentNode
    ) -> StateGraph:
        subgraph = StateGraph(MeteorologicalAgentState)
        subgraph.add_node("collect_official", node.collect_official_sources)
        subgraph.set_entry_point("collect_official")
        subgraph.add_edge("collect_official", END)
        return subgraph.compile()

    def build_social_media_subgraph(self, node: MeteorologicalAgentNode) -> StateGraph:
        subgraph = StateGraph(MeteorologicalAgentState)

        subgraph.add_node("national_social", node.collect_national_social_media)
        subgraph.add_node("district_social", node.collect_district_social_media)
        subgraph.add_node("climate_alerts", node.collect_climate_alerts)

        subgraph.set_entry_point("national_social")
        subgraph.set_entry_point("district_social")
        subgraph.set_entry_point("climate_alerts")

        subgraph.add_edge("national_social", END)
        subgraph.add_edge("district_social", END)
        subgraph.add_edge("climate_alerts", END)

        return subgraph.compile()

    def build_feed_generation_subgraph(
        self, node: MeteorologicalAgentNode
    ) -> StateGraph:
        subgraph = StateGraph(MeteorologicalAgentState)

        subgraph.add_node("categorize", node.categorize_by_geography)
        subgraph.add_node("llm_summary", node.generate_llm_summary)
        subgraph.add_node("format_output", node.format_final_output)

        subgraph.set_entry_point("categorize")
        subgraph.add_edge("categorize", "llm_summary")
        subgraph.add_edge("llm_summary", "format_output")
        subgraph.add_edge("format_output", END)

        return subgraph.compile()

    def build_graph(self):
        node = MeteorologicalAgentNode(self.llm)

        official_subgraph = self.build_official_sources_subgraph(node)
        social_subgraph = self.build_social_media_subgraph(node)
        feed_subgraph = self.build_feed_generation_subgraph(node)

        main_graph = StateGraph(MeteorologicalAgentState)

        main_graph.add_node(
            "official_sources_module", lambda state: official_subgraph.invoke(state)
        )
        main_graph.add_node(
            "social_media_module", lambda state: social_subgraph.invoke(state)
        )
        main_graph.add_node(
            "feed_generation_module", lambda state: feed_subgraph.invoke(state)
        )
        main_graph.add_node("feed_aggregator", node.aggregate_and_store_feeds)

        main_graph.set_entry_point("official_sources_module")
        main_graph.set_entry_point("social_media_module")

        main_graph.add_edge("official_sources_module", "feed_generation_module")
        main_graph.add_edge("social_media_module", "feed_generation_module")
        main_graph.add_edge("feed_generation_module", "feed_aggregator")
        main_graph.add_edge("feed_aggregator", END)

        return main_graph.compile()


llm = GroqLLM().get_llm()
graph = MeteorologicalGraphBuilder(llm).build_graph()
