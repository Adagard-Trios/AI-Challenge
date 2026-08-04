"""
src/states/politicalAgentState.py
Political Agent State - handles government gazette, parliament minutes, social media
FIXED: Added custom reducer for domain_insights to prevent InvalidUpdateError
"""

import operator
from typing import Optional, List, Dict, Any, Union
from typing_extensions import TypedDict, Annotated


# ============================================================================
# CUSTOM REDUCER (Fixes InvalidUpdateError for parallel node updates)
# ============================================================================
def reduce_domain_insights(
    existing: List[Dict], new: Union[List[Dict], str]
) -> List[Dict]:
    """Custom reducer for domain_insights to handle concurrent updates"""
    if isinstance(new, str) and new == "RESET":
        return []
    current = existing if isinstance(existing, list) else []
    if isinstance(new, list):
        return current + new
    return current


class PoliticalAgentState(TypedDict, total=False):
    """
    State for Political Agent.
    Monitors regulatory changes, policy updates, government announcements, social media.
    """

    # ===== ORCHESTRATOR/WORKER BOOKKEEPING =====
    generated_tasks: List[Dict[str, Any]]
    current_task: Optional[Dict[str, Any]]
    tasks_for_workers: List[Dict[str, Any]]
    worker: Optional[List[Dict[str, Any]]]

    # ===== TOOL RESULTS =====
    worker_results: Annotated[List[Dict[str, Any]], operator.add]
    latest_worker_results: List[Dict[str, Any]]

    # ===== CHANGE DETECTION =====
    last_alerts_hash: Optional[int]
    change_detected: bool

    # ===== SOCIAL MEDIA MONITORING =====
    social_media_results: Annotated[List[Dict[str, Any]], operator.add]

    # ===== STRUCTURED FEED OUTPUT =====
    district_feeds: Dict[str, List[Dict[str, Any]]]  # {district: [posts]}
    national_feed: List[Dict[str, Any]]  # Overall Sri Lanka
    world_feed: List[Dict[str, Any]]  # World politics affecting SL

    # ===== LLM PROCESSING =====
    llm_summary: Optional[str]
    structured_output: Dict[str, Any]  # Final formatted output

    # ===== FEED OUTPUT =====
    final_feed: str
    feed_history: Annotated[List[str], operator.add]

    # ===== INTEGRATION WITH PARENT GRAPH =====
    domain_insights: Annotated[List[Dict[str, Any]], reduce_domain_insights]

    # ===== FEED AGGREGATOR =====
    aggregator_stats: Dict[str, Any]
    dataset_path: str
