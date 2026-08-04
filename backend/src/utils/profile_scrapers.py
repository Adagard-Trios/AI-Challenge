"""
src/utils/profile_scrapers.py
Profile-based social media scrapers for Intelligence Agent
Competitive Intelligence & Profile Monitoring Tools
"""

import json
import os
import time
import random
import re
import logging
from typing import Optional, List
from datetime import datetime
from urllib.parse import quote_plus
from langchain_core.tools import tool

try:
    from playwright.sync_api import sync_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

from src.utils.utils import (
    ensure_playwright,
    load_playwright_storage_state_path,
    clean_twitter_text,
    extract_twitter_timestamp,
    clean_fb_text,
    extract_media_id_instagram,
    fetch_caption_via_private_api,
)

logger = logging.getLogger("Roger.utils.profile_scrapers")
logger.setLevel(logging.INFO)


# =====================================================
# TWITTER PROFILE SCRAPER
# =====================================================


@tool
def scrape_twitter_profile(username: str, max_items: int = 20):
    """
    Twitter PROFILE scraper - targets a specific user's timeline for competitive monitoring.
    Fetches tweets from a specific user's profile, not search results.
    Perfect for monitoring competitor accounts, influencers, or specific business profiles.

    Features:
    - Retry logic with exponential backoff (3 attempts)
    - Fallback to keyword search if profile fails
    - Increased timeout (90s)

    Args:
        username: Twitter username (without @)
        max_items: Maximum number of tweets to fetch

    Returns:
        JSON with user's tweets, engagement metrics, and timestamps
    """
    ensure_playwright()

    # Load Session
    site = "twitter"
    session_path = load_playwright_storage_state_path(
        site, out_dir="src/utils/.sessions"
    )
    if not session_path:
        session_path = load_playwright_storage_state_path(site, out_dir=".sessions")

    # Check for alternative session file name
    if not session_path:
        alt_paths = [
            os.path.join(os.getcwd(), "src", "utils", ".sessions", "tw_state.json"),
            os.path.join(os.getcwd(), ".sessions", "tw_state.json"),
            os.path.join(os.getcwd(), "tw_state.json"),
        ]
        for path in alt_paths:
            if os.path.exists(path):
                session_path = path
                logger.info(f"[TWITTER_PROFILE] Found session at {path}")
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
    username = username.lstrip("@")  # Remove @ if present

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
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )

            context.add_init_script(
                """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = {runtime: {}};
            """
            )

            page = context.new_page()

            # Navigate to user profile with retry logic
            profile_url = f"https://x.com/{username}"
            logger.info(f"[TWITTER_PROFILE] Monitoring @{username}")

            max_retries = 3
            navigation_success = False
            last_error = None

            for attempt in range(max_retries):
                try:
                    # Exponential backoff: 0, 2, 4 seconds
                    if attempt > 0:
                        wait_time = 2**attempt
                        logger.info(
                            f"[TWITTER_PROFILE] Retry {attempt + 1}/{max_retries} after {wait_time}s..."
                        )
                        time.sleep(wait_time)

                    # Increased timeout from 60s to 90s, changed to networkidle
                    page.goto(profile_url, timeout=90000, wait_until="networkidle")
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

                    # Wait for tweets to load
                    try:
                        page.wait_for_selector(
                            "article[data-testid='tweet']", timeout=20000
                        )
                        logger.info(f"[TWITTER_PROFILE] Loaded {username}'s profile")
                        navigation_success = True
                        break
                    except:
                        last_error = f"Could not load tweets for @{username}"
                        logger.warning(
                            f"[TWITTER_PROFILE] {last_error}, attempt {attempt + 1}/{max_retries}"
                        )
                        continue

                except Exception as e:
                    last_error = str(e)
                    logger.warning(
                        f"[TWITTER_PROFILE] Navigation failed on attempt {attempt + 1}: {e}"
                    )
                    continue

            # If profile scraping failed after all retries, try fallback to keyword search
            if not navigation_success:
                logger.warning(
                    f"[TWITTER_PROFILE] Profile scraping failed, falling back to keyword search for '{username}'"
                )
                browser.close()

                # Fallback: use keyword search instead
                try:
                    from src.utils.utils import scrape_twitter

                    fallback_result = scrape_twitter.invoke(
                        {"query": username, "max_items": max_items}
                    )
                    fallback_data = (
                        json.loads(fallback_result)
                        if isinstance(fallback_result, str)
                        else fallback_result
                    )

                    if "error" not in fallback_data:
                        fallback_data["fallback_used"] = True
                        fallback_data["original_error"] = last_error
                        fallback_data["note"] = (
                            f"Used keyword search as fallback for @{username}"
                        )
                        return json.dumps(fallback_data, default=str)
                except Exception as fallback_error:
                    logger.error(
                        f"[TWITTER_PROFILE] Fallback also failed: {fallback_error}"
                    )

                return json.dumps(
                    {
                        "error": last_error
                        or f"Profile not found or private: @{username}",
                        "fallback_attempted": True,
                    },
                    default=str,
                )

            # Check if logged in
            if "login" in page.url:
                logger.error("[TWITTER_PROFILE] Session expired")
                return json.dumps({"error": "Session invalid or expired"}, default=str)

            # Scraping with engagement metrics
            seen = set()
            scroll_attempts = 0
            max_scroll_attempts = 10

            TWEET_SELECTOR = "article[data-testid='tweet']"
            TEXT_SELECTOR = "div[data-testid='tweetText']"

            while len(results) < max_items and scroll_attempts < max_scroll_attempts:
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

                # Collect tweets
                tweets = page.locator(TWEET_SELECTOR).all()
                new_tweets_found = 0

                for tweet in tweets:
                    if len(results) >= max_items:
                        break

                    try:
                        tweet.scroll_into_view_if_needed()
                        time.sleep(0.2)

                        # Skip promoted/ads
                        if (
                            tweet.locator("span:has-text('Promoted')").count() > 0
                            or tweet.locator("span:has-text('Ad')").count() > 0
                        ):
                            continue

                        # Extract text
                        text_content = ""
                        text_element = tweet.locator(TEXT_SELECTOR).first
                        if text_element.count() > 0:
                            text_content = text_element.inner_text()

                        cleaned_text = clean_twitter_text(text_content)

                        # Extract timestamp
                        timestamp = extract_twitter_timestamp(tweet)

                        # Extract engagement metrics
                        likes = 0
                        retweets = 0
                        replies = 0

                        try:
                            # Likes
                            like_button = tweet.locator("[data-testid='like']")
                            if like_button.count() > 0:
                                like_text = (
                                    like_button.first.get_attribute("aria-label") or ""
                                )
                                like_match = re.search(r"(\d+)", like_text)
                                if like_match:
                                    likes = int(like_match.group(1))

                            # Retweets
                            retweet_button = tweet.locator("[data-testid='retweet']")
                            if retweet_button.count() > 0:
                                rt_text = (
                                    retweet_button.first.get_attribute("aria-label")
                                    or ""
                                )
                                rt_match = re.search(r"(\d+)", rt_text)
                                if rt_match:
                                    retweets = int(rt_match.group(1))

                            # Replies
                            reply_button = tweet.locator("[data-testid='reply']")
                            if reply_button.count() > 0:
                                reply_text = (
                                    reply_button.first.get_attribute("aria-label") or ""
                                )
                                reply_match = re.search(r"(\d+)", reply_text)
                                if reply_match:
                                    replies = int(reply_match.group(1))
                        except:
                            pass

                        # Extract tweet URL
                        tweet_url = f"https://x.com/{username}"
                        try:
                            link_element = tweet.locator("a[href*='/status/']").first
                            if link_element.count() > 0:
                                href = link_element.get_attribute("href")
                                if href:
                                    tweet_url = f"https://x.com{href}"
                        except:
                            pass

                        # Deduplication
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
                                    "url": tweet_url,
                                    "likes": likes,
                                    "retweets": retweets,
                                    "replies": replies,
                                }
                            )
                            new_tweets_found += 1
                            logger.info(
                                f"[TWITTER_PROFILE] Tweet {len(results)}/{max_items} (♥{likes} ↻{retweets})"
                            )

                    except Exception as e:
                        logger.debug(f"[TWITTER_PROFILE] Error: {e}")
                        continue

                # Scroll if needed
                if len(results) < max_items:
                    page.evaluate(
                        "window.scrollTo(0, document.documentElement.scrollHeight)"
                    )
                    time.sleep(random.uniform(2, 3))

                    if new_tweets_found == 0:
                        break

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
        logger.error(f"[TWITTER_PROFILE] {e}")
        return json.dumps({"error": str(e)}, default=str)


# =====================================================
# FACEBOOK PROFILE SCRAPER
# =====================================================


@tool
def scrape_facebook_profile(profile_url: str, max_items: int = 10):
    """
    Facebook PROFILE scraper - monitors a specific page or user profile.
    Scrapes posts from a specific Facebook page/profile timeline for competitive monitoring.

    Args:
        profile_url: Full Facebook profile/page URL (e.g., "https://www.facebook.com/DialogAxiata")
        max_items: Maximum number of posts to fetch

    Returns:
        JSON with profile's posts, engagement metrics, and timestamps
    """
    ensure_playwright()

    # Load Session
    site = "facebook"
    session_path = load_playwright_storage_state_path(
        site, out_dir="src/utils/.sessions"
    )
    if not session_path:
        session_path = load_playwright_storage_state_path(site, out_dir=".sessions")

    # Check for alternative session file name
    if not session_path:
        alt_paths = [
            os.path.join(os.getcwd(), "src", "utils", ".sessions", "fb_state.json"),
            os.path.join(os.getcwd(), ".sessions", "fb_state.json"),
            os.path.join(os.getcwd(), "fb_state.json"),
        ]
        for path in alt_paths:
            if os.path.exists(path):
                session_path = path
                logger.info(f"[FACEBOOK_PROFILE] Found session at {path}")
                break

    if not session_path:
        return json.dumps(
            {
                "error": "No Facebook session found",
                "solution": "Run the Facebook session manager to create a session",
            },
            default=str,
        )

    results = []

    try:
        with sync_playwright() as p:
            facebook_desktop_ua = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )

            browser = p.chromium.launch(headless=True)

            context = browser.new_context(
                storage_state=session_path,
                user_agent=facebook_desktop_ua,
                viewport={"width": 1400, "height": 900},
            )

            page = context.new_page()

            logger.info(f"[FACEBOOK_PROFILE] Monitoring {profile_url}")
            page.goto(profile_url, timeout=120000)
            time.sleep(5)

            # Check if logged in
            if "login" in page.url:
                logger.error("[FACEBOOK_PROFILE] Session expired")
                return json.dumps({"error": "Session invalid or expired"}, default=str)

            seen = set()
            stuck = 0
            last_scroll = 0

            MESSAGE_SELECTOR = "div[data-ad-preview='message']"

            # Poster selectors
            POSTER_SELECTORS = [
                "h3 strong a span",
                "h3 strong span",
                "h3 a span",
                "strong a span",
                "a[role='link'] span:not([class*='timestamp'])",
                "span.fwb a",
                "span.fwb",
                "a[aria-hidden='false'] span",
                "a[role='link'] span",
            ]

            def extract_poster(post):
                """Extract poster name from Facebook post"""
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

            # IMPROVED: Expand ALL "See more" buttons on page before extracting
            def expand_all_see_more():
                """Click all 'See more' buttons on the visible page"""
                see_more_selectors = [
                    # Primary Facebook "See more" patterns
                    "div[role='button'] span:text-is('See more')",
                    "div[role='button']:has-text('See more')",
                    "span:text-is('See more')",
                    "span:text-is('… See more')",
                    "span:text-is('...See more')",
                    # Alternate patterns
                    "[role='button']:has-text('See more')",
                    "div.x1i10hfl:has-text('See more')",
                    # Direct text match
                    "text='See more'",
                    "text='… See more'",
                ]

                clicked = 0
                for selector in see_more_selectors:
                    try:
                        buttons = page.locator(selector).all()
                        for btn in buttons:
                            try:
                                if btn.is_visible():
                                    btn.scroll_into_view_if_needed()
                                    time.sleep(0.2)
                                    btn.click(force=True)
                                    clicked += 1
                                    time.sleep(0.3)
                            except:
                                pass
                    except:
                        pass

                if clicked > 0:
                    logger.info(
                        f"[FACEBOOK_PROFILE] Expanded {clicked} 'See more' buttons"
                    )
                return clicked

            while len(results) < max_items:
                # First expand all "See more" on visible content
                expand_all_see_more()
                time.sleep(0.5)

                posts = page.locator(MESSAGE_SELECTOR).all()

                for post in posts:
                    try:
                        # Try to expand within this specific post container too
                        try:
                            post.scroll_into_view_if_needed()
                            time.sleep(0.3)

                            # Look for See more in parent container
                            parent = post.locator(
                                "xpath=ancestor::div[contains(@class, 'x1yztbdb')][1]"
                            )

                            post_see_more_selectors = [
                                "div[role='button'] span:text-is('See more')",
                                "span:text-is('See more')",
                                "div[role='button']:has-text('See more')",
                            ]

                            for selector in post_see_more_selectors:
                                try:
                                    btns = parent.locator(selector)
                                    if btns.count() > 0 and btns.first.is_visible():
                                        btns.first.click(force=True)
                                        time.sleep(0.5)
                                        break
                                except:
                                    pass
                        except:
                            pass

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
                                        "url": profile_url,
                                    }
                                )
                                logger.info(
                                    f"[FACEBOOK_PROFILE] Collected post {len(results)}/{max_items}"
                                )

                        if len(results) >= max_items:
                            break

                    except:
                        pass

                # Scroll
                page.evaluate("window.scrollBy(0, 2300)")
                time.sleep(1.5)

                new_scroll = page.evaluate("window.scrollY")
                stuck = stuck + 1 if new_scroll == last_scroll else 0
                last_scroll = new_scroll

                if stuck >= 3:
                    logger.info("[FACEBOOK_PROFILE] Reached end of results")
                    break

            browser.close()

            return json.dumps(
                {
                    "site": "Facebook Profile",
                    "profile_url": profile_url,
                    "results": results[:max_items],
                    "storage_state": session_path,
                },
                default=str,
            )

    except Exception as e:
        logger.error(f"[FACEBOOK_PROFILE] {e}")
        return json.dumps({"error": str(e)}, default=str)


# =====================================================
# INSTAGRAM PROFILE SCRAPER
# =====================================================


@tool
def scrape_instagram_profile(username: str, max_items: int = 15):
    """
    Instagram PROFILE scraper - monitors a specific user's profile.
    Scrapes posts from a specific Instagram user's profile grid for competitive monitoring.

    Args:
        username: Instagram username (without @)
        max_items: Maximum number of posts to fetch

    Returns:
        JSON with user's posts, captions, and engagement
    """
    ensure_playwright()

    # Load Session
    site = "instagram"
    session_path = load_playwright_storage_state_path(
        site, out_dir="src/utils/.sessions"
    )
    if not session_path:
        session_path = load_playwright_storage_state_path(site, out_dir=".sessions")

    # Check for alternative session file name
    if not session_path:
        alt_paths = [
            os.path.join(os.getcwd(), "src", "utils", ".sessions", "ig_state.json"),
            os.path.join(os.getcwd(), ".sessions", "ig_state.json"),
            os.path.join(os.getcwd(), "ig_state.json"),
        ]
        for path in alt_paths:
            if os.path.exists(path):
                session_path = path
                logger.info(f"[INSTAGRAM_PROFILE] Found session at {path}")
                break

    if not session_path:
        return json.dumps(
            {
                "error": "No Instagram session found",
                "solution": "Run the Instagram session manager to create a session",
            },
            default=str,
        )

    username = username.lstrip("@")  # Remove @ if present
    results = []

    try:
        with sync_playwright() as p:
            instagram_mobile_ua = (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
            )

            browser = p.chromium.launch(headless=True)

            context = browser.new_context(
                storage_state=session_path,
                user_agent=instagram_mobile_ua,
                viewport={"width": 430, "height": 932},
            )

            page = context.new_page()
            url = f"https://www.instagram.com/{username}/"

            logger.info(f"[INSTAGRAM_PROFILE] Monitoring @{username}")
            page.goto(url, timeout=120000)
            page.wait_for_timeout(4000)

            # Check if logged in and profile exists
            if "login" in page.url:
                logger.error("[INSTAGRAM_PROFILE] Session expired")
                return json.dumps({"error": "Session invalid or expired"}, default=str)

            # Scroll to load posts
            for _ in range(8):
                page.mouse.wheel(0, 2500)
                page.wait_for_timeout(1500)

            # Collect post links
            anchors = page.locator("a[href*='/p/'], a[href*='/reel/']").all()
            links = []

            for a in anchors:
                href = a.get_attribute("href")
                if href:
                    full = "https://www.instagram.com" + href
                    links.append(full)
                if len(links) >= max_items:
                    break

            logger.info(
                f"[INSTAGRAM_PROFILE] Found {len(links)} posts from @{username}"
            )

            # Extract captions from each post
            for link in links:
                logger.info(f"[INSTAGRAM_PROFILE] Scraping {link}")
                page.goto(link, timeout=120000)
                page.wait_for_timeout(2000)

                media_id = extract_media_id_instagram(page)
                caption = fetch_caption_via_private_api(page, media_id)

                # Fallback to direct extraction
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
                    logger.info(
                        f"[INSTAGRAM_PROFILE] Collected post {len(results)}/{max_items}"
                    )

            browser.close()

            return json.dumps(
                {
                    "site": "Instagram Profile",
                    "username": username,
                    "results": results,
                    "storage_state": session_path,
                },
                default=str,
            )

    except Exception as e:
        logger.error(f"[INSTAGRAM_PROFILE] {e}")
        return json.dumps({"error": str(e)}, default=str)


# =====================================================
# LINKEDIN PROFILE SCRAPER
# =====================================================


@tool
def scrape_linkedin_profile(company_or_username: str, max_items: int = 10):
    """
    LinkedIn PROFILE scraper - monitors a company or user profile.
    Scrapes posts from a specific LinkedIn company or personal profile for competitive monitoring.

    Args:
        company_or_username: LinkedIn company name or username (e.g., "dialog-axiata" or "company/dialog-axiata")
        max_items: Maximum number of posts to fetch

    Returns:
        JSON with profile's posts and engagement
    """
    ensure_playwright()

    # Load Session
    site = "linkedin"
    session_path = load_playwright_storage_state_path(
        site, out_dir="src/utils/.sessions"
    )
    if not session_path:
        session_path = load_playwright_storage_state_path(site, out_dir=".sessions")

    # Check for alternative session file name
    if not session_path:
        alt_paths = [
            os.path.join(os.getcwd(), "src", "utils", ".sessions", "li_state.json"),
            os.path.join(os.getcwd(), ".sessions", "li_state.json"),
            os.path.join(os.getcwd(), "li_state.json"),
        ]
        for path in alt_paths:
            if os.path.exists(path):
                session_path = path
                logger.info(f"[LINKEDIN_PROFILE] Found session at {path}")
                break

    if not session_path:
        return json.dumps(
            {
                "error": "No LinkedIn session found",
                "solution": "Run the LinkedIn session manager to create a session",
            },
            default=str,
        )

    results = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                storage_state=session_path,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1400, "height": 900},
            )

            page = context.new_page()

            # Construct profile URL
            if not company_or_username.startswith("http"):
                if "company/" in company_or_username:
                    profile_url = f"https://www.linkedin.com/company/{company_or_username.replace('company/', '')}"
                else:
                    profile_url = f"https://www.linkedin.com/in/{company_or_username}"
            else:
                profile_url = company_or_username

            logger.info(f"[LINKEDIN_PROFILE] Monitoring {profile_url}")
            page.goto(profile_url, timeout=120000)
            page.wait_for_timeout(5000)

            # Check if logged in
            if "login" in page.url or "authwall" in page.url:
                logger.error("[LINKEDIN_PROFILE] Session expired")
                return json.dumps({"error": "Session invalid or expired"}, default=str)

            # Navigate to posts section
            try:
                posts_tab = page.locator(
                    "a:has-text('Posts'), button:has-text('Posts')"
                ).first
                if posts_tab.is_visible():
                    posts_tab.click()
                    page.wait_for_timeout(3000)
            except:
                logger.warning("[LINKEDIN_PROFILE] Could not find posts tab")

            seen = set()
            no_new_data_count = 0
            previous_height = 0

            POST_CONTAINER_SELECTOR = "div.feed-shared-update-v2"
            TEXT_SELECTOR = "span.break-words"
            POSTER_SELECTOR = "span.update-components-actor__name span[dir='ltr']"

            while len(results) < max_items and no_new_data_count < 3:
                # Expand "see more" buttons
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

                posts = page.locator(POST_CONTAINER_SELECTOR).all()

                for post in posts:
                    if len(results) >= max_items:
                        break
                    try:
                        post.scroll_into_view_if_needed()
                        raw_text = ""
                        text_el = post.locator(TEXT_SELECTOR).first
                        if text_el.is_visible():
                            raw_text = text_el.inner_text()

                        # Clean text
                        cleaned_text = raw_text
                        if cleaned_text:
                            cleaned_text = re.sub(
                                r"…\s*see more", "", cleaned_text, flags=re.IGNORECASE
                            )
                            cleaned_text = re.sub(
                                r"See translation",
                                "",
                                cleaned_text,
                                flags=re.IGNORECASE,
                            )
                            cleaned_text = cleaned_text.strip()

                        poster_name = "(Unknown)"
                        poster_el = post.locator(POSTER_SELECTOR).first
                        if poster_el.is_visible():
                            poster_name = poster_el.inner_text().strip()

                        key = f"{poster_name[:20]}::{cleaned_text[:30]}"
                        if cleaned_text and len(cleaned_text) > 20 and key not in seen:
                            seen.add(key)
                            results.append(
                                {
                                    "source": "LinkedIn",
                                    "poster": poster_name,
                                    "text": cleaned_text,
                                    "url": profile_url,
                                }
                            )
                            logger.info(
                                f"[LINKEDIN_PROFILE] Found post {len(results)}/{max_items}"
                            )
                    except:
                        continue

                # Scroll
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
                    "storage_state": session_path,
                },
                default=str,
            )

    except Exception as e:
        logger.error(f"[LINKEDIN_PROFILE] {e}")
        return json.dumps({"error": str(e)}, default=str)


# =====================================================
# PRODUCT REVIEW AGGREGATOR
# =====================================================


@tool
def scrape_product_reviews(
    product_keyword: str, platforms: Optional[List[str]] = None, max_items: int = 10
):
    """
    Multi-platform product review aggregator for competitive intelligence.
    Searches for product reviews and mentions across Reddit and Twitter.

    Args:
        product_keyword: Product name to search for
        platforms: List of platforms to search (default: ["reddit", "twitter"])
        max_items: Maximum number of reviews per platform

    Returns:
        JSON with aggregated reviews from multiple platforms
    """
    if platforms is None:
        platforms = ["reddit", "twitter"]

    all_reviews = []

    try:
        # Import tool factory for independent tool instances
        # This ensures parallel execution safety
        from src.utils.tool_factory import create_tool_set

        local_tools = create_tool_set()

        # Reddit reviews
        if "reddit" in platforms:
            try:
                reddit_tool = local_tools.get("scrape_reddit")
                if reddit_tool:
                    reddit_data = reddit_tool.invoke(
                        {
                            "keywords": [f"{product_keyword} review", product_keyword],
                            "limit": max_items,
                        }
                    )

                    reddit_results = (
                        json.loads(reddit_data)
                        if isinstance(reddit_data, str)
                        else reddit_data
                    )
                    if "results" in reddit_results:
                        for item in reddit_results["results"]:
                            all_reviews.append(
                                {
                                    "platform": "Reddit",
                                    "text": item.get("text", ""),
                                    "url": item.get("url", ""),
                                    "poster": item.get("poster", "Unknown"),
                                }
                            )
                logger.info(
                    f"[PRODUCT_REVIEWS] Collected {len([r for r in all_reviews if r['platform'] == 'Reddit'])} Reddit reviews"
                )
            except Exception as e:
                logger.error(f"[PRODUCT_REVIEWS] Reddit error: {e}")

        # Twitter reviews
        if "twitter" in platforms:
            try:
                twitter_tool = local_tools.get("scrape_twitter")
                if twitter_tool:
                    twitter_data = twitter_tool.invoke(
                        {
                            "query": f"{product_keyword} review OR {product_keyword} rating",
                            "max_items": max_items,
                        }
                    )

                    twitter_results = (
                        json.loads(twitter_data)
                        if isinstance(twitter_data, str)
                        else twitter_data
                    )
                    if "results" in twitter_results:
                        for item in twitter_results["results"]:
                            all_reviews.append(
                                {
                                    "platform": "Twitter",
                                    "text": item.get("text", ""),
                                    "url": item.get("url", ""),
                                    "poster": item.get("poster", "Unknown"),
                                }
                            )
                logger.info(
                    f"[PRODUCT_REVIEWS] Collected {len([r for r in all_reviews if r['platform'] == 'Twitter'])} Twitter reviews"
                )
            except Exception as e:
                logger.error(f"[PRODUCT_REVIEWS] Twitter error: {e}")

        return json.dumps(
            {
                "product": product_keyword,
                "total_reviews": len(all_reviews),
                "reviews": all_reviews,
                "platforms_searched": platforms,
            },
            default=str,
        )

    except Exception as e:
        logger.error(f"[PRODUCT_REVIEWS] {e}")
        return json.dumps({"error": str(e)}, default=str)
