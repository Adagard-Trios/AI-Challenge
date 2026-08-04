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
        from src.utils.utils import (
            scrape_reddit_impl,
            scrape_local_news_impl,
            scrape_cse_stock_impl,
            scrape_government_gazette_impl,
            scrape_parliament_minutes_impl,
            scrape_train_schedule_impl,
            PLAYWRIGHT_AVAILABLE,
            ensure_playwright,
            load_playwright_storage_state_path,
            create_or_restore_playwright_session,
            clean_twitter_text,
            extract_twitter_timestamp,
            clean_fb_text,
            clean_linkedin_text,
            extract_media_id_instagram,
            fetch_caption_via_private_api,
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
        # PLAYWRIGHT-BASED TOOLS (Social Media)
        # ============================================

        if PLAYWRIGHT_AVAILABLE:
            self._create_playwright_tools()
        else:
            logger.warning(
                "Playwright not available - social media tools will be limited"
            )
            self._create_fallback_social_tools()

        # ============================================
        # PROFILE SCRAPERS (Competitive Intelligence)
        # ============================================

        if self._include_profile_scrapers:
            self._create_profile_scraper_tools()

    def _create_playwright_tools(self) -> None:
        """Create Playwright-based social media tools."""
        from langchain_core.tools import tool
        import json
        import os
        import time
        import random
        import re
        from datetime import datetime
        from urllib.parse import quote_plus
        from playwright.sync_api import sync_playwright

        from src.utils.utils import (
            ensure_playwright,
            load_playwright_storage_state_path,
            clean_twitter_text,
            extract_twitter_timestamp,
            clean_fb_text,
            clean_linkedin_text,
            extract_media_id_instagram,
            fetch_caption_via_private_api,
        )

        # --- Twitter Tool ---
        @tool
        def scrape_twitter(query: str = "Sri Lanka", max_items: int = 20):
            """
            Twitter scraper - extracts actual tweet text, author, and metadata using Playwright session.
            Requires a valid Twitter session file.
            """
            ensure_playwright()

            # Load Session
            site = "twitter"
            session_path = load_playwright_storage_state_path(
                site, out_dir="src/utils/.sessions"
            )
            if not session_path:
                session_path = load_playwright_storage_state_path(
                    site, out_dir=".sessions"
                )

            # Check for alternative session file name
            if not session_path:
                alt_paths = [
                    os.path.join(
                        os.getcwd(), "src", "utils", ".sessions", "tw_state.json"
                    ),
                    os.path.join(os.getcwd(), ".sessions", "tw_state.json"),
                    os.path.join(os.getcwd(), "tw_state.json"),
                ]
                for path in alt_paths:
                    if os.path.exists(path):
                        session_path = path
                        break

            if not session_path:
                return json.dumps(
                    {
                        "error": "No Twitter session found",
                        "solution": "Run the Twitter session manager to create a session",
                    },
                    default=str,
                )

            results = []

            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(
                        headless=True,
                        args=[
                            "--disable-blink-features=AutomationControlled",
                            "--no-sandbox",
                            "--disable-dev-shm-usage",
                        ],
                    )

                    context = browser.new_context(
                        storage_state=session_path,
                        viewport={"width": 1280, "height": 720},
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    )

                    context.add_init_script(
                        """
                        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                        window.chrome = {runtime: {}};
                    """
                    )

                    page = context.new_page()

                    search_urls = [
                        f"https://x.com/search?q={quote_plus(query)}&src=typed_query&f=live",
                        f"https://x.com/search?q={quote_plus(query)}&src=typed_query",
                    ]

                    success = False
                    for url in search_urls:
                        try:
                            page.goto(url, timeout=60000, wait_until="domcontentloaded")
                            time.sleep(5)

                            # Handle popups
                            popup_selectors = [
                                "[data-testid='app-bar-close']",
                                "[aria-label='Close']",
                                "button:has-text('Not now')",
                            ]
                            for selector in popup_selectors:
                                try:
                                    if (
                                        page.locator(selector).count() > 0
                                        and page.locator(selector).first.is_visible()
                                    ):
                                        page.locator(selector).first.click()
                                        time.sleep(1)
                                except:
                                    pass

                            try:
                                page.wait_for_selector(
                                    "article[data-testid='tweet']", timeout=15000
                                )
                                success = True
                                break
                            except:
                                continue
                        except:
                            continue

                    if not success or "login" in page.url:
                        return json.dumps(
                            {"error": "Session invalid or tweets not found"},
                            default=str,
                        )

                    # Scraping
                    seen = set()
                    scroll_attempts = 0
                    max_scroll_attempts = 15

                    TWEET_SELECTOR = "article[data-testid='tweet']"
                    TEXT_SELECTOR = "div[data-testid='tweetText']"
                    USER_SELECTOR = "div[data-testid='User-Name']"

                    while (
                        len(results) < max_items
                        and scroll_attempts < max_scroll_attempts
                    ):
                        scroll_attempts += 1

                        # Expand "Show more" buttons
                        try:
                            show_more_buttons = page.locator(
                                "[data-testid='tweet-text-show-more-link']"
                            ).all()
                            for button in show_more_buttons:
                                if button.is_visible():
                                    try:
                                        button.click()
                                        time.sleep(0.3)
                                    except:
                                        pass
                        except:
                            pass

                        tweets = page.locator(TWEET_SELECTOR).all()
                        new_tweets_found = 0

                        for tweet in tweets:
                            if len(results) >= max_items:
                                break

                            try:
                                tweet.scroll_into_view_if_needed()
                                time.sleep(0.1)

                                if (
                                    tweet.locator("span:has-text('Promoted')").count()
                                    > 0
                                    or tweet.locator("span:has-text('Ad')").count() > 0
                                ):
                                    continue

                                text_content = ""
                                text_element = tweet.locator(TEXT_SELECTOR).first
                                if text_element.count() > 0:
                                    text_content = text_element.inner_text()

                                cleaned_text = clean_twitter_text(text_content)

                                user_info = "Unknown"
                                user_element = tweet.locator(USER_SELECTOR).first
                                if user_element.count() > 0:
                                    user_text = user_element.inner_text()
                                    user_info = user_text.split("\n")[0].strip()

                                timestamp = extract_twitter_timestamp(tweet)

                                text_key = cleaned_text[:50] if cleaned_text else ""
                                unique_key = f"{user_info}_{text_key}"

                                if (
                                    cleaned_text
                                    and len(cleaned_text) > 20
                                    and unique_key not in seen
                                    and not any(
                                        word in cleaned_text.lower()
                                        for word in ["promoted", "advertisement"]
                                    )
                                ):

                                    seen.add(unique_key)
                                    results.append(
                                        {
                                            "source": "Twitter",
                                            "poster": user_info,
                                            "text": cleaned_text,
                                            "timestamp": timestamp,
                                            "url": "https://x.com",
                                        }
                                    )
                                    new_tweets_found += 1
                            except:
                                continue

                        if len(results) < max_items:
                            page.evaluate(
                                "window.scrollTo(0, document.documentElement.scrollHeight)"
                            )
                            time.sleep(random.uniform(2, 3))

                            if new_tweets_found == 0:
                                scroll_attempts += 1

                    browser.close()

                    return json.dumps(
                        {
                            "source": "Twitter",
                            "query": query,
                            "results": results,
                            "total_found": len(results),
                            "fetched_at": datetime.utcnow().isoformat(),
                        },
                        default=str,
                    )

            except Exception as e:
                return json.dumps({"error": str(e)}, default=str)

        self._tools["scrape_twitter"] = scrape_twitter

        # --- LinkedIn Tool ---
        @tool
        def scrape_linkedin(keywords: Optional[List[str]] = None, max_items: int = 10):
            """
            LinkedIn search using Playwright session.
            Requires environment variables: LINKEDIN_USER, LINKEDIN_PASSWORD (if creating session).
            """
            ensure_playwright()

            site = "linkedin"
            session_path = load_playwright_storage_state_path(
                site, out_dir="src/utils/.sessions"
            )
            if not session_path:
                session_path = load_playwright_storage_state_path(
                    site, out_dir=".sessions"
                )

            if not session_path:
                return json.dumps({"error": "No LinkedIn session found"}, default=str)

            keyword = " ".join(keywords) if keywords else "Sri Lanka"
            results = []

            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    context = browser.new_context(
                        storage_state=session_path,
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        no_viewport=True,
                    )

                    page = context.new_page()
                    url = f"https://www.linkedin.com/search/results/content/?keywords={keyword.replace(' ', '%20')}"

                    try:
                        page.goto(url, timeout=60000, wait_until="domcontentloaded")
                    except:
                        pass

                    page.wait_for_timeout(random.randint(4000, 7000))

                    try:
                        if (
                            page.locator("a[href*='login']").is_visible()
                            or "auth_wall" in page.url
                        ):
                            return json.dumps({"error": "Session invalid"})
                    except:
                        pass

                    seen = set()
                    no_new_data_count = 0
                    previous_height = 0

                    POST_SELECTOR = "div.feed-shared-update-v2, li.artdeco-card"
                    TEXT_SELECTOR = (
                        "div.update-components-text span.break-words, span.break-words"
                    )
                    POSTER_SELECTOR = (
                        "span.update-components-actor__name span[dir='ltr']"
                    )

                    while len(results) < max_items:
                        try:
                            see_more_buttons = page.locator(
                                "button.feed-shared-inline-show-more-text__see-more-less-toggle"
                            ).all()
                            for btn in see_more_buttons:
                                if btn.is_visible():
                                    try:
                                        btn.click(timeout=500)
                                    except:
                                        pass
                        except:
                            pass

                        posts = page.locator(POST_SELECTOR).all()

                        for post in posts:
                            if len(results) >= max_items:
                                break
                            try:
                                post.scroll_into_view_if_needed()
                                raw_text = ""
                                text_el = post.locator(TEXT_SELECTOR).first
                                if text_el.is_visible():
                                    raw_text = text_el.inner_text()

                                cleaned_text = clean_linkedin_text(raw_text)
                                poster_name = "(Unknown)"
                                poster_el = post.locator(POSTER_SELECTOR).first
                                if poster_el.is_visible():
                                    poster_name = poster_el.inner_text().strip()

                                key = f"{poster_name[:20]}::{cleaned_text[:30]}"
                                if (
                                    cleaned_text
                                    and len(cleaned_text) > 20
                                    and key not in seen
                                ):
                                    seen.add(key)
                                    results.append(
                                        {
                                            "source": "LinkedIn",
                                            "poster": poster_name,
                                            "text": cleaned_text,
                                            "url": "https://www.linkedin.com",
                                        }
                                    )
                            except:
                                continue

                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        page.wait_for_timeout(random.randint(2000, 4000))

                        new_height = page.evaluate("document.body.scrollHeight")
                        if new_height == previous_height:
                            no_new_data_count += 1
                            if no_new_data_count > 3:
                                break
                        else:
                            no_new_data_count = 0
                            previous_height = new_height

                    browser.close()
                    return json.dumps(
                        {"site": "LinkedIn", "results": results}, default=str
                    )

            except Exception as e:
                return json.dumps({"error": str(e)})

        self._tools["scrape_linkedin"] = scrape_linkedin

        # --- Facebook Tool ---
        @tool
        def scrape_facebook(keywords: Optional[List[str]] = None, max_items: int = 10):
            """
            Facebook scraper using Playwright session (Desktop).
            Extracts posts from keyword search with poster names and text.
            """
            ensure_playwright()

            site = "facebook"
            session_path = load_playwright_storage_state_path(
                site, out_dir="src/utils/.sessions"
            )
            if not session_path:
                session_path = load_playwright_storage_state_path(
                    site, out_dir=".sessions"
                )

            if not session_path:
                alt_paths = [
                    os.path.join(
                        os.getcwd(), "src", "utils", ".sessions", "fb_state.json"
                    ),
                    os.path.join(os.getcwd(), ".sessions", "fb_state.json"),
                ]
                for path in alt_paths:
                    if os.path.exists(path):
                        session_path = path
                        break

            if not session_path:
                return json.dumps({"error": "No Facebook session found"}, default=str)

            keyword = " ".join(keywords) if keywords else "Sri Lanka"
            results = []

            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    context = browser.new_context(
                        storage_state=session_path,
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        viewport={"width": 1400, "height": 900},
                    )

                    page = context.new_page()
                    search_url = f"https://www.facebook.com/search/posts?q={keyword.replace(' ', '%20')}"

                    page.goto(search_url, timeout=120000)
                    time.sleep(5)

                    seen = set()
                    stuck = 0
                    last_scroll = 0

                    MESSAGE_SELECTOR = "div[data-ad-preview='message']"

                    POSTER_SELECTORS = [
                        "h3 strong a span",
                        "h3 strong span",
                        "strong a span",
                        "a[role='link'] span",
                    ]

                    def extract_poster(post):
                        parent = post.locator(
                            "xpath=ancestor::div[contains(@class, 'x1yztbdb')][1]"
                        )
                        for selector in POSTER_SELECTORS:
                            try:
                                el = parent.locator(selector).first
                                if el and el.count() > 0:
                                    name = el.inner_text().strip()
                                    if name and name != "Facebook" and len(name) > 1:
                                        return name
                            except:
                                pass
                        return "(Unknown)"

                    while len(results) < max_items:
                        posts = page.locator(MESSAGE_SELECTOR).all()

                        for post in posts:
                            try:
                                raw = post.inner_text().strip()
                                cleaned = clean_fb_text(raw)
                                poster = extract_poster(post)

                                if cleaned and len(cleaned) > 30:
                                    key = poster + "::" + cleaned
                                    if key not in seen:
                                        seen.add(key)
                                        results.append(
                                            {
                                                "source": "Facebook",
                                                "poster": poster,
                                                "text": cleaned,
                                                "url": "https://www.facebook.com",
                                            }
                                        )

                                if len(results) >= max_items:
                                    break
                            except:
                                pass

                        page.evaluate("window.scrollBy(0, 2300)")
                        time.sleep(1.2)

                        new_scroll = page.evaluate("window.scrollY")
                        stuck = stuck + 1 if new_scroll == last_scroll else 0
                        last_scroll = new_scroll

                        if stuck >= 3:
                            break

                    browser.close()
                    return json.dumps(
                        {"site": "Facebook", "results": results[:max_items]},
                        default=str,
                    )

            except Exception as e:
                return json.dumps({"error": str(e)}, default=str)

        self._tools["scrape_facebook"] = scrape_facebook

        # --- Instagram Tool ---
        @tool
        def scrape_instagram(keywords: Optional[List[str]] = None, max_items: int = 15):
            """
            Instagram scraper using Playwright session.
            Scrapes posts from hashtag search and extracts captions.
            """
            ensure_playwright()

            site = "instagram"
            session_path = load_playwright_storage_state_path(
                site, out_dir="src/utils/.sessions"
            )
            if not session_path:
                session_path = load_playwright_storage_state_path(
                    site, out_dir=".sessions"
                )

            if not session_path:
                alt_paths = [
                    os.path.join(
                        os.getcwd(), "src", "utils", ".sessions", "ig_state.json"
                    ),
                    os.path.join(os.getcwd(), ".sessions", "ig_state.json"),
                ]
                for path in alt_paths:
                    if os.path.exists(path):
                        session_path = path
                        break

            if not session_path:
                return json.dumps({"error": "No Instagram session found"}, default=str)

            keyword = " ".join(keywords) if keywords else "srilanka"
            keyword = keyword.replace(" ", "")
            results = []

            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    context = browser.new_context(
                        storage_state=session_path,
                        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
                        viewport={"width": 430, "height": 932},
                    )

                    page = context.new_page()
                    url = f"https://www.instagram.com/explore/tags/{keyword}/"

                    page.goto(url, timeout=120000)
                    page.wait_for_timeout(4000)

                    for _ in range(12):
                        page.mouse.wheel(0, 2500)
                        page.wait_for_timeout(1500)

                    anchors = page.locator("a[href*='/p/'], a[href*='/reel/']").all()
                    links = []

                    for a in anchors:
                        href = a.get_attribute("href")
                        if href:
                            full = "https://www.instagram.com" + href
                            links.append(full)
                        if len(links) >= max_items:
                            break

                    for link in links:
                        page.goto(link, timeout=120000)
                        page.wait_for_timeout(2000)

                        media_id = extract_media_id_instagram(page)
                        caption = fetch_caption_via_private_api(page, media_id)

                        if not caption:
                            try:
                                caption = (
                                    page.locator("article h1, article span")
                                    .first.inner_text()
                                    .strip()
                                )
                            except:
                                caption = None

                        if caption:
                            results.append(
                                {
                                    "source": "Instagram",
                                    "text": caption,
                                    "url": link,
                                    "poster": "(Instagram User)",
                                }
                            )

                    browser.close()
                    return json.dumps(
                        {"site": "Instagram", "results": results}, default=str
                    )

            except Exception as e:
                return json.dumps({"error": str(e)}, default=str)

        self._tools["scrape_instagram"] = scrape_instagram

    def _create_fallback_social_tools(self) -> None:
        """Create fallback tools when Playwright is not available."""
        from langchain_core.tools import tool
        import json

        @tool
        def scrape_twitter(query: str = "Sri Lanka", max_items: int = 20):
            """Twitter scraper (requires Playwright)."""
            return json.dumps(
                {"error": "Playwright not available for Twitter scraping"}
            )

        @tool
        def scrape_linkedin(keywords: Optional[List[str]] = None, max_items: int = 10):
            """LinkedIn scraper (requires Playwright)."""
            return json.dumps(
                {"error": "Playwright not available for LinkedIn scraping"}
            )

        @tool
        def scrape_facebook(keywords: Optional[List[str]] = None, max_items: int = 10):
            """Facebook scraper (requires Playwright)."""
            return json.dumps(
                {"error": "Playwright not available for Facebook scraping"}
            )

        @tool
        def scrape_instagram(keywords: Optional[List[str]] = None, max_items: int = 15):
            """Instagram scraper (requires Playwright)."""
            return json.dumps(
                {"error": "Playwright not available for Instagram scraping"}
            )

        self._tools["scrape_twitter"] = scrape_twitter
        self._tools["scrape_linkedin"] = scrape_linkedin
        self._tools["scrape_facebook"] = scrape_facebook
        self._tools["scrape_instagram"] = scrape_instagram

    def _create_profile_scraper_tools(self) -> None:
        """Create profile-based scraper tools for competitive intelligence."""
        from langchain_core.tools import tool
        import json
        import os
        import time
        import random
        import re
        from datetime import datetime

        from src.utils.utils import (
            PLAYWRIGHT_AVAILABLE,
            ensure_playwright,
            load_playwright_storage_state_path,
            clean_twitter_text,
            extract_twitter_timestamp,
            clean_fb_text,
            extract_media_id_instagram,
            fetch_caption_via_private_api,
        )

        if not PLAYWRIGHT_AVAILABLE:
            return

        from playwright.sync_api import sync_playwright

        # --- Twitter Profile Scraper ---
        @tool
        def scrape_twitter_profile(username: str, max_items: int = 20):
            """
            Twitter PROFILE scraper - targets a specific user's timeline.
            Perfect for monitoring competitor accounts, influencers, or business profiles.
            """
            ensure_playwright()

            site = "twitter"
            session_path = load_playwright_storage_state_path(
                site, out_dir="src/utils/.sessions"
            )
            if not session_path:
                session_path = load_playwright_storage_state_path(
                    site, out_dir=".sessions"
                )

            if not session_path:
                alt_paths = [
                    os.path.join(
                        os.getcwd(), "src", "utils", ".sessions", "tw_state.json"
                    ),
                    os.path.join(os.getcwd(), ".sessions", "tw_state.json"),
                ]
                for path in alt_paths:
                    if os.path.exists(path):
                        session_path = path
                        break

            if not session_path:
                return json.dumps({"error": "No Twitter session found"}, default=str)

            results = []
            username = username.lstrip("@")

            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                    context = browser.new_context(
                        storage_state=session_path,
                        viewport={"width": 1280, "height": 720},
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    )

                    page = context.new_page()
                    profile_url = f"https://x.com/{username}"

                    try:
                        page.goto(
                            profile_url, timeout=60000, wait_until="domcontentloaded"
                        )
                        time.sleep(5)

                        try:
                            page.wait_for_selector(
                                "article[data-testid='tweet']", timeout=15000
                            )
                        except:
                            return json.dumps(
                                {"error": f"Profile not found or private: @{username}"}
                            )
                    except Exception as e:
                        return json.dumps({"error": str(e)})

                    if "login" in page.url:
                        return json.dumps({"error": "Session expired"})

                    seen = set()
                    scroll_attempts = 0

                    while len(results) < max_items and scroll_attempts < 10:
                        scroll_attempts += 1

                        tweets = page.locator("article[data-testid='tweet']").all()

                        for tweet in tweets:
                            if len(results) >= max_items:
                                break

                            try:
                                tweet.scroll_into_view_if_needed()

                                if (
                                    tweet.locator("span:has-text('Promoted')").count()
                                    > 0
                                ):
                                    continue

                                text_content = ""
                                text_element = tweet.locator(
                                    "div[data-testid='tweetText']"
                                ).first
                                if text_element.count() > 0:
                                    text_content = text_element.inner_text()

                                cleaned_text = clean_twitter_text(text_content)
                                timestamp = extract_twitter_timestamp(tweet)

                                # Get engagement
                                likes = 0
                                try:
                                    like_button = tweet.locator("[data-testid='like']")
                                    if like_button.count() > 0:
                                        like_text = (
                                            like_button.first.get_attribute(
                                                "aria-label"
                                            )
                                            or ""
                                        )
                                        like_match = re.search(r"(\d+)", like_text)
                                        if like_match:
                                            likes = int(like_match.group(1))
                                except:
                                    pass

                                text_key = cleaned_text[:50] if cleaned_text else ""
                                unique_key = f"{username}_{text_key}_{timestamp}"

                                if (
                                    cleaned_text
                                    and len(cleaned_text) > 20
                                    and unique_key not in seen
                                ):
                                    seen.add(unique_key)
                                    results.append(
                                        {
                                            "source": "Twitter",
                                            "poster": f"@{username}",
                                            "text": cleaned_text,
                                            "timestamp": timestamp,
                                            "url": profile_url,
                                            "likes": likes,
                                        }
                                    )
                            except:
                                continue

                        if len(results) < max_items:
                            page.evaluate(
                                "window.scrollTo(0, document.documentElement.scrollHeight)"
                            )
                            time.sleep(random.uniform(2, 3))

                    browser.close()

                    return json.dumps(
                        {
                            "site": "Twitter Profile",
                            "username": username,
                            "results": results,
                            "total_found": len(results),
                            "fetched_at": datetime.utcnow().isoformat(),
                        },
                        default=str,
                    )

            except Exception as e:
                return json.dumps({"error": str(e)}, default=str)

        self._tools["scrape_twitter_profile"] = scrape_twitter_profile

        # --- Facebook Profile Scraper ---
        @tool
        def scrape_facebook_profile(profile_url: str, max_items: int = 10):
            """
            Facebook PROFILE scraper - monitors a specific page or user profile.
            """
            ensure_playwright()

            site = "facebook"
            session_path = load_playwright_storage_state_path(
                site, out_dir="src/utils/.sessions"
            )
            if not session_path:
                session_path = load_playwright_storage_state_path(
                    site, out_dir=".sessions"
                )

            if not session_path:
                return json.dumps({"error": "No Facebook session found"}, default=str)

            results = []

            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    context = browser.new_context(
                        storage_state=session_path,
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        viewport={"width": 1400, "height": 900},
                    )

                    page = context.new_page()
                    page.goto(profile_url, timeout=120000)
                    time.sleep(5)

                    if "login" in page.url:
                        return json.dumps({"error": "Session expired"})

                    seen = set()
                    stuck = 0
                    last_scroll = 0

                    MESSAGE_SELECTOR = "div[data-ad-preview='message']"

                    while len(results) < max_items:
                        posts = page.locator(MESSAGE_SELECTOR).all()

                        for post in posts:
                            try:
                                raw = post.inner_text().strip()
                                cleaned = clean_fb_text(raw)

                                if (
                                    cleaned
                                    and len(cleaned) > 30
                                    and cleaned not in seen
                                ):
                                    seen.add(cleaned)
                                    results.append(
                                        {
                                            "source": "Facebook",
                                            "text": cleaned,
                                            "url": profile_url,
                                        }
                                    )

                                if len(results) >= max_items:
                                    break
                            except:
                                pass

                        page.evaluate("window.scrollBy(0, 2300)")
                        time.sleep(1.5)

                        new_scroll = page.evaluate("window.scrollY")
                        stuck = stuck + 1 if new_scroll == last_scroll else 0
                        last_scroll = new_scroll

                        if stuck >= 3:
                            break

                    browser.close()
                    return json.dumps(
                        {
                            "site": "Facebook Profile",
                            "profile_url": profile_url,
                            "results": results[:max_items],
                        },
                        default=str,
                    )

            except Exception as e:
                return json.dumps({"error": str(e)}, default=str)

        self._tools["scrape_facebook_profile"] = scrape_facebook_profile

        # --- Instagram Profile Scraper ---
        @tool
        def scrape_instagram_profile(username: str, max_items: int = 15):
            """
            Instagram PROFILE scraper - monitors a specific user's profile.
            """
            ensure_playwright()

            site = "instagram"
            session_path = load_playwright_storage_state_path(
                site, out_dir="src/utils/.sessions"
            )
            if not session_path:
                session_path = load_playwright_storage_state_path(
                    site, out_dir=".sessions"
                )

            if not session_path:
                return json.dumps({"error": "No Instagram session found"}, default=str)

            username = username.lstrip("@")
            results = []

            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    context = browser.new_context(
                        storage_state=session_path,
                        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
                        viewport={"width": 430, "height": 932},
                    )

                    page = context.new_page()
                    url = f"https://www.instagram.com/{username}/"

                    page.goto(url, timeout=120000)
                    page.wait_for_timeout(4000)

                    if "login" in page.url:
                        return json.dumps({"error": "Session expired"})

                    for _ in range(8):
                        page.mouse.wheel(0, 2500)
                        page.wait_for_timeout(1500)

                    anchors = page.locator("a[href*='/p/'], a[href*='/reel/']").all()
                    links = []

                    for a in anchors:
                        href = a.get_attribute("href")
                        if href:
                            full = "https://www.instagram.com" + href
                            links.append(full)
                        if len(links) >= max_items:
                            break

                    for link in links:
                        page.goto(link, timeout=120000)
                        page.wait_for_timeout(2000)

                        media_id = extract_media_id_instagram(page)
                        caption = fetch_caption_via_private_api(page, media_id)

                        if not caption:
                            try:
                                caption = (
                                    page.locator("article h1, article span")
                                    .first.inner_text()
                                    .strip()
                                )
                            except:
                                caption = None

                        if caption:
                            results.append(
                                {
                                    "source": "Instagram",
                                    "poster": f"@{username}",
                                    "text": caption,
                                    "url": link,
                                }
                            )

                    browser.close()
                    return json.dumps(
                        {
                            "site": "Instagram Profile",
                            "username": username,
                            "results": results,
                        },
                        default=str,
                    )

            except Exception as e:
                return json.dumps({"error": str(e)}, default=str)

        self._tools["scrape_instagram_profile"] = scrape_instagram_profile

        # --- LinkedIn Profile Scraper ---
        @tool
        def scrape_linkedin_profile(company_or_username: str, max_items: int = 10):
            """
            LinkedIn PROFILE scraper - monitors a company or user profile.
            """
            ensure_playwright()

            site = "linkedin"
            session_path = load_playwright_storage_state_path(
                site, out_dir="src/utils/.sessions"
            )
            if not session_path:
                session_path = load_playwright_storage_state_path(
                    site, out_dir=".sessions"
                )

            if not session_path:
                return json.dumps({"error": "No LinkedIn session found"}, default=str)

            results = []

            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    context = browser.new_context(
                        storage_state=session_path,
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        viewport={"width": 1400, "height": 900},
                    )

                    page = context.new_page()

                    if not company_or_username.startswith("http"):
                        if "company/" in company_or_username:
                            profile_url = f"https://www.linkedin.com/company/{company_or_username.replace('company/', '')}"
                        else:
                            profile_url = (
                                f"https://www.linkedin.com/in/{company_or_username}"
                            )
                    else:
                        profile_url = company_or_username

                    page.goto(profile_url, timeout=120000)
                    page.wait_for_timeout(5000)

                    if "login" in page.url or "authwall" in page.url:
                        return json.dumps({"error": "Session expired"})

                    # Try to click posts tab
                    try:
                        posts_tab = page.locator("a:has-text('Posts')").first
                        if posts_tab.is_visible():
                            posts_tab.click()
                            page.wait_for_timeout(3000)
                    except:
                        pass

                    seen = set()
                    no_new_data_count = 0
                    previous_height = 0

                    while len(results) < max_items and no_new_data_count < 3:
                        posts = page.locator("div.feed-shared-update-v2").all()

                        for post in posts:
                            if len(results) >= max_items:
                                break
                            try:
                                post.scroll_into_view_if_needed()
                                text_el = post.locator("span.break-words").first
                                if text_el.is_visible():
                                    raw_text = text_el.inner_text()

                                    from src.utils.utils import clean_linkedin_text

                                    cleaned = clean_linkedin_text(raw_text)

                                    if (
                                        cleaned
                                        and len(cleaned) > 20
                                        and cleaned[:50] not in seen
                                    ):
                                        seen.add(cleaned[:50])
                                        results.append(
                                            {
                                                "source": "LinkedIn",
                                                "text": cleaned,
                                                "url": profile_url,
                                            }
                                        )
                            except:
                                continue

                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        page.wait_for_timeout(random.randint(2000, 4000))

                        new_height = page.evaluate("document.body.scrollHeight")
                        if new_height == previous_height:
                            no_new_data_count += 1
                        else:
                            no_new_data_count = 0
                            previous_height = new_height

                    browser.close()
                    return json.dumps(
                        {
                            "site": "LinkedIn Profile",
                            "profile": company_or_username,
                            "results": results,
                        },
                        default=str,
                    )

            except Exception as e:
                return json.dumps({"error": str(e)}, default=str)

        self._tools["scrape_linkedin_profile"] = scrape_linkedin_profile

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
