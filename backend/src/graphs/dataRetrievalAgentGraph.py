"""
dataRetrievalAgentGraph.py - Data Retrieval Agent Graph Builder
"""

from langgraph.graph import StateGraph, END
from src.llms.groqllm import GroqLLM
from src.states.dataRetrievalAgentState import DataRetrievalAgentState
from src.nodes.dataRetrievalAgentNode import DataRetrievalAgentNode


class DataRetrievalAgentGraph(DataRetrievalAgentNode):
    def __init__(self, llm):
        super().__init__(llm)
        self.llm = llm

    def prepare_worker_tasks(self, state: DataRetrievalAgentState) -> dict:
        tasks = state.generated_tasks
        initial_states = [{"generated_tasks": [task]} for task in tasks]
        return {"tasks_for_workers": initial_states}

    def create_worker_graph(self):
        worker_graph_builder = StateGraph(DataRetrievalAgentState)

        worker_graph_builder.add_node("worker_agent", self.worker_agent_node)
        worker_graph_builder.add_node("tool_node", self.tool_node)

        worker_graph_builder.set_entry_point("worker_agent")
        worker_graph_builder.add_edge("worker_agent", "tool_node")
        worker_graph_builder.add_edge("tool_node", END)

        return worker_graph_builder.compile()

    def aggregate_results(self, state: DataRetrievalAgentState) -> dict:
        worker_outputs = getattr(state, "worker", [])
        new_results = []

        if isinstance(worker_outputs, list):
            for output in worker_outputs:
                if "worker_results" in output and output["worker_results"]:
                    new_results.extend(output["worker_results"])

        return {"worker_results": new_results, "latest_worker_results": new_results}

    def format_output(self, state: DataRetrievalAgentState) -> dict:
        classified_events = state.classified_buffer
        insights = []

        for event in classified_events:
            insights.append(
                {
                    "source_event_id": event.event_id,
                    "domain": event.target_agent,
                    "severity": "medium",
                    "summary": event.content_summary,
                    "risk_score": event.confidence_score,
                }
            )

        print(f"[DATA RETRIEVAL] Formatted {len(insights)} insights for parent graph")
        return {"domain_insights": insights}

    def build_data_retrieval_agent_graph(self):
        worker_graph = self.create_worker_graph()
        workflow = StateGraph(DataRetrievalAgentState)

        workflow.add_node("master_delegator", self.master_agent_node)
        workflow.add_node("prepare_worker_tasks", self.prepare_worker_tasks)
        workflow.add_node(
            "worker",
            lambda state: {
                "worker": worker_graph.map().invoke(state.tasks_for_workers)
            },
        )
        workflow.add_node("aggregate_results", self.aggregate_results)
        workflow.add_node("classifier_agent", self.classifier_agent_node)
        workflow.add_node("format_output", self.format_output)

        workflow.set_entry_point("master_delegator")
        workflow.add_edge("master_delegator", "prepare_worker_tasks")
        workflow.add_edge("prepare_worker_tasks", "worker")
        workflow.add_edge("worker", "aggregate_results")
        workflow.add_edge("aggregate_results", "classifier_agent")
        workflow.add_edge("classifier_agent", "format_output")
        workflow.add_edge("format_output", END)

        return workflow.compile()


_graph = None


def __getattr__(name):
    """
    Build the graph on first access instead of at import (PEP 562).

    RogerFullGraph imports this module for its builder class, and building at
    import meant that import constructed a full graph the importer then threw
    away and rebuilt. Deferring keeps `langgraph.json` (which references
    `...py:graph`) working unchanged.
    """
    if name == "graph":
        global _graph
        if _graph is None:
            _graph = DataRetrievalAgentGraph(
                GroqLLM().get_llm()
            ).build_data_retrieval_agent_graph()
        return _graph
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
