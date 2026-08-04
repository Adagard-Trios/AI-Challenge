"""
src/states/combinedAgentState.py
COMPLETE - All original states preserved with proper typing and Reducer
"""

from __future__ import annotations
import operator
from typing import Optional, List, Dict, Any, Annotated, Union
from datetime import datetime
from pydantic import BaseModel, Field


# =============================================================================
# CUSTOM REDUCER (Fixes InvalidUpdateError & Enables Reset)
# =============================================================================
def reduce_insights(existing: List[Dict], new: Union[List[Dict], str]) -> List[Dict]:
    """
    Custom reducer for domain_insights.
    1. If new value is "RESET", clears the list (for continuous loops).
    2. If new value is a list, appends it to existing list (for parallel agents).
    """
    if isinstance(new, str) and new == "RESET":
        return []

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
    route: Optional[str] = Field(
        default=None, description="Router decision: None=END, 'GraphInitiator'=loop"
    )

    class Config:
        arbitrary_types_allowed = True
