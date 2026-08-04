"""
src/nodes/socialAgentNode.py
MODULAR - Social Agent Node with Subgraph Architecture
Monitors trending topics, events, people, social intelligence across geographic scopes

Updated: Uses Tool Factory pattern for parallel execution safety.
Each agent instance gets its own private set of tools.

Updated: Now loads user-defined keywords and profiles from intel config.
"""

import json
import uuid
import os
from typing import Dict, Any, List
from datetime import datetime
from src.states.socialAgentState import SocialAgentState
from src.utils.tool_factory import create_tool_set
from src.llms.groqllm import GroqLLM


def load_intel_config() -> dict:
    """Load intel config from JSON file (same as main.py)."""
    config_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "data", "intel_config.json"
    )
    default_config = {
        "user_profiles": {"twitter": [], "facebook": [], "linkedin": []},
        "user_keywords": [],
        "user_products": [],
    }
    try:
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default_config


class SocialAgentNode:
    """
    Modular Social Agent - Geographic social intelligence collection.
    Module 1: Trending Topics (Sri Lanka specific trends)
    Module 2: Social Media (Sri Lanka, Asia, World scopes)
    Module 3: Feed Generation (Categorize, Summarize, Format)
    Module 4: User-Defined Keywords & Profiles (from frontend config)

    Thread Safety:
        Each SocialAgentNode instance creates its own private ToolSet,
        enabling safe parallel execution with other agents.
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

        # Load user-defined intel config (keywords, profiles, products)
        self.intel_config = load_intel_config()
        self.user_keywords = self.intel_config.get("user_keywords", [])
        self.user_profiles = self.intel_config.get("user_profiles", {})
        self.user_products = self.intel_config.get("user_products", [])

        print(
            f"[SocialAgent] Loaded {len(self.user_keywords)} user keywords, "
            f"{sum(len(v) for v in self.user_profiles.values())} profiles"
        )

        # Geographic scopes
        self.geographic_scopes = {
            "sri_lanka": ["sri lanka", "colombo", "srilanka"],
            "asia": [
                "india",
                "pakistan",
                "bangladesh",
                "maldives",
                "singapore",
                "malaysia",
                "thailand",
            ],
            "world": ["global", "international", "breaking news", "world events"],
        }

        # Trending categories
        self.trending_categories = [
            "events",
            "people",
            "viral",
            "breaking",
            "technology",
            "culture",
        ]

    # ============================================
    # MODULE 1: TRENDING TOPICS COLLECTION
    # ============================================

    def collect_sri_lanka_trends(self, state: SocialAgentState) -> Dict[str, Any]:
        """
        Module 1: Collect Sri Lankan trending topics
        """
        print("[MODULE 1] Collecting Sri Lankan Trending Topics")

        trending_results = []

        # Twitter - Sri Lanka Trends
        try:
            twitter_tool = self.tools.get("scrape_twitter")
            if twitter_tool:
                twitter_data = twitter_tool.invoke(
                    {"query": "sri lanka trending viral", "max_items": 20}
                )
                trending_results.append(
                    {
                        "source_tool": "scrape_twitter",
                        "raw_content": str(twitter_data),
                        "category": "trending",
                        "scope": "sri_lanka",
                        "platform": "twitter",
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
                print("  ✓ Twitter Sri Lanka Trends")
        except Exception as e:
            print(f"  ⚠️ Twitter error: {e}")

        # Reddit - Sri Lanka
        try:
            reddit_tool = self.tools.get("scrape_reddit")
            if reddit_tool:
                reddit_data = reddit_tool.invoke(
                    {
                        "keywords": [
                            "sri lanka trending",
                            "sri lanka viral",
                            "sri lanka news",
                        ],
                        "limit": 20,
                        "subreddit": "srilanka",
                    }
                )
                trending_results.append(
                    {
                        "source_tool": "scrape_reddit",
                        "raw_content": str(reddit_data),
                        "category": "trending",
                        "scope": "sri_lanka",
                        "platform": "reddit",
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
                print("  ✓ Reddit Sri Lanka Trends")
        except Exception as e:
            print(f"  ⚠️ Reddit error: {e}")

        return {
            "worker_results": trending_results,
            "latest_worker_results": trending_results,
        }

    # ============================================
    # MODULE 2: SOCIAL MEDIA COLLECTION
    # ============================================

    def collect_sri_lanka_social_media(self, state: SocialAgentState) -> Dict[str, Any]:
        """
        Module 2A: Collect Sri Lankan social media across all platforms
        """
        print("[MODULE 2A] Collecting Sri Lankan Social Media")

        social_results = []

        # Twitter - Sri Lanka Events & People
        try:
            twitter_tool = self.tools.get("scrape_twitter")
            if twitter_tool:
                twitter_data = twitter_tool.invoke(
                    {"query": "sri lanka events people celebrities", "max_items": 15}
                )
                social_results.append(
                    {
                        "source_tool": "scrape_twitter",
                        "raw_content": str(twitter_data),
                        "category": "social",
                        "scope": "sri_lanka",
                        "platform": "twitter",
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
                print("  ✓ Twitter Sri Lanka Social")
        except Exception as e:
            print(f"  ⚠️ Twitter error: {e}")

        # Facebook - Sri Lanka
        try:
            facebook_tool = self.tools.get("scrape_facebook")
            if facebook_tool:
                facebook_data = facebook_tool.invoke(
                    {
                        "keywords": ["sri lanka events", "sri lanka trending"],
                        "max_items": 10,
                    }
                )
                social_results.append(
                    {
                        "source_tool": "scrape_facebook",
                        "raw_content": str(facebook_data),
                        "category": "social",
                        "scope": "sri_lanka",
                        "platform": "facebook",
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
                print("  ✓ Facebook Sri Lanka Social")
        except Exception as e:
            print(f"  ⚠️ Facebook error: {e}")

        # LinkedIn - Sri Lanka Professional
        try:
            linkedin_tool = self.tools.get("scrape_linkedin")
            if linkedin_tool:
                linkedin_data = linkedin_tool.invoke(
                    {
                        "keywords": ["sri lanka events", "sri lanka people"],
                        "max_items": 5,
                    }
                )
                social_results.append(
                    {
                        "source_tool": "scrape_linkedin",
                        "raw_content": str(linkedin_data),
                        "category": "social",
                        "scope": "sri_lanka",
                        "platform": "linkedin",
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
                print("  ✓ LinkedIn Sri Lanka Professional")
        except Exception as e:
            print(f"  ⚠️ LinkedIn error: {e}")

        # Instagram - Sri Lanka
        try:
            instagram_tool = self.tools.get("scrape_instagram")
            if instagram_tool:
                instagram_data = instagram_tool.invoke(
                    {"keywords": ["srilankaevents", "srilankatrending"], "max_items": 5}
                )
                social_results.append(
                    {
                        "source_tool": "scrape_instagram",
                        "raw_content": str(instagram_data),
                        "category": "social",
                        "scope": "sri_lanka",
                        "platform": "instagram",
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
                print("  ✓ Instagram Sri Lanka")
        except Exception as e:
            print(f"  ⚠️ Instagram error: {e}")

        return {
            "worker_results": social_results,
            "social_media_results": social_results,
        }

    def collect_asia_social_media(self, state: SocialAgentState) -> Dict[str, Any]:
        """
        Module 2B: Collect Asian regional social media
        """
        print("[MODULE 2B] Collecting Asian Regional Social Media")

        asia_results = []

        # Twitter - Asian Events
        try:
            twitter_tool = self.tools.get("scrape_twitter")
            if twitter_tool:
                twitter_data = twitter_tool.invoke(
                    {
                        "query": "asia trending india pakistan bangladesh",
                        "max_items": 15,
                    }
                )
                asia_results.append(
                    {
                        "source_tool": "scrape_twitter",
                        "raw_content": str(twitter_data),
                        "category": "social",
                        "scope": "asia",
                        "platform": "twitter",
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
                print("  ✓ Twitter Asia Trends")
        except Exception as e:
            print(f"  ⚠️ Twitter error: {e}")

        # Facebook - Asia
        try:
            facebook_tool = self.tools.get("scrape_facebook")
            if facebook_tool:
                facebook_data = facebook_tool.invoke(
                    {"keywords": ["asia trending", "india events"], "max_items": 10}
                )
                asia_results.append(
                    {
                        "source_tool": "scrape_facebook",
                        "raw_content": str(facebook_data),
                        "category": "social",
                        "scope": "asia",
                        "platform": "facebook",
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
                print("  ✓ Facebook Asia")
        except Exception as e:
            print(f"  ⚠️ Facebook error: {e}")

        # Reddit - Asian subreddits
        try:
            reddit_tool = self.tools.get("scrape_reddit")
            if reddit_tool:
                reddit_data = reddit_tool.invoke(
                    {
                        "keywords": ["asia trending", "india", "pakistan"],
                        "limit": 10,
                        "subreddit": "asia",
                    }
                )
                asia_results.append(
                    {
                        "source_tool": "scrape_reddit",
                        "raw_content": str(reddit_data),
                        "category": "social",
                        "scope": "asia",
                        "platform": "reddit",
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
                print("  ✓ Reddit Asia")
        except Exception as e:
            print(f"  ⚠️ Reddit error: {e}")

        return {"worker_results": asia_results, "social_media_results": asia_results}

    def collect_world_social_media(self, state: SocialAgentState) -> Dict[str, Any]:
        """
        Module 2C: Collect world/global trending topics
        """
        print("[MODULE 2C] Collecting World Trending Topics")

        world_results = []

        # Twitter - World Trends
        try:
            twitter_tool = self.tools.get("scrape_twitter")
            if twitter_tool:
                twitter_data = twitter_tool.invoke(
                    {"query": "world trending global breaking news", "max_items": 15}
                )
                world_results.append(
                    {
                        "source_tool": "scrape_twitter",
                        "raw_content": str(twitter_data),
                        "category": "social",
                        "scope": "world",
                        "platform": "twitter",
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
                print("  ✓ Twitter World Trends")
        except Exception as e:
            print(f"  ⚠️ Twitter error: {e}")

        # Reddit - World News
        try:
            reddit_tool = self.tools.get("scrape_reddit")
            if reddit_tool:
                reddit_data = reddit_tool.invoke(
                    {
                        "keywords": ["breaking", "trending", "viral"],
                        "limit": 15,
                        "subreddit": "worldnews",
                    }
                )
                world_results.append(
                    {
                        "source_tool": "scrape_reddit",
                        "raw_content": str(reddit_data),
                        "category": "social",
                        "scope": "world",
                        "platform": "reddit",
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
                print("  ✓ Reddit World News")
        except Exception as e:
            print(f"  ⚠️ Reddit error: {e}")

        return {"worker_results": world_results, "social_media_results": world_results}

    def collect_user_defined_targets(self, state: SocialAgentState) -> Dict[str, Any]:
        """
        Module 2D: Collect data for USER-DEFINED keywords and profiles.
        These are configured via the frontend Intelligence Settings UI.
        """
        print("[MODULE 2D] Collecting User-Defined Targets")

        user_results = []

        # Reload config to get latest user settings
        self.intel_config = load_intel_config()
        self.user_keywords = self.intel_config.get("user_keywords", [])
        self.user_profiles = self.intel_config.get("user_profiles", {})
        self.user_products = self.intel_config.get("user_products", [])

        # Skip if no user config
        if not self.user_keywords and not any(self.user_profiles.values()):
            print("  ⏭️ No user-defined targets configured")
            return {"worker_results": [], "user_target_results": []}

        # ============================================
        # Scrape USER KEYWORDS across Twitter
        # ============================================
        if self.user_keywords:
            print(f"  📝 Scraping {len(self.user_keywords)} user keywords...")
            twitter_tool = self.tools.get("scrape_twitter")

            for keyword in self.user_keywords[:10]:  # Limit to 10 keywords
                try:
                    if twitter_tool:
                        twitter_data = twitter_tool.invoke(
                            {"query": keyword, "max_items": 5}
                        )
                        user_results.append(
                            {
                                "source_tool": "scrape_twitter",
                                "raw_content": str(twitter_data),
                                "category": "user_keyword",
                                "scope": "sri_lanka",
                                "platform": "twitter",
                                "keyword": keyword,
                                "timestamp": datetime.utcnow().isoformat(),
                            }
                        )
                        print(f"    ✓ Keyword: '{keyword}'")
                except Exception as e:
                    print(f"    ⚠️ Keyword '{keyword}' error: {e}")

        # ============================================
        # Scrape USER PRODUCTS
        # ============================================
        if self.user_products:
            print(f"  📦 Scraping {len(self.user_products)} user products...")
            twitter_tool = self.tools.get("scrape_twitter")

            for product in self.user_products[:5]:  # Limit to 5 products
                try:
                    if twitter_tool:
                        twitter_data = twitter_tool.invoke(
                            {
                                "query": f"{product} review OR {product} Sri Lanka",
                                "max_items": 3,
                            }
                        )
                        user_results.append(
                            {
                                "source_tool": "scrape_twitter",
                                "raw_content": str(twitter_data),
                                "category": "user_product",
                                "scope": "sri_lanka",
                                "platform": "twitter",
                                "product": product,
                                "timestamp": datetime.utcnow().isoformat(),
                            }
                        )
                        print(f"    ✓ Product: '{product}'")
                except Exception as e:
                    print(f"    ⚠️ Product '{product}' error: {e}")

        # ============================================
        # Scrape USER TWITTER PROFILES
        # ============================================
        twitter_profiles = self.user_profiles.get("twitter", [])
        if twitter_profiles:
            print(f"  👤 Scraping {len(twitter_profiles)} Twitter profiles...")
            twitter_tool = self.tools.get("scrape_twitter")

            for profile in twitter_profiles[:10]:  # Limit to 10 profiles
                try:
                    # Clean profile handle
                    handle = profile.replace("@", "").strip()
                    if twitter_tool:
                        # Search for tweets mentioning this profile
                        twitter_data = twitter_tool.invoke(
                            {"query": f"from:{handle} OR @{handle}", "max_items": 5}
                        )
                        user_results.append(
                            {
                                "source_tool": "scrape_twitter",
                                "raw_content": str(twitter_data),
                                "category": "user_profile",
                                "scope": "sri_lanka",
                                "platform": "twitter",
                                "profile": f"@{handle}",
                                "timestamp": datetime.utcnow().isoformat(),
                            }
                        )
                        print(f"    ✓ Profile: @{handle}")
                except Exception as e:
                    print(f"    ⚠️ Profile @{profile} error: {e}")

        print(f"  ✅ User targets: {len(user_results)} results collected")
        return {"worker_results": user_results, "user_target_results": user_results}

    # ============================================
    # MODULE 3: FEED GENERATION
    # ============================================

    def categorize_by_geography(self, state: SocialAgentState) -> Dict[str, Any]:
        """
        Module 3A: Categorize all collected results by geographic scope
        """
        print("[MODULE 3A] Categorizing Results by Geography")

        all_results = state.get("worker_results", []) or []

        # Initialize categories
        sri_lanka_data = []
        asia_data = []
        world_data = []
        geographic_data = {"sri_lanka": [], "asia": [], "world": []}

        for r in all_results:
            scope = r.get("scope", "unknown")
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
                if scope == "sri_lanka":
                    sri_lanka_data.extend(posts[:10])
                    geographic_data["sri_lanka"].extend(posts[:10])
                elif scope == "asia":
                    asia_data.extend(posts[:10])
                    geographic_data["asia"].extend(posts[:10])
                elif scope == "world":
                    world_data.extend(posts[:10])
                    geographic_data["world"].extend(posts[:10])

            except Exception:
                continue

        # Create structured feeds
        structured_feeds = {
            "sri lanka": sri_lanka_data,
            "asia": asia_data,
            "world": world_data,
        }

        print(
            f"  ✓ Categorized: {len(sri_lanka_data)} Sri Lanka, {len(asia_data)} Asia, {len(world_data)} World"
        )

        return {
            "structured_output": structured_feeds,
            "geographic_feeds": geographic_data,
            "sri_lanka_feed": sri_lanka_data,
            "asia_feed": asia_data,
            "world_feed": world_data,
        }

    def generate_llm_summary(self, state: SocialAgentState) -> Dict[str, Any]:
        """
        Module 3B: Use Groq LLM to generate executive summary AND structured insights
        """
        print("[MODULE 3B] Generating LLM Summary + Structured Insights")

        structured_feeds = state.get("structured_output", {})
        llm_summary = "AI summary currently unavailable."
        llm_insights = []

        try:
            # Collect sample posts for analysis
            all_posts = []
            for region, posts in structured_feeds.items():
                for p in posts[:5]:  # Top 5 per region
                    text = p.get("text", "") or p.get("title", "")
                    if text and len(text) > 20:
                        all_posts.append(f"[{region.upper()}] {text[:200]}")

            if not all_posts:
                return {"llm_summary": llm_summary, "llm_insights": []}

            posts_text = "\n".join(all_posts[:15])

            # Generate summary AND structured insights
            analysis_prompt = f"""Analyze these social media posts from Sri Lanka and the region. Generate:
1. A 3-sentence executive summary of key trends
2. Up to 5 unique intelligence insights

Posts:
{posts_text}

Respond in this exact JSON format:
{{
    "executive_summary": "Brief 3-sentence summary of key social trends and developments",
    "insights": [
        {{"summary": "Unique insight #1 (not copying post text)", "severity": "low/medium/high", "impact_type": "risk/opportunity"}},
        {{"summary": "Unique insight #2", "severity": "low/medium/high", "impact_type": "risk/opportunity"}}
    ]
}}

Rules:
- Generate NEW insights, don't just copy post text
- Identify patterns and emerging trends
- Classify severity based on potential impact
- Mark positive developments as "opportunity", concerning ones as "risk"

JSON only, no explanation:"""

            llm_response = self.llm.invoke(analysis_prompt)
            content = (
                llm_response.content
                if hasattr(llm_response, "content")
                else str(llm_response)
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

            print(f"  ✓ LLM generated {len(llm_insights)} unique insights")

        except json.JSONDecodeError as e:
            print(f"  ⚠️ JSON parse error: {e}")
            # Fallback to simple summary
            try:
                fallback_prompt = f"Summarize these social media trends in 3 sentences:\n{posts_text[:1500]}"
                response = self.llm.invoke(fallback_prompt)
                llm_summary = (
                    response.content if hasattr(response, "content") else str(response)
                )
            except Exception as fallback_error:
                print(f"  ⚠️ LLM fallback also failed: {fallback_error}")
        except Exception as e:
            print(f"  ⚠️ LLM Error: {e}")

        return {"llm_summary": llm_summary, "llm_insights": llm_insights}

    def format_final_output(self, state: SocialAgentState) -> Dict[str, Any]:
        """
        Module 3C: Format final feed output with LLM-enhanced insights
        """
        print("[MODULE 3C] Formatting Final Output")

        llm_summary = state.get("llm_summary", "No summary available")
        llm_insights = state.get("llm_insights", [])  # NEW: Get LLM-generated insights
        structured_feeds = state.get("structured_output", {})

        trending_count = len(
            [
                r
                for r in state.get("worker_results", [])
                if r.get("category") == "trending"
            ]
        )
        social_count = len(
            [
                r
                for r in state.get("worker_results", [])
                if r.get("category") == "social"
            ]
        )

        sri_lanka_items = len(structured_feeds.get("sri lanka", []))
        asia_items = len(structured_feeds.get("asia", []))
        world_items = len(structured_feeds.get("world", []))

        bulletin = f"""🌏 COMPREHENSIVE SOCIAL INTELLIGENCE FEED
{datetime.utcnow().strftime("%d %b %Y • %H:%M UTC")}

📊 EXECUTIVE SUMMARY (AI-Generated)
{llm_summary}

📈 DATA COLLECTION STATS
• Trending Topics: {trending_count} items
• Social Media Posts: {social_count} items
• Geographic Coverage: Sri Lanka, Asia, World

🔍 GEOGRAPHIC BREAKDOWN
• Sri Lanka: {sri_lanka_items} trending items
• Asia: {asia_items} regional items
• World: {world_items} global items

🌐 COVERAGE CATEGORIES
• Events: Public gatherings, launches, announcements
• People: Influencers, celebrities, public figures
• Viral Content: Trending posts, hashtags, memes
• Breaking: Real-time developments

🎯 INTELLIGENCE FOCUS
Monitoring social sentiment, trending topics, events, and people across:
- Sri Lanka (local intelligence)
- Asia (regional context: India, Pakistan, Bangladesh, ASEAN)
- World (global trends affecting local sentiment)

Source: Multi-platform aggregation (Twitter, Facebook, LinkedIn, Instagram, Reddit)
"""

        # Create list for domain_insights (FRONTEND COMPATIBLE)
        domain_insights = []
        timestamp = datetime.utcnow().isoformat()

        # PRIORITY 1: Add LLM-generated unique insights (these are curated and unique)
        for insight in llm_insights:
            if isinstance(insight, dict) and insight.get("summary"):
                domain_insights.append(
                    {
                        "source_event_id": str(uuid.uuid4()),
                        "domain": "social",
                        "summary": f"🔍 {insight.get('summary', '')}",  # Mark as AI-analyzed
                        "severity": insight.get("severity", "medium"),
                        "impact_type": insight.get("impact_type", "risk"),
                        "timestamp": timestamp,
                        "is_llm_generated": True,  # Flag for frontend
                    }
                )

        print(f"  ✓ Added {len(llm_insights)} LLM-generated insights")

        # PRIORITY 2: Add top raw posts only if we need more (fallback)
        # Only add raw posts if LLM didn't generate enough insights
        if len(domain_insights) < 5:
            # Sri Lankan districts for geographic tagging
            districts = [
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

            # Add Sri Lanka posts as fallback
            sri_lanka_data = structured_feeds.get("sri lanka", [])
            for post in sri_lanka_data[:5]:
                post_text = post.get("text", "") or post.get("title", "")
                if not post_text or len(post_text) < 20:
                    continue

                # Detect district
                detected_district = "Sri Lanka"
                for district in districts:
                    if district.lower() in post_text.lower():
                        detected_district = district.title()
                        break

                # Determine severity
                severity = "low"
                if any(
                    kw in post_text.lower()
                    for kw in ["protest", "riot", "emergency", "violence", "crisis"]
                ):
                    severity = "high"
                elif any(
                    kw in post_text.lower()
                    for kw in ["trending", "viral", "breaking", "update"]
                ):
                    severity = "medium"

                domain_insights.append(
                    {
                        "source_event_id": str(uuid.uuid4()),
                        "domain": "social",
                        "summary": f"{detected_district}: {post_text[:200]}",
                        "severity": severity,
                        "impact_type": (
                            "risk" if severity in ["high", "medium"] else "opportunity"
                        ),
                        "timestamp": timestamp,
                        "is_llm_generated": False,
                    }
                )

        # Add executive summary insight
        domain_insights.append(
            {
                "source_event_id": str(uuid.uuid4()),
                "structured_data": structured_feeds,
                "domain": "social",
                "summary": f"📊 Social Intelligence Summary: {llm_summary[:300]}",
                "severity": "medium",
                "impact_type": "risk",
                "is_llm_generated": True,
            }
        )

        print(f"  ✓ Created {len(domain_insights)} total social intelligence insights")

        return {
            "final_feed": bulletin,
            "feed_history": [bulletin],
            "domain_insights": domain_insights,
        }

    # ============================================
    # MODULE 4: FEED AGGREGATOR & STORAGE
    # ============================================

    def aggregate_and_store_feeds(self, state: SocialAgentState) -> Dict[str, Any]:
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
        dataset_dir = os.getenv("DATASET_PATH", "./datasets/social_feeds")
        os.makedirs(dataset_dir, exist_ok=True)

        csv_filename = f"social_feeds_{datetime.now().strftime('%Y%m')}.csv"
        csv_path = os.path.join(dataset_dir, csv_filename)

        # CSV headers
        csv_headers = [
            "post_id",
            "timestamp",
            "platform",
            "category",
            "scope",
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
                    platform = worker_result.get("platform", "unknown")
                    source_tool = worker_result.get("source_tool", "")
                    scope = worker_result.get("scope", "")

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
                                platform=platform,
                                source_tool=source_tool,
                            )

                            if not post_data:
                                continue

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
                                    "scope": scope,
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
