"""
src/utils/tool_factory.py
Tool Factory Pattern for Parallel Agent Execution

This module provides a factory pattern for creating independent tool instances
for each agent, enabling safe parallel execution without shared state issues.

Usage:
    from src.utils.tool_factory import create_tool_set

    class MyAgentNode:
        def __init__(self):
            # Each agent gets its own private tool set
            self.tools = create_tool_set()

        def some_method(self, state):
            twitter_tool = self.tools.get("scrape_twitter")
            result = twitter_tool.invoke({"query": "..."})
"""

from typing import Dict, Any, Optional, List
import logging

logger = logging.getLogger("Roger.tool_factory")


class ToolSet:
    """
    Encapsulates a complete set of independent tool instances for an agent.

    Each ToolSet instance contains its own copy of all tools, ensuring
    that parallel agents don't share state or create race conditions.

    Thread Safety:
        Each ToolSet is independent. Multiple agents can safely use
        their own ToolSet instances in parallel without conflicts.

    Example:
        agent1_tools = ToolSet()
        agent2_tools = ToolSet()

        # These are independent instances - no shared state
        agent1_tools.get("scrape_twitter").invoke({...})
        agent2_tools.get("scrape_twitter").invoke({...})  # Safe to run in parallel
    """

    def __init__(self, include_profile_scrapers: bool = True):
        """
        Initialize a new ToolSet with fresh tool instances.

        Args:
            include_profile_scrapers: Whether to include profile-based scrapers
                                     (Twitter profile, LinkedIn profile, etc.)
        """
        self._tools: Dict[str, Any] = {}
        self._include_profile_scrapers = include_profile_scrapers
        self._create_tools()
        logger.debug(f"ToolSet created with {len(self._tools)} tools")

    def get(self, tool_name: str) -> Optional[Any]:
        """
        Get a tool by name.

        Args:
            tool_name: Name of the tool (e.g., "scrape_twitter", "scrape_reddit")

        Returns:
            Tool instance if found, None otherwise
        """
        return self._tools.get(tool_name)

    def as_dict(self) -> Dict[str, Any]:
        """
        Get all tools as a dictionary.

        Returns:
            Dictionary mapping tool names to tool instances
        """
        return self._tools.copy()

    def list_tools(self) -> List[str]:
        """
        List all available tool names.

        Returns:
            List of tool names in this ToolSet
        """
        return list(self._tools.keys())

    def _create_tools(self) -> None:
        """
        Create fresh instances of all tools.

        This method imports and creates new tool instances, ensuring
        each ToolSet has its own independent copies.
        """
        from langchain_core.tools import tool
        import json
        from datetime import datetime

        # Import implementation functions from utils
        # These are stateless functions that can be safely wrapped
        # Only the session-FREE scrapers are still needed from utils.py. The
        # eleven session/text helpers that used to be imported here went with
        # the social tools when they moved to src/scrapers -- keeping the
        # imports would make utils.py look load-bearing for social scraping
        # when it no longer is.
        from src.utils.utils import (
            scrape_reddit_impl,
            scrape_local_news_impl,
            scrape_cse_stock_impl,
            scrape_government_gazette_impl,
            scrape_parliament_minutes_impl,
            scrape_train_schedule_impl,
        )

        # ============================================
        # CREATE FRESH TOOL INSTANCES
        # ============================================

        # --- Reddit Tool ---
        @tool
        def scrape_reddit(
            keywords: List[str], limit: int = 20, subreddit: Optional[str] = None
        ):
            """
            Scrape Reddit for posts matching specific keywords.
            Optionally restrict to a specific subreddit.
            """
            data = scrape_reddit_impl(
                keywords=keywords, limit=limit, subreddit=subreddit
            )
            return json.dumps(data, default=str)

        self._tools["scrape_reddit"] = scrape_reddit

        # --- Local News Tool ---
        @tool
        def scrape_local_news(
            keywords: Optional[List[str]] = None, max_articles: int = 30
        ):
            """
            Scrape local Sri Lankan news from Daily Mirror, Daily FT, and News First.
            """
            data = scrape_local_news_impl(keywords=keywords, max_articles=max_articles)
            return json.dumps(data, default=str)

        self._tools["scrape_local_news"] = scrape_local_news

        # --- CSE Stock Tool ---
        @tool
        def scrape_cse_stock_data(
            symbol: str = "ASPI", period: str = "1d", interval: str = "1h"
        ):
            """
            Fetch Colombo Stock Exchange data using yfinance.
            """
            data = scrape_cse_stock_impl(
                symbol=symbol, period=period, interval=interval
            )
            return json.dumps(data, default=str)

        self._tools["scrape_cse_stock_data"] = scrape_cse_stock_data

        # --- Government Gazette Tool ---
        @tool
        def scrape_government_gazette(
            keywords: Optional[List[str]] = None, max_items: int = 15
        ):
            """
            Scrape latest government gazettes from gazette.lk.
            """
            data = scrape_government_gazette_impl(
                keywords=keywords, max_items=max_items
            )
            return json.dumps(data, default=str)

        self._tools["scrape_government_gazette"] = scrape_government_gazette

        # --- Parliament Minutes Tool ---
        @tool
        def scrape_parliament_minutes(
            keywords: Optional[List[str]] = None, max_items: int = 20
        ):
            """
            Scrape parliament Hansard and minutes from parliament.lk.
            """
            data = scrape_parliament_minutes_impl(
                keywords=keywords, max_items=max_items
            )
            return json.dumps(data, default=str)

        self._tools["scrape_parliament_minutes"] = scrape_parliament_minutes

        # --- Train Schedule Tool ---
        @tool
        def scrape_train_schedule(
            from_station: Optional[str] = None,
            to_station: Optional[str] = None,
            keyword: Optional[str] = None,
            max_items: int = 30,
        ):
            """
            Scrape train schedules from railway.gov.lk.
            """
            data = scrape_train_schedule_impl(
                from_station=from_station,
                to_station=to_station,
                keyword=keyword,
                max_items=max_items,
            )
            return json.dumps(data, default=str)

        self._tools["scrape_train_schedule"] = scrape_train_schedule

        # --- Think Tool (Agent Reasoning) ---
        @tool
        def think_tool(thought: str) -> str:
            """
            Use this tool to think through complex problems step-by-step.
            Write out your reasoning process here before taking action.
            """
            return f"Thought recorded: {thought}"

        self._tools["think_tool"] = think_tool

        # ============================================
        # SOCIAL TOOLS (session-dependent)
        # ============================================
        #
        # Registered unconditionally. There is no longer a PLAYWRIGHT_AVAILABLE
        # branch, because the tool layer no longer drives a browser -- it calls
        # src/scrapers, which resolves a credential and reports "unavailable"
        # when there is none.
        #
        # That distinction matters on the server, which installs no Playwright:
        # the old code registered stub tools returning
        # {"error": "Playwright not available"}, which reads to the agent as a
        # malfunction. "No account connected, connect one in Settings" is the
        # truth, and it is actionable.

        self._create_social_tools()

        # ============================================
        # PROFILE SCRAPERS (Competitive Intelligence)
        # ============================================

        if self._include_profile_scrapers:
            self._create_profile_scraper_tools()

    # ------------------------------------------------------------------
    # Social tools: thin delegation to src/scrapers
    #
    # These used to be ~660 lines of closures re-implementing every scraper a
    # third time. Because agent nodes reach tools through create_tool_set(),
    # THOSE were the copies that actually ran -- and they were the weakest of
    # the three: a User-Agent with no Chrome/ or Safari/ token (which makes
    # sites serve a degraded layout that then breaks the desktop selectors),
    # missing --disable-blink-features, no retry, no engagement extraction,
    # and 26 session-path probes for filenames nothing ever wrote.
    #
    # The tool layer's job is to describe a tool to the LLM and hand off. The
    # scraping lives in src/scrapers, once.
    # ------------------------------------------------------------------

    def _create_social_tools(self) -> None:
        """Register the session-dependent social tools by delegation."""
        from langchain_core.tools import tool
        import json

        from src.scrapers import registry as scraper_registry

        def _run(name: str, value: str, max_items: int) -> str:
            return json.dumps(
                scraper_registry.run(name, value, max_items=max_items),
                default=str,
                indent=2,
            )

        def _first(value, default: str) -> str:
            """Tools are called with either a string or a list of keywords."""
            if isinstance(value, (list, tuple)):
                return str(value[0]) if value else default
            return str(value) if value else default

        @tool
        def scrape_twitter(query: str = "Sri Lanka", max_items: int = 20) -> str:
            """Search X/Twitter for recent posts matching a query. Requires a connected X account."""
            return _run("scrape_twitter", _first(query, "Sri Lanka"), max_items)

        @tool
        def scrape_linkedin(keywords: Optional[List[str]] = None, max_items: int = 10) -> str:
            """Search LinkedIn posts for keywords. Requires a connected LinkedIn account."""
            return _run("scrape_linkedin", _first(keywords, "Sri Lanka business"), max_items)

        @tool
        def scrape_facebook(keywords: Optional[List[str]] = None, max_items: int = 10) -> str:
            """Search Facebook posts for a keyword. Requires a connected Facebook account."""
            return _run("scrape_facebook", _first(keywords, "Sri Lanka"), max_items)

        @tool
        def scrape_instagram(keywords: Optional[List[str]] = None, max_items: int = 15) -> str:
            """Collect Instagram posts for a hashtag. Requires a connected Instagram account."""
            return _run("scrape_instagram", _first(keywords, "srilanka"), max_items)

        for t in (scrape_twitter, scrape_linkedin, scrape_facebook, scrape_instagram):
            self._tools[t.name] = t

    def _create_profile_scraper_tools(self) -> None:
        """
        Register profile-based tools for competitive intelligence.

        Also delegation now. The previous versions here duplicated
        profile_scrapers.py, which in turn duplicated utils.py -- and the copy
        registered here is the one that ran, so the retry loop, engagement
        extraction and search fallback that made profile_scrapers.py the best
        implementation in the repo were never actually reached.
        """
        from langchain_core.tools import tool
        import json

        from src.scrapers import registry as scraper_registry

        def _run(name: str, value: str, max_items: int) -> str:
            return json.dumps(
                scraper_registry.run(name, value, max_items=max_items),
                default=str,
                indent=2,
            )

        @tool
        def scrape_twitter_profile(username: str, max_items: int = 20) -> str:
            """Collect recent posts from a specific X/Twitter account, with engagement counts."""
            return _run("scrape_twitter_profile", username, max_items)

        @tool
        def scrape_facebook_profile(profile_url: str, max_items: int = 10) -> str:
            """Collect recent posts from a Facebook page or profile URL."""
            return _run("scrape_facebook_profile", profile_url, max_items)

        @tool
        def scrape_instagram_profile(username: str, max_items: int = 15) -> str:
            """Collect recent posts from an Instagram account."""
            return _run("scrape_instagram_profile", username, max_items)

        @tool
        def scrape_linkedin_profile(company_or_username: str, max_items: int = 10) -> str:
            """Collect recent posts from a LinkedIn company page or person."""
            return _run("scrape_linkedin_profile", company_or_username, max_items)

        for t in (scrape_twitter_profile, scrape_facebook_profile,
                  scrape_instagram_profile, scrape_linkedin_profile):
            self._tools[t.name] = t

        # --- Product Reviews Tool ---
        @tool
        def scrape_product_reviews(
            product_keyword: str,
            platforms: Optional[List[str]] = None,
            max_items: int = 10,
        ):
            """
            Multi-platform product review aggregator for competitive intelligence.
            """
            if platforms is None:
                platforms = ["reddit", "twitter"]

            all_reviews = []

            # Reddit reviews
            if "reddit" in platforms:
                try:
                    reddit_tool = self._tools.get("scrape_reddit")
                    if reddit_tool:
                        reddit_data = reddit_tool.invoke(
                            {
                                "keywords": [
                                    f"{product_keyword} review",
                                    product_keyword,
                                ],
                                "limit": max_items,
                            }
                        )

                        reddit_results = (
                            json.loads(reddit_data)
                            if isinstance(reddit_data, str)
                            else reddit_data
                        )
                        for item in reddit_results:
                            if isinstance(item, dict):
                                all_reviews.append(
                                    {
                                        "platform": "Reddit",
                                        "text": item.get("title", "")
                                        + " "
                                        + item.get("selftext", ""),
                                        "url": item.get("url", ""),
                                    }
                                )
                except:
                    pass

            # Twitter reviews
            if "twitter" in platforms:
                try:
                    twitter_tool = self._tools.get("scrape_twitter")
                    if twitter_tool:
                        twitter_data = twitter_tool.invoke(
                            {
                                "query": f"{product_keyword} review",
                                "max_items": max_items,
                            }
                        )

                        twitter_results = (
                            json.loads(twitter_data)
                            if isinstance(twitter_data, str)
                            else twitter_data
                        )
                        if (
                            isinstance(twitter_results, dict)
                            and "results" in twitter_results
                        ):
                            for item in twitter_results["results"]:
                                all_reviews.append(
                                    {
                                        "platform": "Twitter",
                                        "text": item.get("text", ""),
                                        "url": item.get("url", ""),
                                    }
                                )
                except:
                    pass

            return json.dumps(
                {
                    "product": product_keyword,
                    "total_reviews": len(all_reviews),
                    "reviews": all_reviews,
                    "platforms_searched": platforms,
                },
                default=str,
            )

        self._tools["scrape_product_reviews"] = scrape_product_reviews


def create_tool_set(include_profile_scrapers: bool = True) -> ToolSet:
    """
    Factory function to create a new ToolSet with independent tool instances.

    This is the primary entry point for creating tools for an agent.
    Each call creates a completely independent set of tools.

    Args:
        include_profile_scrapers: Whether to include profile-based scrapers

    Returns:
        A new ToolSet instance with fresh tool instances

    Example:
        # In an agent node
        class MyAgentNode:
            def __init__(self):
                self.tools = create_tool_set()

            def process(self, state):
                twitter = self.tools.get("scrape_twitter")
                result = twitter.invoke({"query": "..."})
    """
    return ToolSet(include_profile_scrapers=include_profile_scrapers)


# Convenience exports
__all__ = [
    "ToolSet",
    "create_tool_set",
]
