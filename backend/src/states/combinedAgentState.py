"""
src/states/combinedAgentState.py
COMPLETE - All original states preserved with proper typing and Reducer
"""

from __future__ import annotations
from typing import Optional, List, Dict, Any, Annotated, Union
from datetime import datetime
from pydantic import BaseModel, Field


# =============================================================================
# CUSTOM REDUCER (Fixes InvalidUpdateError & Enables Reset)
# =============================================================================
def reduce_insights(existing: List[Dict], new: Union[List[Dict], str]) -> List[Dict]:
    """
    Custom reducer for domain_insights: appends, so five agents writing the
    same key in one superstep merge instead of raising InvalidUpdateError.

    There was a "RESET" string sentinel here that cleared the list, sent by
    GraphInitiator at the top of every cycle. It cleared nothing: main.py
    builds a fresh CombinedAgentState per cycle, so the list is already empty
    when that node runs. What it did do was make a field DECLARED as
    List[Dict] sometimes hold a str, which every reader then had to defend
    against.

    The str in the signature stays deliberately. This is a reducer -- it
    receives whatever a node returns -- and silently keeping the existing list
    on an unexpected type is better than a TypeError inside a superstep, where
    the traceback names LangGraph rather than the node at fault.
    """

    # Ensure existing is a list (handles initialization)
    current = existing if isinstance(existing, list) else []

    if isinstance(new, list):
        return current + new

    return current


# =============================================================================
# DATA MODELS
# =============================================================================


class RiskMetrics(BaseModel):
    """
    Quantifiable indicators for the Operational Risk Radar.
    Maps to the dashboard metrics in your project report.
    """

    logistics_friction: float = Field(
        default=0.0, description="Route risk score from mobility data"
    )
    compliance_volatility: float = Field(
        default=0.0, description="Regulatory risk from political data"
    )
    market_instability: float = Field(
        default=0.0, description="Market volatility from economic data"
    )
    opportunity_index: float = Field(
        default=0.0, description="Positive growth signal score"
    )


class CombinedAgentState(BaseModel):
    """
    Main state for the Roger combined graph.
    This is the parent state that receives outputs from all domain agents.

    CRITICAL: All domain agents must write to 'domain_insights' field.
    """

    # ===== INPUT FROM DOMAIN AGENTS =====
    # This is where domain agents write their outputs
    domain_insights: Annotated[List[Dict[str, Any]], reduce_insights] = Field(
        default_factory=list,
        description="Insights from domain agents (Social, Political, Economic, etc.)",
    )

    # ===== AGGREGATED OUTPUTS =====
    # After FeedAggregator processes domain_insights
    final_ranked_feed: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Ranked and deduplicated feed for National Activity Feed",
    )

    # NEW: Categorized feeds organized by domain for frontend sections
    categorized_feeds: Dict[str, List[Dict[str, Any]]] = Field(
        default_factory=lambda: {
            "political": [],
            "economical": [],
            "social": [],
            "meteorological": [],
            "intelligence": [],
        },
        description="Feeds organized by domain category for frontend display",
    )

    # Dashboard snapshot for Operational Risk Radar
    risk_dashboard_snapshot: Dict[str, Any] = Field(
        default_factory=lambda: {
            "logistics_friction": 0.0,
            "compliance_volatility": 0.0,
            "market_instability": 0.0,
            "opportunity_index": 0.0,
            "avg_confidence": 0.0,
            "high_priority_count": 0,
            "total_events": 0,
            "last_updated": "",
        },
        description="Real-time risk and opportunity metrics dashboard",
    )

    # ===== EXECUTION CONTROL =====
    # Loop control to prevent infinite recursion
    run_count: int = Field(
        default=0, description="Number of times graph has executed (safety counter)"
    )

    max_runs: int = Field(default=5, description="Maximum allowed loop iterations")

    last_run_ts: Optional[datetime] = Field(
        default=None, description="Timestamp of last execution"
    )

    # ===== ROUTING CONTROL =====
    # CRITICAL: Used by DataRefreshRouter for conditional edges
    # Must be Optional[str] - None means END, "GraphInitiator" means loop
    # No `route` field.
    #
    # It held a router decision -- None=END, 'GraphInitiator'=loop -- for a
    # conditional edge that was removed because the "loop" branch could never
    # be selected, and would have re-entered the graph into LangGraph's
    # recursion limit if it had been. The 60-second cadence is driven by
    # main.py's run_graph_loop, outside the graph entirely.

    class Config:
        arbitrary_types_allowed = True
