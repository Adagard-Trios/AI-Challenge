"""
src/nodes/meteorologicalAgentNode.py
MODULAR - Meteorological Agent Node with Subgraph Architecture
Three modules: Official Sources, Social Media Collection, Feed Generation

Updated: Uses Tool Factory pattern for parallel execution safety.
Each agent instance gets its own private set of tools.

ENHANCED: Now includes RiverNet flood monitoring integration.
"""

import json
import uuid
from typing import Dict, Any
from datetime import datetime
from src.states.meteorologicalAgentState import MeteorologicalAgentState
from src.utils.tool_factory import create_tool_set
from src.utils.utils import tool_dmc_alerts, tool_weather_nowcast, tool_rivernet_status
from src.llms.groqllm import GroqLLM


class MeteorologicalAgentNode:
    """
    Modular Meteorological Agent - Three independent collection modules.
    Module 1: Official Weather Sources (DMC Alerts, Weather Nowcast, RiverNet)
    Module 2: Social Media (National, District, Climate)
    Module 3: Feed Generation (Categorize, Summarize, Format)

    Thread Safety:
        Each MeteorologicalAgentNode instance creates its own private ToolSet,
        enabling safe parallel execution with other agents.
    """

    def __init__(self, llm=None):
        """Initialize with Groq LLM and private tool set"""
        # Create PRIVATE tool instances for this agent
        self.tools = create_tool_set()

        if llm is None:
            groq = GroqLLM()
            self.llm = groq.get_llm()
        else:
            self.llm = llm

        # All 25 districts of Sri Lanka
        self.districts = [
            "colombo",
            "gampaha",
            "kalutara",
            "kandy",
            "matale",
            "nuwara eliya",
            "galle",
            "matara",
            "hambantota",
            "jaffna",
            "kilinochchi",
            "mannar",
            "mullaitivu",
            "vavuniya",
            "puttalam",
            "kurunegala",
            "anuradhapura",
            "polonnaruwa",
            "badulla",
            "monaragala",
            "ratnapura",
            "kegalle",
            "ampara",
            "batticaloa",
            "trincomalee",
        ]

        # Key districts for weather monitoring
        self.key_districts = ["colombo", "kandy", "galle", "jaffna", "trincomalee"]

        # Key cities for weather nowcast
        self.key_cities = [
            "Colombo",
            "Kandy",
            "Galle",
            "Jaffna",
            "Trincomalee",
            "Anuradhapura",
        ]

    # ============================================
    # MODULE 1: OFFICIAL WEATHER SOURCES
    # ============================================

    def collect_official_sources(
        self, state: MeteorologicalAgentState
    ) -> Dict[str, Any]:
        """
        Module 1: Collect official weather sources
        - DMC Alerts (Disaster Management Centre)
        - Weather Nowcast for key cities
        - RiverNet flood monitoring data (NEW)
        """
        print("[MODULE 1] Collecting Official Weather Sources")

        official_results = []
        river_data = None

        # DMC Alerts
        try:
            dmc_data = tool_dmc_alerts()
            official_results.append(
                {
                    "source_tool": "dmc_alerts",
                    "raw_content": json.dumps(dmc_data),
                    "category": "official",
                    "subcategory": "dmc_alerts",
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )
            print("  ✓ Collected DMC Alerts")
        except Exception as e:
            print(f"  ⚠️ DMC Alerts error: {e}")

        # RiverNet Flood Monitoring (NEW)
        try:
            river_data = tool_rivernet_status()
            official_results.append(
                {
                    "source_tool": "rivernet",
                    "raw_content": json.dumps(river_data),
                    "category": "official",
                    "subcategory": "flood_monitoring",
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )

            # Log summary
            summary = river_data.get("summary", {})
            overall_status = summary.get("overall_status", "unknown")
            river_count = summary.get("total_monitored", 0)
            print(
                f"  ✓ RiverNet: {river_count} rivers monitored, status: {overall_status}"
            )

            # Add any flood alerts
            for alert in river_data.get("alerts", []):
                official_results.append(
                    {
                        "source_tool": "rivernet_alert",
                        "raw_content": json.dumps(alert),
                        "category": "official",
                        "subcategory": "flood_alert",
                        "severity": alert.get("severity", "medium"),
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )

        except Exception as e:
            print(f"  ⚠️ RiverNet error: {e}")

        # Weather Nowcast for key cities
        for city in self.key_cities:
            try:
                weather_data = tool_weather_nowcast(location=city)
                official_results.append(
                    {
                        "source_tool": "weather_nowcast",
                        "raw_content": json.dumps(weather_data),
                        "category": "official",
                        "subcategory": "weather_forecast",
                        "city": city,
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
                print(f"  ✓ Weather Nowcast for {city}")
            except Exception as e:
                print(f"  ⚠️ Weather Nowcast {city} error: {e}")

        return {
            "worker_results": official_results,
            "latest_worker_results": official_results,
            "river_data": river_data,  # Store river data separately for easy access
        }

    # ============================================
    # MODULE 2: SOCIAL MEDIA COLLECTION
    # ============================================

    def collect_national_social_media(
        self, state: MeteorologicalAgentState
    ) -> Dict[str, Any]:
        """
        Module 2A: Collect national-level weather social media
        """
        print("[MODULE 2A] Collecting National Weather Social Media")

        social_results = []

        # Twitter - National Weather
        try:
            twitter_tool = self.tools.get("scrape_twitter")
            if twitter_tool:
                twitter_data = twitter_tool.invoke(
                    {"query": "sri lanka weather forecast rain", "max_items": 15}
                )
                social_results.append(
                    {
                        "source_tool": "scrape_twitter",
                        "raw_content": str(twitter_data),
                        "category": "national",
                        "platform": "twitter",
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
                print("  ✓ Twitter National Weather")
        except Exception as e:
            print(f"  ⚠️ Twitter error: {e}")

        # Facebook - National Weather
        try:
            facebook_tool = self.tools.get("scrape_facebook")
            if facebook_tool:
                facebook_data = facebook_tool.invoke(
                    {
                        "keywords": ["sri lanka weather", "sri lanka rain"],
                        "max_items": 10,
                    }
                )
                social_results.append(
                    {
                        "source_tool": "scrape_facebook",
                        "raw_content": str(facebook_data),
                        "category": "national",
                        "platform": "facebook",
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
                print("  ✓ Facebook National Weather")
        except Exception as e:
            print(f"  ⚠️ Facebook error: {e}")

        # LinkedIn - Climate & Weather
        try:
            linkedin_tool = self.tools.get("scrape_linkedin")
            if linkedin_tool:
                linkedin_data = linkedin_tool.invoke(
                    {
                        "keywords": ["sri lanka weather", "sri lanka climate"],
                        "max_items": 5,
                    }
                )
                social_results.append(
                    {
                        "source_tool": "scrape_linkedin",
                        "raw_content": str(linkedin_data),
                        "category": "national",
                        "platform": "linkedin",
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
                print("  ✓ LinkedIn Weather/Climate")
        except Exception as e:
            print(f"  ⚠️ LinkedIn error: {e}")

        # Instagram - Weather
        try:
            instagram_tool = self.tools.get("scrape_instagram")
            if instagram_tool:
                instagram_data = instagram_tool.invoke(
                    {"keywords": ["srilankaweather"], "max_items": 5}
                )
                social_results.append(
                    {
                        "source_tool": "scrape_instagram",
                        "raw_content": str(instagram_data),
                        "category": "national",
                        "platform": "instagram",
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
                print("  ✓ Instagram Weather")
        except Exception as e:
            print(f"  ⚠️ Instagram error: {e}")

        # Reddit - Weather
        try:
            reddit_tool = self.tools.get("scrape_reddit")
            if reddit_tool:
                reddit_data = reddit_tool.invoke(
                    {
                        "keywords": ["sri lanka weather", "sri lanka rain"],
                        "limit": 10,
                        "subreddit": "srilanka",
                    }
                )
                social_results.append(
                    {
                        "source_tool": "scrape_reddit",
                        "raw_content": str(reddit_data),
                        "category": "national",
                        "platform": "reddit",
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
                print("  ✓ Reddit Weather")
        except Exception as e:
            print(f"  ⚠️ Reddit error: {e}")

        return {
            "worker_results": social_results,
            "social_media_results": social_results,
        }

    def collect_district_social_media(
        self, state: MeteorologicalAgentState
    ) -> Dict[str, Any]:
        """
        Module 2B: Collect district-level weather social media
        """
        print(
            f"[MODULE 2B] Collecting District Weather Social Media ({len(self.key_districts)} districts)"
        )

        district_results = []

        for district in self.key_districts:
            # Twitter per district
            try:
                twitter_tool = self.tools.get("scrape_twitter")
                if twitter_tool:
                    twitter_data = twitter_tool.invoke(
                        {"query": f"{district} sri lanka weather", "max_items": 5}
                    )
                    district_results.append(
                        {
                            "source_tool": "scrape_twitter",
                            "raw_content": str(twitter_data),
                            "category": "district",
                            "district": district,
                            "platform": "twitter",
                            "timestamp": datetime.utcnow().isoformat(),
                        }
                    )
                    print(f"  ✓ Twitter {district.title()}")
            except Exception as e:
                print(f"  ⚠️ Twitter {district} error: {e}")

            # Facebook per district
            try:
                facebook_tool = self.tools.get("scrape_facebook")
                if facebook_tool:
                    facebook_data = facebook_tool.invoke(
                        {"keywords": [f"{district} weather"], "max_items": 5}
                    )
                    district_results.append(
                        {
                            "source_tool": "scrape_facebook",
                            "raw_content": str(facebook_data),
                            "category": "district",
                            "district": district,
                            "platform": "facebook",
                            "timestamp": datetime.utcnow().isoformat(),
                        }
                    )
                    print(f"  ✓ Facebook {district.title()}")
            except Exception as e:
                print(f"  ⚠️ Facebook {district} error: {e}")

        return {
            "worker_results": district_results,
            "social_media_results": district_results,
        }

    def collect_climate_alerts(self, state: MeteorologicalAgentState) -> Dict[str, Any]:
        """
        Module 2C: Collect climate and disaster-related posts
        """
        print("[MODULE 2C] Collecting Climate & Disaster Alerts")

        climate_results = []

        # Twitter - Climate & Disasters
        try:
            twitter_tool = self.tools.get("scrape_twitter")
            if twitter_tool:
                twitter_data = twitter_tool.invoke(
                    {
                        "query": "sri lanka flood drought cyclone disaster",
                        "max_items": 10,
                    }
                )
                climate_results.append(
                    {
                        "source_tool": "scrape_twitter",
                        "raw_content": str(twitter_data),
                        "category": "climate",
                        "platform": "twitter",
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
                print("  ✓ Twitter Climate Alerts")
        except Exception as e:
            print(f"  ⚠️ Twitter climate error: {e}")

        return {
            "worker_results": climate_results,
            "social_media_results": climate_results,
        }

    # ============================================
    # MODULE 3: FEED GENERATION
    # ============================================

    def categorize_by_geography(
        self, state: MeteorologicalAgentState
    ) -> Dict[str, Any]:
        """
        Module 3A: Categorize all collected results by geography and alert type
        """
        print("[MODULE 3A] Categorizing Weather Results")

        all_results = state.get("worker_results", []) or []

        # Initialize categories
        official_data = []
        national_data = []
        alert_data = []
        district_data = {district: [] for district in self.districts}

        for r in all_results:
            category = r.get("category", "unknown")
            district = r.get("district")
            content = r.get("raw_content", "")

            # Parse content
            try:
                data = json.loads(content)
                if isinstance(data, dict) and "error" in data:
                    continue

                if isinstance(data, str):
                    data = json.loads(data)

                posts = []
                if isinstance(data, list):
                    posts = data
                elif isinstance(data, dict):
                    posts = data.get("results", []) or data.get("data", [])
                    if not posts:
                        posts = [data]

                # Categorize
                if category == "official":
                    official_data.extend(posts[:10])
                    # DMC alerts go to alert feed
                    if r.get("subcategory") == "dmc_alerts":
                        alert_data.extend(posts[:20])
                elif category == "climate":
                    alert_data.extend(posts[:10])
                elif category == "district" and district:
                    district_data[district].extend(posts[:5])
                elif category == "national":
                    national_data.extend(posts[:10])

            except Exception:
                continue

        # Create structured feeds
        structured_feeds = {
            "sri lanka weather": national_data + official_data,
            "alerts": alert_data,
            **{district: posts for district, posts in district_data.items() if posts},
        }

        print(
            f"  ✓ Categorized: {len(official_data)} official, {len(national_data)} national, {len(alert_data)} alerts"
        )
        print(
            f"  ✓ Districts with data: {len([d for d in district_data if district_data[d]])}"
        )

        return {
            "structured_output": structured_feeds,
            "district_feeds": district_data,
            "national_feed": national_data + official_data,
            "alert_feed": alert_data,
        }

    def generate_llm_summary(self, state: MeteorologicalAgentState) -> Dict[str, Any]:
        """
        Module 3B: Use Groq LLM to generate executive summary
        """
        print("[MODULE 3B] Generating LLM Summary")

        structured_feeds = state.get("structured_output", {})

        try:
            summary_prompt = f"""Analyze the following meteorological intelligence data for Sri Lanka and create a concise executive summary.

Data Summary:
- National/Official Weather: {len(structured_feeds.get('sri lanka weather', []))} items
- Weather Alerts: {len(structured_feeds.get('alerts', []))} items
- District Coverage: {len([k for k in structured_feeds.keys() if k not in ['sri lanka weather', 'alerts']])} districts

Sample Data:
{json.dumps(structured_feeds, indent=2)[:2000]}

Generate a brief (3-5 sentences) executive summary highlighting the most important weather developments and alerts."""

            llm_response = self.llm.invoke(summary_prompt)
            llm_summary = (
                llm_response.content
                if hasattr(llm_response, "content")
                else str(llm_response)
            )

            print("  ✓ LLM Summary Generated")

        except Exception as e:
            print(f"  ⚠️ LLM Error: {e}")
            llm_summary = "AI summary currently unavailable."

        return {"llm_summary": llm_summary}

    def format_final_output(self, state: MeteorologicalAgentState) -> Dict[str, Any]:
        """
        Module 3C: Format final feed output
        ENHANCED: Now includes RiverNet flood monitoring data
        """
        print("[MODULE 3C] Formatting Final Output")

        llm_summary = state.get("llm_summary", "No summary available")
        structured_feeds = state.get("structured_output", {})
        district_feeds = state.get("district_feeds", {})
        river_data = state.get("river_data", {})  # NEW: River data

        official_count = len(
            [
                r
                for r in state.get("worker_results", [])
                if r.get("category") == "official"
            ]
        )
        national_count = len(
            [
                r
                for r in state.get("worker_results", [])
                if r.get("category") == "national"
            ]
        )
        alert_count = len(
            [
                r
                for r in state.get("worker_results", [])
                if r.get("category") == "climate"
            ]
        )
        active_districts = len([d for d in district_feeds if district_feeds.get(d)])

        # River monitoring stats
        river_summary = river_data.get("summary", {}) if river_data else {}
        rivers_monitored = river_summary.get("total_monitored", 0)
        river_status = river_summary.get("overall_status", "unknown")
        has_flood_alerts = river_summary.get("has_alerts", False)

        change_detected = state.get("change_detected", False) or has_flood_alerts
        change_line = "⚠️ NEW ALERTS DETECTED\n" if change_detected else ""

        # Build river status section
        river_section = ""
        if river_data and river_data.get("rivers"):
            river_lines = ["🌊 RIVER MONITORING (RiverNet.lk)"]
            for river in river_data.get("rivers", [])[:6]:
                name = river.get("name", "Unknown")
                status = river.get("status", "unknown")
                region = river.get("region", "")
                status_emoji = {
                    "danger": "🔴",
                    "warning": "🟠",
                    "rising": "🟡",
                    "normal": "🟢",
                    "unknown": "⚪",
                    "error": "❌",
                }.get(status, "⚪")
                river_lines.append(
                    f"  {status_emoji} {name} ({region}): {status.upper()}"
                )
            river_section = "\n".join(river_lines) + "\n"

        bulletin = f"""🇱🇰 COMPREHENSIVE METEOROLOGICAL INTELLIGENCE FEED
{datetime.utcnow().strftime("%d %b %Y • %H:%M UTC")}

{change_line}
📊 EXECUTIVE SUMMARY (AI-Generated)
{llm_summary}

{river_section}
📈 DATA COLLECTION STATS
• Official Sources: {official_count} items
• National Social Media: {national_count} items
• Climate Alerts: {alert_count} items  
• Active Districts: {active_districts}
• Rivers Monitored: {rivers_monitored} (Status: {river_status.upper()})

🔍 COVERAGE
Districts monitored: {', '.join([d.title() for d in self.key_districts])}
Cities: {', '.join(self.key_cities)}

🌐 STRUCTURED DATA AVAILABLE
• "sri lanka weather": Combined national & official intelligence
• "alerts": Critical weather and disaster alerts
• "rivers": Real-time river level monitoring
• District-level: {', '.join([d.title() for d in district_feeds if district_feeds.get(d)])}

Source: Multi-platform aggregation (DMC, MetDept, RiverNet, Twitter, Facebook, LinkedIn, Instagram, Reddit)
"""

        # Create list for per-district domain_insights (FRONTEND COMPATIBLE)
        domain_insights = []
        timestamp = datetime.utcnow().isoformat()

        # 1. Create insights from RiverNet data (NEW - HIGH PRIORITY)
        if river_data and river_data.get("rivers"):
            for river in river_data.get("rivers", []):
                status = river.get("status", "unknown")
                if status in ["danger", "warning", "rising"]:
                    severity = (
                        "high"
                        if status == "danger"
                        else ("medium" if status == "warning" else "low")
                    )
                    river_name = river.get("name", "Unknown River")
                    region = river.get("region", "")
                    water_level = river.get("water_level", {})
                    level_str = (
                        f" at {water_level.get('value', 'N/A')}{water_level.get('unit', 'm')}"
                        if water_level
                        else ""
                    )

                    domain_insights.append(
                        {
                            "source_event_id": str(uuid.uuid4()),
                            "domain": "meteorological",
                            "category": "flood_monitoring",
                            "summary": f"🌊 {river_name} ({region}): {status.upper()}{level_str}",
                            "severity": severity,
                            "impact_type": "risk",
                            "source": "rivernet.lk",
                            "river_name": river_name,
                            "river_status": status,
                            "water_level": water_level,
                            "timestamp": timestamp,
                        }
                    )

            # Add overall river status insight
            if river_summary.get("has_alerts"):
                domain_insights.append(
                    {
                        "source_event_id": str(uuid.uuid4()),
                        "domain": "meteorological",
                        "category": "flood_alert",
                        "summary": f"⚠️ FLOOD MONITORING ALERT: {rivers_monitored} rivers monitored, overall status: {river_status.upper()}",
                        "severity": "high" if river_status == "danger" else "medium",
                        "impact_type": "risk",
                        "source": "rivernet.lk",
                        "river_data": river_data,
                        "timestamp": timestamp,
                    }
                )

        # 2. Create insights from DMC alerts (high severity)
        alert_data = structured_feeds.get("alerts", [])
        for alert in alert_data[:10]:
            alert_text = alert.get("text", "") or alert.get("title", "")
            if not alert_text:
                continue
            detected_district = "Sri Lanka"
            for district in self.districts:
                if district.lower() in alert_text.lower():
                    detected_district = district.title()
                    break
            domain_insights.append(
                {
                    "source_event_id": str(uuid.uuid4()),
                    "domain": "meteorological",
                    "summary": f"{detected_district}: {alert_text[:200]}",
                    "severity": "high" if change_detected else "medium",
                    "impact_type": "risk",
                    "timestamp": timestamp,
                }
            )

        # 3. Create per-district weather insights
        for district, posts in district_feeds.items():
            if not posts:
                continue
            for post in posts[:3]:
                post_text = post.get("text", "") or post.get("title", "")
                if not post_text or len(post_text) < 10:
                    continue
                severity = "low"
                if any(
                    kw in post_text.lower()
                    for kw in [
                        "flood",
                        "cyclone",
                        "storm",
                        "warning",
                        "alert",
                        "danger",
                    ]
                ):
                    severity = "high"
                elif any(kw in post_text.lower() for kw in ["rain", "wind", "thunder"]):
                    severity = "medium"
                domain_insights.append(
                    {
                        "source_event_id": str(uuid.uuid4()),
                        "domain": "meteorological",
                        "summary": f"{district.title()}: {post_text[:200]}",
                        "severity": severity,
                        "impact_type": "risk" if severity != "low" else "opportunity",
                        "timestamp": timestamp,
                    }
                )

        # 4. Create national weather insights
        national_data = structured_feeds.get("sri lanka weather", [])
        for post in national_data[:5]:
            post_text = post.get("text", "") or post.get("title", "")
            if not post_text or len(post_text) < 10:
                continue
            domain_insights.append(
                {
                    "source_event_id": str(uuid.uuid4()),
                    "domain": "meteorological",
                    "summary": f"Sri Lanka Weather: {post_text[:200]}",
                    "severity": "medium",
                    "impact_type": "risk",
                    "timestamp": timestamp,
                }
            )

        # 5. Add executive summary insight
        domain_insights.append(
            {
                "source_event_id": str(uuid.uuid4()),
                "structured_data": structured_feeds,
                "river_data": river_data,  # NEW: Include river data
                "domain": "meteorological",
                "summary": f"Sri Lanka Meteorological Summary: {llm_summary[:300]}",
                "severity": "high" if change_detected else "medium",
                "impact_type": "risk",
            }
        )

        print(
            f"  ✓ Created {len(domain_insights)} domain insights (including river monitoring)"
        )

        return {
            "final_feed": bulletin,
            "feed_history": [bulletin],
            "domain_insights": domain_insights,
            "river_data": river_data,  # NEW: Pass through for frontend
        }

    # ============================================
    # MODULE 4: FEED AGGREGATOR & STORAGE
    # ============================================

    def aggregate_and_store_feeds(
        self, state: MeteorologicalAgentState
    ) -> Dict[str, Any]:
        """
        Module 4: Aggregate, deduplicate, and store feeds
        - Check uniqueness using Neo4j (URL + content hash)
        - Store unique posts in Neo4j
        - Store unique posts in ChromaDB for RAG
        - Append to CSV dataset for ML training
        """
        print("[MODULE 4] Aggregating and Storing Feeds")

        from src.utils.db_manager import (
            Neo4jManager,
            ChromaDBManager,
            extract_post_data,
        )
        import csv
        import os

        # Initialize database managers
        neo4j_manager = Neo4jManager()
        chroma_manager = ChromaDBManager()

        # Get all worker results from state
        all_worker_results = state.get("worker_results", [])

        # Statistics
        total_posts = 0
        unique_posts = 0
        duplicate_posts = 0
        stored_neo4j = 0
        stored_chroma = 0
        stored_csv = 0

        # Setup CSV dataset
        dataset_dir = os.getenv("DATASET_PATH", "./datasets/weather_feeds")
        os.makedirs(dataset_dir, exist_ok=True)

        csv_filename = f"weather_feeds_{datetime.now().strftime('%Y%m')}.csv"
        csv_path = os.path.join(dataset_dir, csv_filename)

        # CSV headers
        csv_headers = [
            "post_id",
            "timestamp",
            "platform",
            "category",
            "district",
            "poster",
            "post_url",
            "title",
            "text",
            "content_hash",
            "engagement_score",
            "engagement_likes",
            "engagement_shares",
            "engagement_comments",
            "source_tool",
        ]

        # Check if CSV exists to determine if we need to write headers
        file_exists = os.path.exists(csv_path)

        try:
            # Open CSV file in append mode
            with open(csv_path, "a", newline="", encoding="utf-8") as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=csv_headers)

                # Write headers if new file
                if not file_exists:
                    writer.writeheader()
                    print(f"  ✓ Created new CSV dataset: {csv_path}")
                else:
                    print(f"  ✓ Appending to existing CSV: {csv_path}")

                # Process each worker result
                for worker_result in all_worker_results:
                    category = worker_result.get("category", "unknown")
                    platform = worker_result.get("platform", "") or worker_result.get(
                        "subcategory", ""
                    )
                    source_tool = worker_result.get("source_tool", "")
                    district = worker_result.get("district", "")

                    # Parse raw content
                    raw_content = worker_result.get("raw_content", "")
                    if not raw_content:
                        continue

                    try:
                        # Try to parse JSON content
                        if isinstance(raw_content, str):
                            data = json.loads(raw_content)
                        else:
                            data = raw_content

                        # Handle different data structures
                        posts = []
                        if isinstance(data, list):
                            posts = data
                        elif isinstance(data, dict):
                            # Check for common result keys
                            posts = (
                                data.get("results")
                                or data.get("data")
                                or data.get("posts")
                                or data.get("items")
                                or []
                            )

                            # If still empty, treat the dict itself as a post
                            if not posts and (
                                data.get("title")
                                or data.get("text")
                                or data.get("forecast")
                            ):
                                posts = [data]

                        # Process each post
                        for raw_post in posts:
                            total_posts += 1

                            # Skip if error object
                            if isinstance(raw_post, dict) and "error" in raw_post:
                                continue

                            # Extract normalized post data
                            post_data = extract_post_data(
                                raw_post=raw_post,
                                category=category,
                                platform=platform or "unknown",
                                source_tool=source_tool,
                            )

                            if not post_data:
                                continue

                            # Override district if from worker result
                            if district:
                                post_data["district"] = district

                            # Check uniqueness with Neo4j
                            is_dup = neo4j_manager.is_duplicate(
                                post_url=post_data["post_url"],
                                content_hash=post_data["content_hash"],
                            )

                            if is_dup:
                                duplicate_posts += 1
                                continue

                            # Unique post - store it
                            unique_posts += 1

                            # Store in Neo4j
                            if neo4j_manager.store_post(post_data):
                                stored_neo4j += 1

                            # Store in ChromaDB
                            if chroma_manager.add_document(post_data):
                                stored_chroma += 1

                            # Store in CSV
                            try:
                                csv_row = {
                                    "post_id": post_data["post_id"],
                                    "timestamp": post_data["timestamp"],
                                    "platform": post_data["platform"],
                                    "category": post_data["category"],
                                    "district": post_data["district"],
                                    "poster": post_data["poster"],
                                    "post_url": post_data["post_url"],
                                    "title": post_data["title"],
                                    "text": post_data["text"],
                                    "content_hash": post_data["content_hash"],
                                    "engagement_score": post_data["engagement"].get(
                                        "score", 0
                                    ),
                                    "engagement_likes": post_data["engagement"].get(
                                        "likes", 0
                                    ),
                                    "engagement_shares": post_data["engagement"].get(
                                        "shares", 0
                                    ),
                                    "engagement_comments": post_data["engagement"].get(
                                        "comments", 0
                                    ),
                                    "source_tool": post_data["source_tool"],
                                }
                                writer.writerow(csv_row)
                                stored_csv += 1
                            except Exception as e:
                                print(f"  ⚠️ CSV write error: {e}")

                    except Exception as e:
                        print(f"  ⚠️ Error processing worker result: {e}")
                        continue

        except Exception as e:
            print(f"  ⚠️ CSV file error: {e}")

        # Close database connections
        neo4j_manager.close()

        # Print statistics
        print("\n  📊 AGGREGATION STATISTICS")
        print(f"  Total Posts Processed: {total_posts}")
        print(f"  Unique Posts: {unique_posts}")
        print(f"  Duplicate Posts: {duplicate_posts}")
        print(f"  Stored in Neo4j: {stored_neo4j}")
        print(f"  Stored in ChromaDB: {stored_chroma}")
        print(f"  Stored in CSV: {stored_csv}")
        print(f"  Dataset Path: {csv_path}")

        # Get database counts
        neo4j_total = neo4j_manager.get_post_count() if neo4j_manager.driver else 0
        chroma_total = (
            chroma_manager.get_document_count() if chroma_manager.collection else 0
        )

        print("\n  💾 DATABASE TOTALS")
        print(f"  Neo4j Total Posts: {neo4j_total}")
        print(f"  ChromaDB Total Docs: {chroma_total}")

        return {
            "aggregator_stats": {
                "total_processed": total_posts,
                "unique_posts": unique_posts,
                "duplicate_posts": duplicate_posts,
                "stored_neo4j": stored_neo4j,
                "stored_chroma": stored_chroma,
                "stored_csv": stored_csv,
                "neo4j_total": neo4j_total,
                "chroma_total": chroma_total,
            },
            "dataset_path": csv_path,
        }
