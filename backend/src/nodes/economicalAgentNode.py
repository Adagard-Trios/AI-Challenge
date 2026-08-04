"""
src/nodes/economicalAgentNode.py
MODULAR - Economical Agent Node with Subgraph Architecture
Three modules: Official Sources, Social Media Collection, Feed Generation

Updated: Uses Tool Factory pattern for parallel execution safety.
Each agent instance gets its own private set of tools.
"""

import json
import uuid
from typing import Dict, Any
from datetime import datetime
from src.states.economicalAgentState import EconomicalAgentState
from src.utils.tool_factory import create_tool_set
from src.llms.groqllm import GroqLLM


class EconomicalAgentNode:
    """
    Modular Economical Agent - Three independent collection modules.
    Module 1: Official Sources (CSE Stock Data, Local Economic News)
    Module 2: Social Media (National, Sectoral, World)
    Module 3: Feed Generation (Categorize, Summarize, Format)

    Thread Safety:
        Each EconomicalAgentNode instance creates its own private ToolSet,
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

        # Economic sectors to monitor
        self.sectors = [
            "banking",
            "finance",
            "manufacturing",
            "tourism",
            "agriculture",
            "technology",
            "real estate",
            "retail",
        ]

        # Key sectors to monitor per run (to avoid overwhelming)
        self.key_sectors = ["banking", "manufacturing", "tourism", "technology"]

    # ============================================
    # MODULE 1: OFFICIAL SOURCES COLLECTION
    # ============================================

    def collect_official_sources(self, state: EconomicalAgentState) -> Dict[str, Any]:
        """
        Module 1: Collect official economic sources in parallel
        - CSE Stock Data
        - Local Economic News
        """
        print("[MODULE 1] Collecting Official Economic Sources")

        official_results = []

        # CSE Stock Data
        try:
            stock_tool = self.tools.get("scrape_cse_stock_data")
            if stock_tool:
                stock_data = stock_tool.invoke(
                    {"symbol": "ASPI", "period": "5d", "interval": "1h"}
                )
                official_results.append(
                    {
                        "source_tool": "scrape_cse_stock_data",
                        "raw_content": str(stock_data),
                        "category": "official",
                        "subcategory": "stock_market",
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
                print("  ✓ Scraped CSE Stock Data")
        except Exception as e:
            print(f"  ⚠️ CSE Stock error: {e}")

        # Local Economic News
        try:
            news_tool = self.tools.get("scrape_local_news")
            if news_tool:
                news_data = news_tool.invoke(
                    {
                        "keywords": [
                            "sri lanka economy",
                            "sri lanka market",
                            "sri lanka business",
                            "sri lanka investment",
                            "sri lanka inflation",
                            "sri lanka IMF",
                        ],
                        "max_articles": 20,
                    }
                )
                official_results.append(
                    {
                        "source_tool": "scrape_local_news",
                        "raw_content": str(news_data),
                        "category": "official",
                        "subcategory": "news",
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
                print("  ✓ Scraped Local Economic News")
        except Exception as e:
            print(f"  ⚠️ Local News error: {e}")

        return {
            "worker_results": official_results,
            "latest_worker_results": official_results,
        }

    # ============================================
    # MODULE 2: SOCIAL MEDIA COLLECTION
    # ============================================

    def collect_national_social_media(
        self, state: EconomicalAgentState
    ) -> Dict[str, Any]:
        """
        Module 2A: Collect national-level social media for economy
        """
        print("[MODULE 2A] Collecting National Economic Social Media")

        social_results = []

        # Twitter - National Economy
        try:
            twitter_tool = self.tools.get("scrape_twitter")
            if twitter_tool:
                twitter_data = twitter_tool.invoke(
                    {"query": "sri lanka economy market business", "max_items": 15}
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
                print("  ✓ Twitter National Economy")
        except Exception as e:
            print(f"  ⚠️ Twitter error: {e}")

        # Facebook - National Economy
        try:
            facebook_tool = self.tools.get("scrape_facebook")
            if facebook_tool:
                facebook_data = facebook_tool.invoke(
                    {
                        "keywords": ["sri lanka economy", "sri lanka business"],
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
                print("  ✓ Facebook National Economy")
        except Exception as e:
            print(f"  ⚠️ Facebook error: {e}")

        # LinkedIn - National Economy
        try:
            linkedin_tool = self.tools.get("scrape_linkedin")
            if linkedin_tool:
                linkedin_data = linkedin_tool.invoke(
                    {
                        "keywords": ["sri lanka economy", "sri lanka market"],
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
                print("  ✓ LinkedIn National Economy")
        except Exception as e:
            print(f"  ⚠️ LinkedIn error: {e}")

        # Instagram - National Economy
        try:
            instagram_tool = self.tools.get("scrape_instagram")
            if instagram_tool:
                instagram_data = instagram_tool.invoke(
                    {
                        "keywords": ["srilankaeconomy", "srilankabusiness"],
                        "max_items": 5,
                    }
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
                print("  ✓ Instagram National Economy")
        except Exception as e:
            print(f"  ⚠️ Instagram error: {e}")

        # Reddit - National Economy
        try:
            reddit_tool = self.tools.get("scrape_reddit")
            if reddit_tool:
                reddit_data = reddit_tool.invoke(
                    {
                        "keywords": ["sri lanka economy", "sri lanka market"],
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
                print("  ✓ Reddit National Economy")
        except Exception as e:
            print(f"  ⚠️ Reddit error: {e}")

        return {
            "worker_results": social_results,
            "social_media_results": social_results,
        }

    def collect_sectoral_social_media(
        self, state: EconomicalAgentState
    ) -> Dict[str, Any]:
        """
        Module 2B: Collect sector-level social media for key economic sectors
        """
        print(
            f"[MODULE 2B] Collecting Sectoral Social Media ({len(self.key_sectors)} sectors)"
        )

        sectoral_results = []

        for sector in self.key_sectors:
            # Twitter per sector
            try:
                twitter_tool = self.tools.get("scrape_twitter")
                if twitter_tool:
                    twitter_data = twitter_tool.invoke(
                        {"query": f"sri lanka {sector}", "max_items": 5}
                    )
                    sectoral_results.append(
                        {
                            "source_tool": "scrape_twitter",
                            "raw_content": str(twitter_data),
                            "category": "sector",
                            "sector": sector,
                            "platform": "twitter",
                            "timestamp": datetime.utcnow().isoformat(),
                        }
                    )
                    print(f"  ✓ Twitter {sector.title()}")
            except Exception as e:
                print(f"  ⚠️ Twitter {sector} error: {e}")

            # Facebook per sector
            try:
                facebook_tool = self.tools.get("scrape_facebook")
                if facebook_tool:
                    facebook_data = facebook_tool.invoke(
                        {"keywords": [f"sri lanka {sector}"], "max_items": 5}
                    )
                    sectoral_results.append(
                        {
                            "source_tool": "scrape_facebook",
                            "raw_content": str(facebook_data),
                            "category": "sector",
                            "sector": sector,
                            "platform": "facebook",
                            "timestamp": datetime.utcnow().isoformat(),
                        }
                    )
                    print(f"  ✓ Facebook {sector.title()}")
            except Exception as e:
                print(f"  ⚠️ Facebook {sector} error: {e}")

        return {
            "worker_results": sectoral_results,
            "social_media_results": sectoral_results,
        }

    def collect_world_economy(self, state: EconomicalAgentState) -> Dict[str, Any]:
        """
        Module 2C: Collect world economy affecting Sri Lanka
        """
        print("[MODULE 2C] Collecting World Economy")

        world_results = []

        # Twitter - World Economy
        try:
            twitter_tool = self.tools.get("scrape_twitter")
            if twitter_tool:
                twitter_data = twitter_tool.invoke(
                    {
                        "query": "sri lanka IMF world bank international trade",
                        "max_items": 10,
                    }
                )
                world_results.append(
                    {
                        "source_tool": "scrape_twitter",
                        "raw_content": str(twitter_data),
                        "category": "world",
                        "platform": "twitter",
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
                print("  ✓ Twitter World Economy")
        except Exception as e:
            print(f"  ⚠️ Twitter world error: {e}")

        return {"worker_results": world_results, "social_media_results": world_results}

    # ============================================
    # MODULE 3: FEED GENERATION
    # ============================================

    def categorize_by_sector(self, state: EconomicalAgentState) -> Dict[str, Any]:
        """
        Module 3A: Categorize all collected results by sector/geography
        """
        print("[MODULE 3A] Categorizing Results by Sector")

        all_results = state.get("worker_results", []) or []

        # Initialize categories
        official_data = []
        national_data = []
        world_data = []
        sector_data = {sector: [] for sector in self.sectors}

        for r in all_results:
            category = r.get("category", "unknown")
            sector = r.get("sector")
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
                elif category == "world":
                    world_data.extend(posts[:10])
                elif category == "sector" and sector:
                    sector_data[sector].extend(posts[:5])
                elif category == "national":
                    national_data.extend(posts[:10])

            except Exception:
                continue

        # Create structured feeds
        structured_feeds = {
            "sri lanka economy": national_data + official_data,
            "world economy": world_data,
            **{sector: posts for sector, posts in sector_data.items() if posts},
        }

        print(
            f"  ✓ Categorized: {len(official_data)} official, {len(national_data)} national, {len(world_data)} world"
        )
        print(
            f"  ✓ Sectors with data: {len([s for s in sector_data if sector_data[s]])}"
        )
        return {
            "structured_output": structured_feeds,
            "market_feeds": sector_data,
            "national_feed": national_data + official_data,
            "world_feed": world_data,
        }

    def generate_llm_summary(self, state: EconomicalAgentState) -> Dict[str, Any]:
        """
        Module 3B: Use Groq LLM to generate executive summary
        """
        print("[MODULE 3B] Generating LLM Summary")

        structured_feeds = state.get("structured_output", {})

        try:
            summary_prompt = f"""Analyze the following economic intelligence data for Sri Lanka and create a concise executive summary.

Data Summary:
- National/Official Economic Data: {len(structured_feeds.get('sri lanka economy', []))} items
- World Economy: {len(structured_feeds.get('world economy', []))} items
- Sector Coverage: {len([k for k in structured_feeds.keys() if k not in ['sri lanka economy', 'world economy']])} sectors

Sample Data:
{json.dumps(structured_feeds, indent=2)[:2000]}

Generate a brief (3-5 sentences) executive summary highlighting the most important economic developments."""

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

    def format_final_output(self, state: EconomicalAgentState) -> Dict[str, Any]:
        """
        Module 3C: Format final feed output
        """
        print("[MODULE 3C] Formatting Final Output")

        llm_summary = state.get("llm_summary", "No summary available")
        structured_feeds = state.get("structured_output", {})
        sector_feeds = state.get("market_feeds", {})

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
        world_count = len(
            [r for r in state.get("worker_results", []) if r.get("category") == "world"]
        )
        active_sectors = len([s for s in sector_feeds if sector_feeds.get(s)])

        bulletin = f"""🇱🇰 COMPREHENSIVE ECONOMIC INTELLIGENCE FEED
{datetime.utcnow().strftime("%d %b %Y • %H:%M UTC")}

📊 EXECUTIVE SUMMARY (AI-Generated)
{llm_summary}

📈 DATA COLLECTION STATS
• Official Sources: {official_count} items
• National Social Media: {national_count} items
• World Economy: {world_count} items  
• Active Sectors: {active_sectors}

🔍 COVERAGE
Sectors monitored: {', '.join([s.title() for s in self.key_sectors])}

🌐 STRUCTURED DATA AVAILABLE
• "sri lanka economy": Combined national & official intelligence
• "world economy": International economic impact
• Sector-level: {', '.join([s.title() for s in sector_feeds if sector_feeds.get(s)])}

Source: Multi-platform aggregation (Twitter, Facebook, LinkedIn, Instagram, Reddit, CSE, Local News)
"""

        # Create list for per-sector domain_insights (FRONTEND COMPATIBLE)
        domain_insights = []
        timestamp = datetime.utcnow().isoformat()

        # 1. Create per-item economical insights
        for category, posts in structured_feeds.items():
            if not isinstance(posts, list):
                continue
            for post in posts[:10]:
                post_text = post.get("text", "") or post.get("title", "")
                if not post_text or len(post_text) < 10:
                    continue

                # Determine severity based on keywords
                severity = "medium"
                if any(
                    kw in post_text.lower()
                    for kw in [
                        "inflation",
                        "crisis",
                        "crash",
                        "recession",
                        "bankruptcy",
                    ]
                ):
                    severity = "high"
                elif any(
                    kw in post_text.lower()
                    for kw in ["growth", "profit", "investment", "opportunity"]
                ):
                    severity = "low"

                impact = (
                    "risk"
                    if severity == "high"
                    else "opportunity" if severity == "low" else "risk"
                )

                domain_insights.append(
                    {
                        "source_event_id": str(uuid.uuid4()),
                        "domain": "economical",
                        "summary": f"Sri Lanka Economy ({category.title()}): {post_text[:200]}",
                        "severity": severity,
                        "impact_type": impact,
                        "timestamp": timestamp,
                    }
                )

        # 2. Add executive summary insight
        domain_insights.append(
            {
                "source_event_id": str(uuid.uuid4()),
                "structured_data": structured_feeds,
                "domain": "economical",
                "summary": f"Sri Lanka Economic Summary: {llm_summary[:300]}",
                "severity": "medium",
                "impact_type": "risk",
            }
        )

        print(f"  ✓ Created {len(domain_insights)} economic insights")

        return {
            "final_feed": bulletin,
            "feed_history": [bulletin],
            "domain_insights": domain_insights,
        }

    # ============================================
    # MODULE 4: FEED AGGREGATOR & STORAGE
    # ============================================

    def aggregate_and_store_feeds(self, state: EconomicalAgentState) -> Dict[str, Any]:
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
        dataset_dir = os.getenv("DATASET_PATH", "./datasets/economic_feeds")
        os.makedirs(dataset_dir, exist_ok=True)

        csv_filename = f"economic_feeds_{datetime.now().strftime('%Y%m')}.csv"
        csv_path = os.path.join(dataset_dir, csv_filename)

        # CSV headers
        csv_headers = [
            "post_id",
            "timestamp",
            "platform",
            "category",
            "sector",
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
                    sector = worker_result.get("sector", "")

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

                            # Override sector if from worker result
                            if sector:
                                post_data["district"] = (
                                    sector  # Using district field for sector
                                )

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
                                    "sector": sector,
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
