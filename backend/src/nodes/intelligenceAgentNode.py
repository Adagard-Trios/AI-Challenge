"""
src/nodes/intelligenceAgentNode.py
MODULAR - Intelligence Agent Node with Subgraph Architecture
Three modules: Profile Monitoring, Competitive Intelligence, Feed Generation

Updated: Uses Tool Factory pattern for parallel execution safety.
Each agent instance gets its own private set of tools.

Updated: Supports user-defined keywords and profiles from config file.
"""

import json
import uuid
import csv
import os
import logging
from typing import List, Dict, Any
from datetime import datetime
from src.states.intelligenceAgentState import IntelligenceAgentState
from src.utils.tool_factory import create_tool_set
from src.llms.groqllm import GroqLLM
from src.utils.db_manager import (
    Neo4jManager,
    ChromaDBManager,
    extract_post_data,
)

logger = logging.getLogger("Roger.intelligence")


class IntelligenceAgentNode:
    """
    Modular Intelligence Agent - Three independent collection modules.
    Module 1: Profile Monitoring (Twitter, Facebook, LinkedIn, Instagram)
    Module 2: Competitive Intelligence (Competitor mentions, Product reviews, Market analysis)
    Module 3: Feed Generation (Categorize, Summarize, Format)

    Thread Safety:
        Each IntelligenceAgentNode instance creates its own private ToolSet,
        enabling safe parallel execution with other agents.

    User Config:
        Loads user-defined profiles and keywords from src/config/intel_config.json
    """

    def __init__(self, llm=None):
        """Initialize with Groq LLM and private tool set"""
        # Create PRIVATE tool instances for this agent
        # This enables parallel execution without shared state conflicts
        self.tools = create_tool_set()

        if llm is None:
            groq = GroqLLM()
            self.llm = groq.get_llm()
        else:
            self.llm = llm

        # DEFAULT Competitor profiles to monitor
        self.competitor_profiles = {
            "twitter": ["DialogLK", "SLTMobitel", "HutchSriLanka"],
            "facebook": ["DialogAxiata", "SLTMobitel"],
            "linkedin": ["dialog-axiata", "slt-mobitel"],
        }

        # DEFAULT Products to track
        self.product_watchlist = ["Dialog 5G", "SLT Fiber", "Mobitel Data"]

        # Competitor categories
        self.local_competitors = ["Dialog", "SLT", "Mobitel", "Hutch"]
        self.global_competitors = ["Apple", "Samsung", "Google", "Microsoft"]

        # User-defined keywords (loaded from config)
        self.user_keywords: List[str] = []

        # Load and merge user-defined config
        self._load_user_config()

    def _load_user_config(self):
        """
        Load user-defined profiles and keywords from config file.
        Merges with default values - user config ADDS to defaults, doesn't replace.
        """
        config_path = os.path.join(
            os.path.dirname(__file__), "..", "config", "intel_config.json"
        )
        try:
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    user_config = json.load(f)

                # Merge user profiles with defaults (avoid duplicates)
                for platform, profiles in user_config.get("user_profiles", {}).items():
                    if platform in self.competitor_profiles:
                        for profile in profiles:
                            if profile not in self.competitor_profiles[platform]:
                                self.competitor_profiles[platform].append(profile)
                    else:
                        self.competitor_profiles[platform] = profiles

                # Merge user products with defaults
                for product in user_config.get("user_products", []):
                    if product not in self.product_watchlist:
                        self.product_watchlist.append(product)

                # Load user keywords
                self.user_keywords = user_config.get("user_keywords", [])

                total_profiles = sum(
                    len(v) for v in user_config.get("user_profiles", {}).values()
                )
                logger.info(
                    f"[IntelAgent] ✓ Loaded user config: {len(self.user_keywords)} keywords, {total_profiles} profiles, {len(user_config.get('user_products', []))} products"
                )
            else:
                logger.info(
                    f"[IntelAgent] No user config found at {config_path}, using defaults"
                )
        except Exception as e:
            logger.warning(f"[IntelAgent] Could not load user config: {e}")

    # ============================================
    # MODULE 1: PROFILE MONITORING
    # ============================================

    def collect_profile_activity(self, state: IntelligenceAgentState) -> Dict[str, Any]:
        """
        Module 1: Monitor specific competitor profiles
        Uses profile-based scrapers to track competitor social media
        """
        print("[MODULE 1] Profile Monitoring")

        profile_results = []

        # Twitter Profiles
        try:
            twitter_profile_tool = self.tools.get("scrape_twitter_profile")
            if twitter_profile_tool:
                for username in self.competitor_profiles.get("twitter", []):
                    try:
                        data = twitter_profile_tool.invoke(
                            {"username": username, "max_items": 10}
                        )
                        profile_results.append(
                            {
                                "source_tool": "scrape_twitter_profile",
                                "raw_content": str(data),
                                "category": "profile_monitoring",
                                "subcategory": "twitter",
                                "profile": username,
                                "timestamp": datetime.utcnow().isoformat(),
                            }
                        )
                        print(f"  ✓ Scraped Twitter @{username}")
                    except Exception as e:
                        print(f"  ⚠️ Twitter @{username} error: {e}")
        except Exception as e:
            print(f"  ⚠️ Twitter profiles error: {e}")

        # Facebook Profiles
        try:
            fb_profile_tool = self.tools.get("scrape_facebook_profile")
            if fb_profile_tool:
                for page_name in self.competitor_profiles.get("facebook", []):
                    try:
                        url = f"https://www.facebook.com/{page_name}"
                        data = fb_profile_tool.invoke(
                            {"profile_url": url, "max_items": 10}
                        )
                        profile_results.append(
                            {
                                "source_tool": "scrape_facebook_profile",
                                "raw_content": str(data),
                                "category": "profile_monitoring",
                                "subcategory": "facebook",
                                "profile": page_name,
                                "timestamp": datetime.utcnow().isoformat(),
                            }
                        )
                        print(f"  ✓ Scraped Facebook {page_name}")
                    except Exception as e:
                        print(f"  ⚠️ Facebook {page_name} error: {e}")
        except Exception as e:
            print(f"  ⚠️ Facebook profiles error: {e}")

        # LinkedIn Profiles
        try:
            linkedin_profile_tool = self.tools.get("scrape_linkedin_profile")
            if linkedin_profile_tool:
                for company in self.competitor_profiles.get("linkedin", []):
                    try:
                        data = linkedin_profile_tool.invoke(
                            {"company_or_username": company, "max_items": 10}
                        )
                        profile_results.append(
                            {
                                "source_tool": "scrape_linkedin_profile",
                                "raw_content": str(data),
                                "category": "profile_monitoring",
                                "subcategory": "linkedin",
                                "profile": company,
                                "timestamp": datetime.utcnow().isoformat(),
                            }
                        )
                        print(f"  ✓ Scraped LinkedIn {company}")
                    except Exception as e:
                        print(f"  ⚠️ LinkedIn {company} error: {e}")
        except Exception as e:
            print(f"  ⚠️ LinkedIn profiles error: {e}")

        return {
            "worker_results": profile_results,
            "latest_worker_results": profile_results,
        }

    # ============================================
    # MODULE 2: COMPETITIVE INTELLIGENCE COLLECTION
    # ============================================

    def collect_competitor_mentions(
        self, state: IntelligenceAgentState
    ) -> Dict[str, Any]:
        """
        Collect competitor mentions from social media
        """
        print("[MODULE 2A] Competitor Mentions")

        competitor_results = []

        # Twitter competitor tracking
        try:
            twitter_tool = self.tools.get("scrape_twitter")
            if twitter_tool:
                for competitor in self.local_competitors[:3]:
                    try:
                        data = twitter_tool.invoke(
                            {"query": competitor, "max_items": 10}
                        )
                        competitor_results.append(
                            {
                                "source_tool": "scrape_twitter",
                                "raw_content": str(data),
                                "category": "competitor_mention",
                                "subcategory": "twitter",
                                "entity": competitor,
                                "timestamp": datetime.utcnow().isoformat(),
                            }
                        )
                        print(f"  ✓ Tracked {competitor} on Twitter")
                    except Exception as e:
                        print(f"  ⚠️ {competitor} error: {e}")
        except Exception as e:
            print(f"  ⚠️ Twitter tracking error: {e}")

        # Reddit competitor discussions
        try:
            reddit_tool = self.tools.get("scrape_reddit")
            if reddit_tool:
                for competitor in self.local_competitors[:2]:
                    try:
                        data = reddit_tool.invoke(
                            {
                                "keywords": [competitor, f"{competitor} sri lanka"],
                                "limit": 10,
                            }
                        )
                        competitor_results.append(
                            {
                                "source_tool": "scrape_reddit",
                                "raw_content": str(data),
                                "category": "competitor_mention",
                                "subcategory": "reddit",
                                "entity": competitor,
                                "timestamp": datetime.utcnow().isoformat(),
                            }
                        )
                        print(f"  ✓ Tracked {competitor} on Reddit")
                    except Exception as e:
                        print(f"  ⚠️ Reddit {competitor} error: {e}")
        except Exception as e:
            print(f"  ⚠️ Reddit tracking error: {e}")

        return {
            "worker_results": competitor_results,
            "latest_worker_results": competitor_results,
        }

    def collect_product_reviews(self, state: IntelligenceAgentState) -> Dict[str, Any]:
        """
        Collect product reviews and sentiment
        """
        print("[MODULE 2B] Product Reviews")

        review_results = []

        try:
            review_tool = self.tools.get("scrape_product_reviews")
            if review_tool:
                for product in self.product_watchlist:
                    try:
                        data = review_tool.invoke(
                            {
                                "product_keyword": product,
                                "platforms": ["reddit", "twitter"],
                                "max_items": 10,
                            }
                        )
                        review_results.append(
                            {
                                "source_tool": "scrape_product_reviews",
                                "raw_content": str(data),
                                "category": "product_review",
                                "subcategory": "multi_platform",
                                "product": product,
                                "timestamp": datetime.utcnow().isoformat(),
                            }
                        )
                        print(f"  ✓ Collected reviews for {product}")
                    except Exception as e:
                        print(f"  ⚠️ {product} error: {e}")
        except Exception as e:
            print(f"  ⚠️ Product review error: {e}")

        return {
            "worker_results": review_results,
            "latest_worker_results": review_results,
        }

    def collect_market_intelligence(
        self, state: IntelligenceAgentState
    ) -> Dict[str, Any]:
        """
        Collect broader market intelligence
        """
        print("[MODULE 2C] Market Intelligence")

        market_results = []

        # Industry news and trends
        try:
            twitter_tool = self.tools.get("scrape_twitter")
            if twitter_tool:
                for keyword in ["telecom sri lanka", "5G sri lanka", "fiber broadband"]:
                    try:
                        data = twitter_tool.invoke({"query": keyword, "max_items": 10})
                        market_results.append(
                            {
                                "source_tool": "scrape_twitter",
                                "raw_content": str(data),
                                "category": "market_intelligence",
                                "subcategory": "industry_trends",
                                "keyword": keyword,
                                "timestamp": datetime.utcnow().isoformat(),
                            }
                        )
                        print(f"  ✓ Tracked '{keyword}'")
                    except Exception as e:
                        print(f"  ⚠️ '{keyword}' error: {e}")
        except Exception as e:
            print(f"  ⚠️ Market intelligence error: {e}")

        return {
            "worker_results": market_results,
            "latest_worker_results": market_results,
        }

    # ============================================
    # MODULE 3: FEED GENERATION
    # ============================================

    def categorize_intelligence(self, state: IntelligenceAgentState) -> Dict[str, Any]:
        """
        Categorize collected intelligence by competitor, product, geography
        """
        print("[MODULE 3A] Categorizing Intelligence")

        all_results = state.get("worker_results", [])

        # Initialize category buckets
        profile_feeds = {}
        competitor_feeds = {}
        product_feeds = {}
        local_intel = []
        global_intel = []

        for result in all_results:
            category = result.get("category", "")

            # Categorize by type
            if category == "profile_monitoring":
                profile = result.get("profile", "unknown")
                if profile not in profile_feeds:
                    profile_feeds[profile] = []
                profile_feeds[profile].append(result)

            elif category == "competitor_mention":
                entity = result.get("entity", "unknown")
                if entity not in competitor_feeds:
                    competitor_feeds[entity] = []
                competitor_feeds[entity].append(result)

                # Local vs Global classification
                if entity in self.local_competitors:
                    local_intel.append(result)
                elif entity in self.global_competitors:
                    global_intel.append(result)

            elif category == "product_review":
                product = result.get("product", "unknown")
                if product not in product_feeds:
                    product_feeds[product] = []
                product_feeds[product].append(result)

        print(f"  ✓ Categorized {len(profile_feeds)} profiles")
        print(f"  ✓ Categorized {len(competitor_feeds)} competitors")
        print(f"  ✓ Categorized {len(product_feeds)} products")

        return {
            "profile_feeds": profile_feeds,
            "competitor_feeds": competitor_feeds,
            "product_review_feeds": product_feeds,
            "local_intel": local_intel,
            "global_intel": global_intel,
        }

    def generate_llm_summary(self, state: IntelligenceAgentState) -> Dict[str, Any]:
        """
        Generate competitive intelligence summary AND structured insights using LLM
        """
        print("[MODULE 3B] Generating LLM Summary + Competitive Insights")

        all_results = state.get("worker_results", [])
        profile_feeds = state.get("profile_feeds", {})
        competitor_feeds = state.get("competitor_feeds", {})
        product_feeds = state.get("product_review_feeds", {})

        llm_summary = "Competitive intelligence summary unavailable."
        llm_insights = []

        # Prepare summary data
        summary_data = {
            "total_results": len(all_results),
            "profiles_monitored": list(profile_feeds.keys()),
            "competitors_tracked": list(competitor_feeds.keys()),
            "products_analyzed": list(product_feeds.keys()),
            "local_competitors": len(state.get("local_intel", [])),
            "global_competitors": len(state.get("global_intel", [])),
        }

        # Collect sample data for LLM analysis
        sample_posts = []
        for profile, posts in profile_feeds.items():
            if isinstance(posts, list):
                for p in posts[:2]:
                    text = (
                        p.get("text", "")
                        or p.get("title", "")
                        or p.get("raw_content", "")[:200]
                    )
                    if text:
                        sample_posts.append(f"[PROFILE: {profile}] {text[:150]}")

        for competitor, posts in competitor_feeds.items():
            if isinstance(posts, list):
                for p in posts[:2]:
                    text = (
                        p.get("text", "")
                        or p.get("title", "")
                        or p.get("raw_content", "")[:200]
                    )
                    if text:
                        sample_posts.append(f"[COMPETITOR: {competitor}] {text[:150]}")

        posts_text = (
            "\n".join(sample_posts[:10])
            if sample_posts
            else "No detailed data available"
        )

        prompt = f"""Analyze this competitive intelligence data and generate:
1. A strategic 3-sentence executive summary
2. Up to 5 unique business intelligence insights

Data Overview:
- Total intelligence: {summary_data['total_results']} items
- Competitors tracked: {', '.join(summary_data['competitors_tracked']) or 'None'}
- Products analyzed: {', '.join(summary_data['products_analyzed']) or 'None'}

Sample Data:
{posts_text}

Respond in this exact JSON format:
{{
    "executive_summary": "Strategic 3-sentence summary of competitive landscape",
    "insights": [
        {{"summary": "Unique competitive insight #1", "severity": "low/medium/high", "impact_type": "risk/opportunity"}},
        {{"summary": "Unique competitive insight #2", "severity": "low/medium/high", "impact_type": "risk/opportunity"}}
    ]
}}

Rules:
- Generate actionable business intelligence, not just data descriptions
- Identify competitive threats as "risk", business opportunities as "opportunity"
- Severity: high=urgent action needed, medium=monitor closely, low=informational

JSON only:"""

        try:
            response = self.llm.invoke(prompt)
            content = (
                response.content if hasattr(response, "content") else str(response)
            )

            # Parse JSON response
            import re

            content = content.strip()
            if content.startswith("```"):
                content = re.sub(r"^```\w*\n?", "", content)
                content = re.sub(r"\n?```$", "", content)

            result = json.loads(content)
            llm_summary = result.get("executive_summary", llm_summary)
            llm_insights = result.get("insights", [])

            print(f"  ✓ LLM generated {len(llm_insights)} competitive insights")

        except json.JSONDecodeError as e:
            print(f"  ⚠️ JSON parse error: {e}")
            # Fallback to simple summary
            try:
                fallback_prompt = f"Summarize this competitive intelligence in 3 sentences:\n{posts_text[:1500]}"
                response = self.llm.invoke(fallback_prompt)
                llm_summary = (
                    response.content if hasattr(response, "content") else str(response)
                )
            except Exception as fallback_error:
                print(f"  ⚠️ LLM fallback also failed: {fallback_error}")
        except Exception as e:
            print(f"  ⚠️ LLM error: {e}")

        return {
            "llm_summary": llm_summary,
            "llm_insights": llm_insights,
            "structured_output": summary_data,
        }

    def format_final_output(self, state: IntelligenceAgentState) -> Dict[str, Any]:
        """
        Module 3C: Format final competitive intelligence feed with LLM-enhanced insights
        """
        print("[MODULE 3C] Formatting Final Output")

        profile_feeds = state.get("profile_feeds", {})
        competitor_feeds = state.get("competitor_feeds", {})
        product_feeds = state.get("product_review_feeds", {})
        llm_summary = state.get("llm_summary", "No summary available")
        llm_insights = state.get("llm_insights", [])  # NEW: Get LLM-generated insights
        local_intel = state.get("local_intel", [])
        global_intel = state.get("global_intel", [])

        profile_count = len(profile_feeds)
        competitor_count = len(competitor_feeds)
        product_count = len(product_feeds)
        total_results = len(state.get("worker_results", []))

        bulletin = f"""📊 COMPREHENSIVE COMPETITIVE INTELLIGENCE FEED
{datetime.utcnow().strftime("%d %b %Y • %H:%M UTC")}

🎯 EXECUTIVE SUMMARY (AI-Generated)
{llm_summary}

📈 DATA COLLECTION STATS
• Profile Monitoring: {profile_count} profiles tracked
• Competitor Mentions: {competitor_count} competitors analyzed
• Product Reviews: {product_count} products monitored
• Total Intelligence: {total_results} items

🔍 COMPETITIVE LANDSCAPE
• Local Market: {len(local_intel)} data points
• Global Market: {len(global_intel)} data points

🌐 STRUCTURED DATA AVAILABLE
• Profile Activity: {', '.join([p for p in profile_feeds.keys()][:5])}
• Competitor Tracking: {', '.join([c for c in competitor_feeds.keys()][:5])}
• Product Analysis: {', '.join([p for p in product_feeds.keys()][:3])}

Source: Multi-platform competitive intelligence (Twitter, Facebook, LinkedIn, Instagram, Reddit)
"""

        # Create integration output with structured data
        structured_feeds = {
            "profiles": profile_feeds,
            "competitors": competitor_feeds,
            "products": product_feeds,
            "local_intel": local_intel,
            "global_intel": global_intel,
        }

        # Create list for domain_insights (FRONTEND COMPATIBLE)
        domain_insights = []
        timestamp = datetime.utcnow().isoformat()

        # PRIORITY 1: Add LLM-generated unique insights (curated and actionable)
        for insight in llm_insights:
            if isinstance(insight, dict) and insight.get("summary"):
                domain_insights.append(
                    {
                        "source_event_id": str(uuid.uuid4()),
                        "domain": "intelligence",
                        "summary": f"🎯 {insight.get('summary', '')}",  # Mark as AI-analyzed
                        "severity": insight.get("severity", "medium"),
                        "impact_type": insight.get("impact_type", "risk"),
                        "timestamp": timestamp,
                        "is_llm_generated": True,
                    }
                )

        print(f"  ✓ Added {len(llm_insights)} LLM-generated competitive insights")

        # PRIORITY 2: Add raw data only as fallback if LLM didn't generate enough
        if len(domain_insights) < 5:
            # Add competitor insights as fallback
            for competitor, posts in competitor_feeds.items():
                if not isinstance(posts, list):
                    continue
                for post in posts[:3]:
                    post_text = post.get("text", "") or post.get("title", "")
                    if not post_text or len(post_text) < 20:
                        continue
                    severity = (
                        "high"
                        if any(
                            kw in post_text.lower()
                            for kw in ["launch", "expansion", "acquisition"]
                        )
                        else "medium"
                    )
                    domain_insights.append(
                        {
                            "source_event_id": str(uuid.uuid4()),
                            "domain": "intelligence",
                            "summary": f"Competitor ({competitor}): {post_text[:200]}",
                            "severity": severity,
                            "impact_type": "risk",
                            "timestamp": timestamp,
                            "is_llm_generated": False,
                        }
                    )

        # Add executive summary insight
        domain_insights.append(
            {
                "source_event_id": str(uuid.uuid4()),
                "structured_data": structured_feeds,
                "domain": "intelligence",
                "summary": f"📊 Business Intelligence Summary: {llm_summary[:300]}",
                "severity": "medium",
                "impact_type": "risk",
                "is_llm_generated": True,
            }
        )

        print(f"  ✓ Created {len(domain_insights)} total intelligence insights")

        return {
            "final_feed": bulletin,
            "feed_history": [bulletin],
            "domain_insights": domain_insights,
        }

    # ============================================
    # MODULE 4: FEED AGGREGATOR (Neo4j + ChromaDB + CSV)
    # ============================================

    def aggregate_and_store_feeds(
        self, state: IntelligenceAgentState
    ) -> Dict[str, Any]:
        """
        Module 4: Aggregate, deduplicate, and store feeds
        - Check uniqueness using Neo4j (URL + content hash)
        - Store unique posts in Neo4j
        - Store unique posts in ChromaDB for RAG
        - Append to CSV dataset for ML training
        """
        print("[MODULE 4] Aggregating and Storing Feeds")

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
        dataset_dir = os.getenv("DATASET_PATH", "./datasets/intelligence_feeds")
        os.makedirs(dataset_dir, exist_ok=True)

        csv_filename = f"intelligence_feeds_{datetime.now().strftime('%Y%m')}.csv"
        csv_path = os.path.join(dataset_dir, csv_filename)

        # CSV headers
        csv_headers = [
            "post_id",
            "timestamp",
            "platform",
            "category",
            "entity",
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
                    entity = (
                        worker_result.get("entity", "")
                        or worker_result.get("profile", "")
                        or worker_result.get("product", "")
                    )

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
                            if not posts and (data.get("title") or data.get("text")):
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

                            # Override entity if from worker result
                            if entity and "metadata" in post_data:
                                post_data["metadata"]["entity"] = entity

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
                                    "entity": entity,
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
