"""
politicalAgentGraph.py - Political Agent Graph with Subgraph Architecture
"""

from langgraph.graph import StateGraph, END
from src.states.politicalAgentState import PoliticalAgentState
from src.nodes.politicalAgentNode import PoliticalAgentNode
from src.llms.groqllm import GroqLLM
from .subgraph_runner import subgraph_node


class PoliticalGraphBuilder:
    def __init__(self, llm):
        self.llm = llm

    def build_official_sources_subgraph(self, node: PoliticalAgentNode) -> StateGraph:
        subgraph = StateGraph(PoliticalAgentState)
        subgraph.add_node("collect_official", node.collect_official_sources)
        subgraph.set_entry_point("collect_official")
        subgraph.add_edge("collect_official", END)
        return subgraph.compile()

    def build_social_media_subgraph(self, node: PoliticalAgentNode) -> StateGraph:
        subgraph = StateGraph(PoliticalAgentState)
        subgraph.add_node("national_social", node.collect_national_social_media)
        subgraph.add_node("district_social", node.collect_district_social_media)
        subgraph.add_node("world_politics", node.collect_world_politics)

        subgraph.set_entry_point("national_social")
        subgraph.set_entry_point("district_social")
        subgraph.set_entry_point("world_politics")

        subgraph.add_edge("national_social", END)
        subgraph.add_edge("district_social", END)
        subgraph.add_edge("world_politics", END)

        return subgraph.compile()

    def build_feed_generation_subgraph(self, node: PoliticalAgentNode) -> StateGraph:
        subgraph = StateGraph(PoliticalAgentState)

        subgraph.add_node("categorize", node.categorize_by_geography)
        subgraph.add_node("llm_summary", node.generate_llm_summary)
        subgraph.add_node("format_output", node.format_final_output)

        subgraph.set_entry_point("categorize")
        subgraph.add_edge("categorize", "llm_summary")
        subgraph.add_edge("llm_summary", "format_output")
        subgraph.add_edge("format_output", END)

        return subgraph.compile()

    def build_graph(self):
        node = PoliticalAgentNode(self.llm)

        official_subgraph = self.build_official_sources_subgraph(node)
        social_subgraph = self.build_social_media_subgraph(node)
        feed_subgraph = self.build_feed_generation_subgraph(node)

        main_graph = StateGraph(PoliticalAgentState)

        main_graph.add_node(
            "official_sources_module", subgraph_node(official_subgraph, "official")
        )
        main_graph.add_node(
            "social_media_module", subgraph_node(social_subgraph, "social")
        )
        main_graph.add_node(
            "feed_generation_module", subgraph_node(feed_subgraph, "feed")
        )
        main_graph.add_node("feed_aggregator", node.aggregate_and_store_feeds)

        main_graph.set_entry_point("official_sources_module")
        main_graph.set_entry_point("social_media_module")

        main_graph.add_edge("official_sources_module", "feed_generation_module")
        main_graph.add_edge("social_media_module", "feed_generation_module")
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
            _graph = PoliticalGraphBuilder(GroqLLM().get_llm()).build_graph()
        return _graph
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
