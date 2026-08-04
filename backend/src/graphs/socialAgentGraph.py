"""
socialAgentGraph.py - Social Agent Graph with Subgraph Architecture
"""

import uuid
from langgraph.graph import StateGraph, END
from src.states.socialAgentState import SocialAgentState
from src.nodes.socialAgentNode import SocialAgentNode
from src.llms.groqllm import GroqLLM


class SocialGraphBuilder:
    def __init__(self, llm):
        self.llm = llm

    def build_trending_subgraph(self, node: SocialAgentNode) -> StateGraph:
        subgraph = StateGraph(SocialAgentState)
        subgraph.add_node("collect_trends", node.collect_sri_lanka_trends)
        subgraph.set_entry_point("collect_trends")
        subgraph.add_edge("collect_trends", END)
        return subgraph.compile()

    def build_social_media_subgraph(self, node: SocialAgentNode) -> StateGraph:
        subgraph = StateGraph(SocialAgentState)

        subgraph.add_node("sri_lanka_social", node.collect_sri_lanka_social_media)
        subgraph.add_node("asia_social", node.collect_asia_social_media)
        subgraph.add_node("world_social", node.collect_world_social_media)

        subgraph.set_entry_point("sri_lanka_social")
        subgraph.set_entry_point("asia_social")
        subgraph.set_entry_point("world_social")

        subgraph.add_edge("sri_lanka_social", END)
        subgraph.add_edge("asia_social", END)
        subgraph.add_edge("world_social", END)

        return subgraph.compile()

    def build_feed_generation_subgraph(self, node: SocialAgentNode) -> StateGraph:
        subgraph = StateGraph(SocialAgentState)

        subgraph.add_node("categorize", node.categorize_by_geography)
        subgraph.add_node("llm_summary", node.generate_llm_summary)
        subgraph.add_node("format_output", node.format_final_output)

        subgraph.set_entry_point("categorize")
        subgraph.add_edge("categorize", "llm_summary")
        subgraph.add_edge("llm_summary", "format_output")
        subgraph.add_edge("format_output", END)

        return subgraph.compile()

    def build_user_targets_subgraph(self, node: SocialAgentNode) -> StateGraph:
        """Build subgraph for user-defined keywords and profiles."""
        subgraph = StateGraph(SocialAgentState)
        subgraph.add_node("collect_user_targets", node.collect_user_defined_targets)
        subgraph.set_entry_point("collect_user_targets")
        subgraph.add_edge("collect_user_targets", END)
        return subgraph.compile()

    def build_graph(self):
        node = SocialAgentNode(self.llm)

        trending_subgraph = self.build_trending_subgraph(node)
        social_subgraph = self.build_social_media_subgraph(node)
        user_targets_subgraph = self.build_user_targets_subgraph(node)
        feed_subgraph = self.build_feed_generation_subgraph(node)

        main_graph = StateGraph(SocialAgentState)

        main_graph.add_node(
            "trending_module", lambda state: trending_subgraph.invoke(state)
        )
        main_graph.add_node(
            "social_media_module", lambda state: social_subgraph.invoke(state)
        )
        main_graph.add_node(
            "user_targets_module", lambda state: user_targets_subgraph.invoke(state)
        )
        main_graph.add_node(
            "feed_generation_module", lambda state: feed_subgraph.invoke(state)
        )
        main_graph.add_node("feed_aggregator", node.aggregate_and_store_feeds)

        # Parallel entry points - all 3 modules start together
        main_graph.set_entry_point("trending_module")
        main_graph.set_entry_point("social_media_module")
        main_graph.set_entry_point("user_targets_module")

        # All modules converge to feed generation
        main_graph.add_edge("trending_module", "feed_generation_module")
        main_graph.add_edge("social_media_module", "feed_generation_module")
        main_graph.add_edge("user_targets_module", "feed_generation_module")
        main_graph.add_edge("feed_generation_module", "feed_aggregator")
        main_graph.add_edge("feed_aggregator", END)

        return main_graph.compile()


llm = GroqLLM().get_llm()
graph = SocialGraphBuilder(llm).build_graph()
