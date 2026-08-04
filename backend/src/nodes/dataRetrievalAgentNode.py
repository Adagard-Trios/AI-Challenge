"""
src/nodes/dataRetrievalAgentNode.py
COMPLETE - Data Retrieval Agent Node Implementation
Handles orchestrator-worker pattern for scraping tasks

Updated: Uses Tool Factory pattern for parallel execution safety.
Each agent instance gets its own private set of tools.
"""

import json
import uuid
from typing import List
from langchain_core.messages import HumanMessage, SystemMessage
from src.states.dataRetrievalAgentState import (
    DataRetrievalAgentState,
    ScrapingTask,
    RawScrapedData,
    ClassifiedEvent,
)
from src.utils.tool_factory import create_tool_set


class DataRetrievalAgentNode:
    """
    Implements the Data Retrieval Agent workflow:
    1. Master Agent - Plans scraping tasks
    2. Worker Agent - Executes individual tasks
    3. Tool Node - Runs the actual tools
    4. Classifier Agent - Categorizes results for domain agents

    Thread Safety:
        Each DataRetrievalAgentNode instance creates its own private ToolSet,
        enabling safe parallel execution with other agents.
    """

    def __init__(self, llm):
        """Initialize with LLM and private tool set"""
        # Create PRIVATE tool instances for this agent
        self.tools = create_tool_set()
        self.llm = llm

    # =========================================================================
    # 1. MASTER AGENT (TASK DELEGATOR)
    # =========================================================================

    def master_agent_node(self, state: DataRetrievalAgentState):
        """
        TASK DELEGATOR MASTER AGENT

        Decides which scraping tools to run based on:
        - Previously completed tasks (avoid redundancy)
        - Current monitoring needs
        - Keywords of interest

        Returns: List[ScrapingTask]
        """
        print("=== [MASTER AGENT] Planning Scraping Tasks ===")

        completed_tools = [r.source_tool for r in state.worker_results]

        system_prompt = f"""
You are the Master Data Retrieval Agent for Roger - Sri Lanka's situational awareness platform.

AVAILABLE TOOLS: {list(self.tools.as_dict().keys())}

Your job:
1. Decide which tools to run to keep the system updated
2. Avoid re-running tools just executed: {completed_tools}
3. Prioritize a mix of:
   - Official sources: scrape_government_gazette, scrape_parliament_minutes, scrape_train_schedule
   - Market data: scrape_cse_stock_data, scrape_local_news
   - Social media: scrape_reddit, scrape_twitter, scrape_facebook

Focus on Sri Lankan context with keywords like:
- "election", "policy", "budget", "strike", "inflation"
- "fuel", "railway", "protest", "flood", "gazette"

Previously planned: {state.previous_tasks}

Respond with valid JSON array:
[
  {{
    "tool_name": "<tool_name>",
    "parameters": {{"keywords": [...]}},
    "priority": "high" | "normal"
  }},
  ...
]

If no tasks needed, return []
"""

        parsed_tasks: List[ScrapingTask] = []

        try:
            response = self.llm.invoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(
                        content="Plan the next scraping wave for Sri Lankan situational awareness."
                    ),
                ]
            )

            raw = response.content
            suggested = json.loads(raw)

            if isinstance(suggested, dict):
                suggested = [suggested]

            for item in suggested:
                try:
                    task = ScrapingTask(**item)
                    parsed_tasks.append(task)
                except Exception as e:
                    print(f"[MASTER] Failed to parse task: {e}")
                    continue

        except Exception as e:
            print(f"[MASTER] LLM planning failed: {e}, using fallback plan")

        # Fallback plan if LLM fails
        if not parsed_tasks and not state.previous_tasks:
            parsed_tasks = [
                ScrapingTask(
                    tool_name="scrape_local_news",
                    parameters={"keywords": ["Sri Lanka", "economy", "politics"]},
                    priority="high",
                ),
                ScrapingTask(
                    tool_name="scrape_cse_stock_data",
                    parameters={"symbol": "ASPI"},
                    priority="high",
                ),
                ScrapingTask(
                    tool_name="scrape_government_gazette",
                    parameters={"keywords": ["tax", "import", "regulation"]},
                    priority="normal",
                ),
                ScrapingTask(
                    tool_name="scrape_reddit",
                    parameters={"keywords": ["Sri Lanka"], "limit": 20},
                    priority="normal",
                ),
            ]

        print(f"[MASTER] Planned {len(parsed_tasks)} tasks")

        return {
            "generated_tasks": parsed_tasks,
            "previous_tasks": [t.tool_name for t in parsed_tasks],
        }

    # =========================================================================
    # 2. WORKER AGENT
    # =========================================================================

    def worker_agent_node(self, state: DataRetrievalAgentState):
        """
        DATA RETRIEVAL WORKER AGENT

        Pops next task from queue and prepares it for ToolNode execution.
        This runs in parallel via map() in the graph.
        """
        if not state.generated_tasks:
            print("[WORKER] No tasks in queue")
            return {}

        # Pop first task (FIFO)
        current_task = state.generated_tasks[0]
        remaining = state.generated_tasks[1:]

        print(f"[WORKER] Dispatching -> {current_task.tool_name}")

        return {"generated_tasks": remaining, "current_task": current_task}

    # =========================================================================
    # 3. TOOL NODE
    # =========================================================================

    def tool_node(self, state: DataRetrievalAgentState):
        """
        TOOL NODE

        Executes the actual scraping tool specified by current_task.
        Handles errors gracefully and records results.
        """
        current_task = state.current_task
        if current_task is None:
            print("[TOOL NODE] No active task")
            return {}

        print(f"[TOOL NODE] Executing -> {current_task.tool_name}")

        tool_func = self.tools.get(current_task.tool_name)

        if tool_func is None:
            output = f"Tool '{current_task.tool_name}' not found in registry"
            status = "failed"
        else:
            try:
                # Invoke LangChain tool with parameters
                output = tool_func.invoke(current_task.parameters or {})
                status = "success"
                print("[TOOL NODE] ✓ Success")
            except Exception as e:
                output = f"Error: {str(e)}"
                status = "failed"
                print(f"[TOOL NODE] ✗ Failed: {e}")

        result = RawScrapedData(
            source_tool=current_task.tool_name, raw_content=str(output), status=status
        )

        return {"current_task": None, "worker_results": [result]}

    # =========================================================================
    # 4. CLASSIFIER AGENT
    # =========================================================================

    def classifier_agent_node(self, state: DataRetrievalAgentState):
        """
        DATA CLASSIFIER AGENT

        Analyzes scraped data and routes it to appropriate domain agents.
        Creates ClassifiedEvent objects with summaries and target agents.
        """
        if not state.latest_worker_results:
            print("[CLASSIFIER] No new results to process")
            return {}

        print(f"[CLASSIFIER] Processing {len(state.latest_worker_results)} results")

        agent_categories = [
            "social",
            "economical",
            "political",
            "mobility",
            "weather",
            "intelligence",
        ]

        system_prompt = """
You are a data classification expert for Roger.

AVAILABLE AGENTS:
- social: Social media sentiment, public discussions
- economical: Stock market, economic indicators, CSE data
- political: Government gazette, parliament, regulations
- mobility: Transportation, train schedules, logistics
- weather: Meteorological data, disaster alerts
- intelligence: Brand monitoring, entity tracking

Task: Analyze the scraped data and:
1. Write a one-sentence summary
2. Choose the most appropriate agent

Respond with JSON:
{
  "summary": "<brief summary>",
  "target_agent": "<agent_name>"
}
"""

        all_classified: List[ClassifiedEvent] = []

        for result in state.latest_worker_results:
            try:
                response = self.llm.invoke(
                    [
                        SystemMessage(content=system_prompt),
                        HumanMessage(
                            content=f"Source: {result.source_tool}\n\nData:\n{result.raw_content[:2000]}"
                        ),
                    ]
                )

                result_json = json.loads(response.content)
                summary = result_json.get("summary", "No summary")
                target = result_json.get("target_agent", "social")

                if target not in agent_categories:
                    target = "social"

            except Exception as e:
                print(f"[CLASSIFIER] LLM failed: {e}, using rule-based classification")

                # Fallback rule-based classification
                source = result.source_tool.lower()
                if "stock" in source or "cse" in source:
                    target = "economical"
                elif "gazette" in source or "parliament" in source:
                    target = "political"
                elif "train" in source or "schedule" in source:
                    target = "mobility"
                elif any(s in source for s in ["reddit", "twitter", "facebook"]):
                    target = "social"
                else:
                    target = "social"

                summary = (
                    f"Data from {result.source_tool}: {result.raw_content[:150]}..."
                )

            classified = ClassifiedEvent(
                event_id=str(uuid.uuid4()),
                content_summary=summary,
                target_agent=target,
                confidence_score=0.85,
            )
            all_classified.append(classified)

        print(f"[CLASSIFIER] Classified {len(all_classified)} events")

        return {"classified_buffer": all_classified, "latest_worker_results": []}
