"""
src/nodes/combinedAgentNode.py
COMPLETE IMPLEMENTATION - Orchestration nodes for Roger Mother Graph
Implements: GraphInitiator, FeedAggregator, DataRefresher, DataRefreshRouter
UPDATED: Supports 'Opportunity' tracking and new Scoring Logic
"""

from __future__ import annotations
import uuid
import logging
import time
from datetime import datetime
from typing import Dict, Any, List

# Import storage manager for production-grade persistence
from src.storage.storage_manager import StorageManager

# Import trending detector for velocity metrics
try:
    from src.utils.trending_detector import get_trending_detector, record_topic_mention

    TRENDING_ENABLED = True
except ImportError:
    TRENDING_ENABLED = False

logger = logging.getLogger("combined_node")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(ch)


class CombinedAgentNode:
    """
    Orchestration nodes for the Mother Graph (CombinedAgentState).

    Implements the Fan-In logic after domain agents complete:
    1. GraphInitiator - Starts each iteration & Clears previous state
    2. FeedAggregator - Collects and ranks domain insights (Risks & Opportunities)
    3. DataRefresher - Updates risk dashboard
    4. DataRefreshRouter - Decides to loop or end
    """

    def __init__(self, llm):
        self.llm = llm
        # Initialize production storage manager
        self.storage = StorageManager()
        # Track seen summaries for corroboration scoring
        self._seen_summaries_count: Dict[str, int] = {}
        logger.info(
            "[CombinedAgentNode] Initialized with production storage layer + LLM filter"
        )

    # =========================================================================
    # LLM POST FILTER - Quality control and enhancement
    # =========================================================================

    def _llm_filter_post(self, summary: str, domain: str = "unknown") -> Dict[str, Any]:
        """
        LLM-based post filtering and enhancement.

        Returns:
            Dict with:
            - keep: bool (True if post should be displayed)
            - enhanced_summary: str (200-word max, cleaned summary)
            - severity: str (low/medium/high/critical)
            - fake_news_score: float (0.0-1.0, higher = more likely fake)
            - region: str (sri_lanka/world)
            - confidence_boost: float (0.0-0.3, based on corroboration)
        """
        if not summary or len(summary.strip()) < 20:
            return {"keep": False, "reason": "too_short"}

        # Limit input to prevent token overflow
        summary_input = summary[:1500]

        filter_prompt = f"""Analyze this news post for quality and classification:

POST: {summary_input}
DOMAIN: {domain}

Respond with JSON only (no markdown, no explanation):
{{
    "keep": true/false,
    "fake_news_probability": 0.0-1.0,
    "severity": "low/medium/high/critical",
    "region": "sri_lanka/world",
    "enhanced_summary": "Cleaned, concise summary (max 200 words)",
    "is_meaningful": true/false
}}

Rules:
1. keep=false if: spam, ads, meaningless text, or fake_news_probability > 0.7
2. severity: critical=emergency/disaster, high=significant impact, medium=notable, low=informational
3. region: "sri_lanka" if about Sri Lanka, otherwise "world"
4. enhanced_summary: Clean, professional, max 200 words. Keep key facts.
5. is_meaningful: false if no actionable intelligence or just social chatter

JSON only:"""

        try:
            response = self.llm.invoke(filter_prompt)
            content = (
                response.content if hasattr(response, "content") else str(response)
            )

            # Parse JSON response
            import json
            import re

            # Clean up response - extract JSON
            content = content.strip()
            if content.startswith("```"):
                content = re.sub(r"^```\w*\n?", "", content)
                content = re.sub(r"\n?```$", "", content)

            result = json.loads(content)

            # Validate required fields
            keep = result.get("keep", False) and result.get("is_meaningful", False)
            fake_score = float(result.get("fake_news_probability", 0.5))

            # Reject high fake news probability
            if fake_score > 0.7:
                keep = False

            # Calculate corroboration boost
            confidence_boost = self._calculate_corroboration_boost(summary)

            # Limit enhanced summary to 200 words
            enhanced = result.get("enhanced_summary", summary)
            words = enhanced.split()
            if len(words) > 200:
                enhanced = " ".join(words[:200])

            return {
                "keep": keep,
                "enhanced_summary": enhanced,
                "severity": result.get("severity", "medium"),
                "fake_news_score": fake_score,
                "region": result.get("region", "sri_lanka"),
                "confidence_boost": confidence_boost,
                "original_summary": summary,
            }

        except Exception as e:
            logger.warning(f"[LLM_FILTER] Error processing post: {e}")
            # Fallback: keep post but with default values
            words = summary.split()
            truncated = " ".join(words[:200]) if len(words) > 200 else summary
            return {
                "keep": True,
                "enhanced_summary": truncated,
                "severity": "medium",
                "fake_news_score": 0.3,
                "region": (
                    "sri_lanka"
                    if any(
                        kw in summary.lower()
                        for kw in ["sri lanka", "colombo", "kandy", "galle"]
                    )
                    else "world"
                ),
                "confidence_boost": 0.0,
                "original_summary": summary,
            }

    def _calculate_corroboration_boost(self, summary: str) -> float:
        """
        Calculate confidence boost based on similar news corroboration.
        More sources reporting similar news = higher confidence.
        """
        try:
            # Check for similar news in ChromaDB
            similar = self.storage.chromadb.find_similar(summary, threshold=0.75)
            if similar:
                # Each corroborating source adds 0.1 confidence, max 0.3
                return min(0.3, 0.1)
            return 0.0
        except Exception:
            return 0.0

    # =========================================================================
    # 1. GRAPH INITIATOR
    # =========================================================================

    def graph_initiator(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Initialization step executed at START in the graph.

        Responsibilities:
        - Increment run counter
        - Timestamp the execution
        - CRITICAL: Send "RESET" signal to clear domain_insights from previous loop

        Returns:
            Dict updating run_count, last_run_ts, and clearing data lists
        """
        logger.info("[GraphInitiator] ===== STARTING GRAPH ITERATION =====")

        current_run = getattr(state, "run_count", 0)
        new_run_count = current_run + 1

        logger.info(f"[GraphInitiator] Run count: {new_run_count}")
        logger.info(f"[GraphInitiator] Timestamp: {datetime.utcnow().isoformat()}")

        return {
            "run_count": new_run_count,
            "last_run_ts": datetime.utcnow(),
            # CRITICAL FIX: Send "RESET" string to trigger the custom reducer
            # in CombinedAgentState. This wipes the list clean for the new loop.
            "domain_insights": "RESET",
            "final_ranked_feed": [],
        }

    # =========================================================================
    # 2. FEED AGGREGATOR AGENT
    # =========================================================================

    def feed_aggregator_agent(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        CRITICAL NODE: Aggregates outputs from all domain agents.

        This implements the "Fan-In (Reduce Phase)" from your architecture:
        - Collects domain_insights from all agents
        - Deduplicates similar events
        - Ranks by risk_score + severity + impact_type
        - Converts to ClassifiedEvent format

        Input: domain_insights (List[Dict]) from state
        Output: final_ranked_feed (List[Dict])
        """
        logger.info("[FeedAggregatorAgent] ===== AGGREGATING DOMAIN INSIGHTS =====")

        # Step 1: Gather domain insights
        # Note: In the new state model, this will be a List[Dict] gathered from parallel agents
        incoming = getattr(state, "domain_insights", [])

        # Handle case where incoming might be the "RESET" string (edge case protection)
        if isinstance(incoming, str):
            incoming = []

        if not incoming:
            logger.warning("[FeedAggregatorAgent] No domain insights received!")
            return {"final_ranked_feed": []}

        # Step 2: Flatten nested lists
        # Some agents may return [[insight], [insight]] due to reducer logic
        flattened: List[Dict[str, Any]] = []
        for item in incoming:
            if isinstance(item, list):
                flattened.extend(item)
            else:
                flattened.append(item)

        logger.info(
            f"[FeedAggregatorAgent] Received {len(flattened)} raw insights from domain agents"
        )

        # Step 3: PRODUCTION DEDUPLICATION - 3-tier pipeline (SQLite → ChromaDB → Accept)
        unique: List[Dict[str, Any]] = []
        dedup_stats = {"exact_matches": 0, "semantic_matches": 0, "unique_events": 0}

        for ins in flattened:
            summary = str(ins.get("summary", "")).strip()
            if not summary:
                continue

            # Use storage manager's 3-tier deduplication
            is_dup, reason, match_data = self.storage.is_duplicate(summary)

            if is_dup:
                if reason == "exact_match":
                    dedup_stats["exact_matches"] += 1
                elif reason == "semantic_match":
                    dedup_stats["semantic_matches"] += 1
                    # Link similar events in Neo4j knowledge graph
                    if match_data and "id" in match_data:
                        event_id = ins.get("source_event_id") or str(uuid.uuid4())
                        self.storage.link_similar_events(
                            event_id,
                            match_data["id"],
                            match_data.get("similarity", 0.85),
                        )
                continue

            # Event is unique - accept it
            dedup_stats["unique_events"] += 1
            unique.append(ins)

        logger.info(
            f"[FeedAggregatorAgent] Deduplication complete: "
            f"{dedup_stats['unique_events']} unique, "
            f"{dedup_stats['exact_matches']} exact dups, "
            f"{dedup_stats['semantic_matches']} semantic dups"
        )

        # Step 4: Rank by risk_score + severity boost + Opportunity Logic
        severity_boost_map = {"low": 0.0, "medium": 0.05, "high": 0.15, "critical": 0.3}

        def calculate_score(item: Dict[str, Any]) -> float:
            """Calculate composite score for Risks AND Opportunities"""
            base = float(item.get("risk_score", 0.0))
            severity = str(item.get("severity", "low")).lower()
            impact = str(item.get("impact_type", "risk")).lower()

            boost = severity_boost_map.get(severity, 0.0)

            # Opportunities are also "High Priority" events, so we boost them too
            # to make sure they appear at the top of the feed
            opp_boost = 0.2 if impact == "opportunity" else 0.0

            return base + boost + opp_boost

        # Sort descending by score
        ranked = sorted(unique, key=calculate_score, reverse=True)

        logger.info("[FeedAggregatorAgent] Top 3 events by score:")
        for i, ins in enumerate(ranked[:3]):
            score = calculate_score(ins)
            domain = ins.get("domain", "unknown")
            impact = ins.get("impact_type", "risk")
            summary_preview = str(ins.get("summary", ""))[:80]
            logger.info(
                f"  {i+1}. [{domain}] ({impact}) Score={score:.3f} | {summary_preview}..."
            )

        # Step 5: LLM FILTER + Convert to ClassifiedEvent format + Store
        # Process each post through LLM for quality control
        converted: List[Dict[str, Any]] = []
        filtered_count = 0
        llm_processed = 0

        logger.info(
            f"[FeedAggregatorAgent] Processing {len(ranked)} posts through LLM filter..."
        )

        for ins in ranked:
            event_id = ins.get("source_event_id") or str(uuid.uuid4())
            original_summary = str(ins.get("summary", ""))
            domain = ins.get("domain", "unknown")
            original_severity = ins.get("severity", "medium")
            impact_type = ins.get("impact_type", "risk")
            base_confidence = round(calculate_score(ins), 3)
            timestamp = datetime.utcnow().isoformat()

            # Run through LLM filter
            llm_result = self._llm_filter_post(original_summary, domain)
            llm_processed += 1

            # Skip if LLM says don't keep
            if not llm_result.get("keep", False):
                filtered_count += 1
                logger.debug(f"[LLM_FILTER] Filtered out: {original_summary[:60]}...")
                continue

            # Use LLM-enhanced data
            summary = llm_result.get("enhanced_summary", original_summary)
            severity = llm_result.get("severity", original_severity)
            region = llm_result.get("region", "sri_lanka")
            fake_score = llm_result.get("fake_news_score", 0.0)
            confidence_boost = llm_result.get("confidence_boost", 0.0)

            # Final confidence = base + corroboration boost - fake penalty
            final_confidence = min(
                1.0, max(0.0, base_confidence + confidence_boost - (fake_score * 0.2))
            )

            # FRONTEND-COMPATIBLE FORMAT
            classified = {
                "event_id": event_id,
                "summary": summary,  # Frontend expects 'summary'
                "domain": domain,  # Frontend expects 'domain'
                "confidence": round(
                    final_confidence, 3
                ),  # Frontend expects 'confidence'
                "severity": severity,
                "impact_type": impact_type,
                "region": region,  # NEW: for sidebar filtering
                "fake_news_score": fake_score,  # NEW: for transparency
                "timestamp": timestamp,
            }
            converted.append(classified)

            # Store in all databases (SQLite, ChromaDB, Neo4j)
            self.storage.store_event(
                event_id=event_id,
                summary=summary,
                domain=domain,
                severity=severity,
                impact_type=impact_type,
                confidence_score=final_confidence,
                timestamp=timestamp,
            )

        logger.info(
            f"[FeedAggregatorAgent] LLM Filter: {llm_processed} processed, {filtered_count} filtered out"
        )
        logger.info(
            f"[FeedAggregatorAgent] ===== PRODUCED {len(converted)} QUALITY EVENTS ====="
        )

        # NEW: Step 6 - Create categorized feeds for frontend display
        categorized = {
            "political": [],
            "economical": [],
            "social": [],
            "meteorological": [],
            "intelligence": [],
        }

        for ins in flattened:
            domain = ins.get("domain", "unknown")
            structured_data = ins.get("structured_data", {})

            # Skip if no structured data or unknown domain
            if not structured_data or domain not in categorized:
                continue

            # Extract and add feeds for this domain
            domain_feeds = self._extract_feeds(structured_data, domain)
            categorized[domain].extend(domain_feeds)

        # Log categorized counts
        for domain, items in categorized.items():
            logger.info(
                f"[FeedAggregatorAgent] {domain.title()}: {len(items)} categorized items"
            )

        return {"final_ranked_feed": converted, "categorized_feeds": categorized}

    def _extract_feeds(
        self, structured_data: Dict[str, Any], domain: str
    ) -> List[Dict[str, Any]]:
        """
        Helper to extract and flatten feed items from structured_data.
        Converts nested structured_data into a flat list of feed items.
        """
        extracted = []

        for category, items in structured_data.items():
            # Handle list items (actual feed data)
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        feed_item = {
                            **item,
                            "domain": domain,
                            "category": category,
                            "timestamp": item.get(
                                "timestamp", datetime.utcnow().isoformat()
                            ),
                        }
                        extracted.append(feed_item)

            # Handle dictionary items (e.g., intelligence profiles/competitors)
            elif isinstance(items, dict):
                for key, value in items.items():
                    if isinstance(value, list):
                        for item in value:
                            if isinstance(item, dict):
                                feed_item = {
                                    **item,
                                    "domain": domain,
                                    "category": category,
                                    "subcategory": key,
                                    "timestamp": item.get(
                                        "timestamp", datetime.utcnow().isoformat()
                                    ),
                                }
                                extracted.append(feed_item)

        return extracted

    # =========================================================================
    # 3. DATA REFRESHER AGENT
    # =========================================================================

    def data_refresher_agent(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Updates risk dashboard snapshot based on final_ranked_feed.

        This implements the "Operational Risk Radar" from your report:
        - logistics_friction: Route risk from mobility data
        - compliance_volatility: Regulatory risk from political data
        - market_instability: Volatility from economic data
        - opportunity_index: NEW - Growth signals from positive events

        Input: final_ranked_feed
        Output: risk_dashboard_snapshot
        """
        logger.info("[DataRefresherAgent] ===== REFRESHING DASHBOARD =====")

        # Get feed from state - handle both dict and object access
        if isinstance(state, dict):
            feed = state.get("final_ranked_feed", [])
        else:
            feed = getattr(state, "final_ranked_feed", [])

        # Default snapshot structure
        snapshot = {
            "logistics_friction": 0.0,
            "compliance_volatility": 0.0,
            "market_instability": 0.0,
            "opportunity_index": 0.0,
            "avg_confidence": 0.0,
            "high_priority_count": 0,
            "total_events": 0,
            "trending_topics": [],
            "spike_alerts": [],
            "infrastructure_health": 1.0,
            "regulatory_activity": 0.0,
            "investment_climate": 0.5,
            "last_updated": datetime.utcnow().isoformat(),
        }

        if not feed:
            logger.info("[DataRefresherAgent] Empty feed - returning zero metrics")
            return {"risk_dashboard_snapshot": snapshot}

        # Compute aggregate metrics - feed uses 'confidence' field, not 'confidence_score'
        confidences = [
            float(item.get("confidence", item.get("confidence_score", 0.5)))
            for item in feed
        ]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        high_priority_count = sum(1 for c in confidences if c >= 0.7)

        # Domain-specific scoring buckets
        domain_risks = {}
        opportunity_scores = []

        for item in feed:
            # Feed uses 'domain' field, not 'target_agent'
            domain = item.get("domain", item.get("target_agent", "unknown"))
            score = item.get("confidence", item.get("confidence_score", 0.5))
            impact = item.get("impact_type", "risk")

            # Separate Opportunities from Risks
            if impact == "opportunity":
                opportunity_scores.append(score)
            else:
                # Group Risks by Domain
                if domain not in domain_risks:
                    domain_risks[domain] = []
                domain_risks[domain].append(score)

        # Helper for calculating averages safely
        def safe_avg(lst):
            return sum(lst) / len(lst) if lst else 0.0

        # Calculate domain-specific risk scores
        # Mobility -> Logistics Friction
        mobility_scores = domain_risks.get("mobility", []) + domain_risks.get(
            "social", []
        )  # Social unrest affects logistics
        snapshot["logistics_friction"] = round(safe_avg(mobility_scores), 3)

        # Political -> Compliance Volatility
        political_scores = domain_risks.get("political", [])
        snapshot["compliance_volatility"] = round(safe_avg(political_scores), 3)

        # Market/Economic -> Market Instability
        market_scores = domain_risks.get("market", []) + domain_risks.get(
            "economical", []
        )
        snapshot["market_instability"] = round(safe_avg(market_scores), 3)

        # NEW: Opportunity Index
        # Higher score means stronger positive signals
        snapshot["opportunity_index"] = round(safe_avg(opportunity_scores), 3)

        snapshot["avg_confidence"] = round(avg_confidence, 3)
        snapshot["high_priority_count"] = high_priority_count
        snapshot["total_events"] = len(feed)

        # NEW: Enhanced Operational Indicators
        # Infrastructure Health (inverted logistics friction)
        snapshot["infrastructure_health"] = round(
            max(0, 1.0 - snapshot["logistics_friction"]), 3
        )

        # Regulatory Activity (sum of political events)
        snapshot["regulatory_activity"] = round(len(political_scores) * 0.1, 3)

        # Investment Climate (opportunity-weighted)
        if opportunity_scores:
            snapshot["investment_climate"] = round(
                0.5 + safe_avg(opportunity_scores) * 0.5, 3
            )

        # NEW: Record topics for trending analysis and get current trends
        if TRENDING_ENABLED:
            try:
                detector = get_trending_detector()

                # Record topics from feed
                for item in feed:
                    summary = item.get("summary", "")
                    domain = item.get("domain", item.get("target_agent", "unknown"))

                    # Extract key topic words (simplified - just use first 3 words)
                    words = summary.split()[:5]
                    if words:
                        topic = " ".join(words).lower()
                        record_topic_mention(topic, source="roger_feed", domain=domain)

                # Get trending topics and spike alerts
                snapshot["trending_topics"] = detector.get_trending_topics(limit=5)
                snapshot["spike_alerts"] = detector.get_spike_alerts(limit=3)

                logger.info(
                    f"[DataRefresherAgent] Trending: {len(snapshot['trending_topics'])} topics, {len(snapshot['spike_alerts'])} spikes"
                )
            except Exception as e:
                logger.warning(f"[DataRefresherAgent] Trending detection failed: {e}")

        snapshot["last_updated"] = datetime.utcnow().isoformat()

        logger.info("[DataRefresherAgent] Dashboard Metrics:")
        logger.info(f"  Logistics Friction: {snapshot['logistics_friction']}")
        logger.info(f"  Compliance Volatility: {snapshot['compliance_volatility']}")
        logger.info(f"  Market Instability: {snapshot['market_instability']}")
        logger.info(f"  Opportunity Index: {snapshot['opportunity_index']}")
        logger.info(
            f"  High Priority Events: {snapshot['high_priority_count']}/{snapshot['total_events']}"
        )

        # PRODUCTION FEATURE: Export to CSV for archival
        try:
            if feed:
                self.storage.export_feed_to_csv(feed)
                logger.info(f"[DataRefresherAgent] Exported {len(feed)} events to CSV")
        except Exception as e:
            logger.error(f"[DataRefresherAgent] CSV export error: {e}")

        # Cleanup old cache entries periodically
        try:
            self.storage.cleanup_old_data()
        except Exception as e:
            logger.error(f"[DataRefresherAgent] Cleanup error: {e}")

        return {"risk_dashboard_snapshot": snapshot}

    # =========================================================================
    # 4. DATA REFRESH ROUTER
    # =========================================================================

    def data_refresh_router(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Routing decision after dashboard refresh.

        UPDATED: Returns END immediately (non-blocking). The 60-second interval
        is now managed externally by the caller (main.py run_graph_loop).
        This makes the graph execution non-blocking.

        Returns:
            {"route": "END"} to complete this cycle
        """
        logger.info("[DataRefreshRouter] Cycle complete. Returning END (non-blocking).")

        # Return END to complete this graph cycle
        # The 60-second scheduling is handled by the caller in main.py
        return {"route": "END"}
