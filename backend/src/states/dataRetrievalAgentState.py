"""
src/states/dataRetrievalAgentState.py
Data Retrieval Agent State - handles scraping tasks
"""

import operator
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field
from typing_extensions import Literal


class ScrapingTask(BaseModel):
    """Instruction from Master Agent to Worker."""

    tool_name: Literal[
        "scrape_linkedin",
        "scrape_instagram",
        "scrape_facebook",
        "scrape_reddit",
        "scrape_twitter",
        "scrape_government_gazette",
        "scrape_parliament_minutes",
        "scrape_train_schedule",
        "scrape_cse_stock_data",
        "scrape_local_news",
    ]
    parameters: Dict[str, Any] = Field(default_factory=dict)
    priority: Literal["high", "normal"] = "normal"


class RawScrapedData(BaseModel):
    """Output from a Worker's tool execution."""

    source_tool: str
    raw_content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    status: Literal["success", "failed"]


class ClassifiedEvent(BaseModel):
    """Final output after classification."""

    event_id: str
    content_summary: str
    target_agent: str
    confidence_score: float
    # ADDED: To align with "Risk & Opportunity" requirement
    severity: Literal["low", "medium", "high", "critical"] = "low"
    impact_type: Literal["risk", "opportunity"] = "risk"


class DataRetrievalAgentState(BaseModel):
    """
    State for the Data Retrieval Agent (Orchestrator-Worker pattern).
    """

    # Task queue
    generated_tasks: List[ScrapingTask] = Field(default_factory=list)
    current_task: Optional[ScrapingTask] = None

    # Worker execution
    tasks_for_workers: List[Dict[str, Any]] = Field(default_factory=list)
    worker: Any = None  # Holds worker graph outputs

    # Results
    worker_results: List[RawScrapedData] = Field(default_factory=list)
    latest_worker_results: List[RawScrapedData] = Field(default_factory=list)

    # Classified outputs
    classified_buffer: List[ClassifiedEvent] = Field(default_factory=list)

    # History tracking
    previous_tasks: List[str] = Field(default_factory=list)

    # ===== INTEGRATION WITH PARENT GRAPH =====
    # CRITICAL: This is how data flows to CombinedAgentState
    domain_insights: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Output formatted for parent graph FeedAggregator",
    )

    class Config:
        arbitrary_types_allowed = True
