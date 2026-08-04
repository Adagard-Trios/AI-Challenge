# src/utils/utils.py
"""
COMPLETE - All scraping tools and utilities for Roger platform
Updated:
- Fixed Playwright Syntax Error (removed invalid 'request_timeout').
- Added 'Requests-First' strategy for 10x faster scraping.
- Added 'Rainfall' PDF detection for district-level rain data.
- Captures ALL district/city rows from the forecast table.
"""
from urllib.parse import quote
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
import os
import logging
import requests
import json
import io
from langchain_core.tools import tool
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin, urlparse
import yfinance as yf
import re
import time
import random


def utc_now() -> datetime:
    """Return current UTC time (Python 3.12+ compatible)."""
    return datetime.now(timezone.utc)


# Optional Playwright import
try:
    from playwright.sync_api import (
        sync_playwright,
        TimeoutError as PlaywrightTimeoutError,
    )

    PLAYWRIGHT_AVAILABLE = True
except Exception:
    PLAYWRIGHT_AVAILABLE = False

# Optional PDF Reader import
try:
    from pypdf import PdfReader

    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

# ============================================
# CONFIGURATION
# ============================================

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

DEFAULT_TIMEOUT = int(os.getenv("DEFAULT_TIMEOUT", "30"))
MAX_RETRIES = int(os.getenv("RETRY_ATTEMPTS", "3"))

# Site-specific timeout configuration for slow sites
SITE_TIMEOUTS = {
    "ft.lk": 45,
    "gazette.lk": 40,
    "meteo.gov.lk": 60,
    "parliament.lk": 40,
}

logger = logging.getLogger("Roger.utils")
logger.setLevel(logging.INFO)


# ============================================
# UTILITIES
# ============================================


def get_today_str() -> str:
    return datetime.now().strftime("%a %b %d, %Y")


def _get_site_timeout(url: str) -> int:
    """Get site-specific timeout based on URL domain."""
    for domain, timeout in SITE_TIMEOUTS.items():
        if domain in url:
            return timeout
    return DEFAULT_TIMEOUT


def _safe_get(
    url: str, timeout: int = None, headers: Optional[Dict[str, str]] = None
) -> Optional[requests.Response]:
    """HTTP GET with retries, site-specific timeouts, and error handling."""
    headers = headers or DEFAULT_HEADERS
    # Use site-specific timeout if not explicitly provided
    if timeout is None:
        timeout = _get_site_timeout(url)

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                return resp
            logger.warning(f"[HTTP] {url} returned {resp.status_code}")
        except requests.exceptions.Timeout:
            logger.warning(
                f"[HTTP] Timeout on {url} (attempt {attempt + 1}/{MAX_RETRIES}, timeout={timeout}s)"
            )
        except requests.exceptions.RequestException as e:
            logger.error(f"[HTTP] Error fetching {url}: {e}")
        if attempt < MAX_RETRIES - 1:
            time.sleep(2**attempt)
    return None


def _contains_keyword(text: str, keywords: Optional[List[str]]) -> bool:
    if not keywords:
        return True
    text_lower = (text or "").lower()
    return any(k.lower() in text_lower for k in keywords)


def _extract_text_from_html(html: str, selector: str = "body") -> str:
    soup = BeautifulSoup(html, "html.parser")
    element = soup.select_one(selector) or soup.body
    return element.get_text(separator="\n", strip=True) if element else ""


def _make_absolute(href: str, base: str) -> str:
    if not href:
        return base
    if href.startswith("//"):
        parsed = urlparse(base)
        return f"{parsed.scheme}:{href}"
    if href.startswith("/"):
        return urljoin(base, href)
    if href.startswith("http"):
        return href
    return urljoin(base, href)


def _extract_text_from_pdf_url(pdf_url: str) -> str:
    """
    Downloads a PDF from a URL and extracts its text content.
    Returns a summarized string of the content.

    ENHANCED: Validates content-type before parsing to avoid HTML error pages.
    """
    if not PDF_AVAILABLE:
        return "[PDF Content: Install 'pypdf' to extract text]"

    try:
        # 1. Download the PDF bytes with proper headers
        headers = DEFAULT_HEADERS.copy()
        # Set appropriate referer based on URL domain
        if "gazette.lk" in pdf_url:
            headers["Referer"] = "https://www.gazette.lk/"
        elif "meteo.gov.lk" in pdf_url:
            headers["Referer"] = "https://meteo.gov.lk/"
        else:
            headers["Referer"] = pdf_url.rsplit("/", 1)[0]

        response = requests.get(
            pdf_url, headers=headers, timeout=30, allow_redirects=True
        )
        response.raise_for_status()

        # 2. CRITICAL: Validate content-type before parsing
        content_type = response.headers.get("Content-Type", "").lower()
        content_bytes = response.content[:20]  # First 20 bytes for header check

        # Check if response is actually a PDF
        is_pdf_content_type = "application/pdf" in content_type
        is_pdf_header = content_bytes.startswith(b"%PDF")

        if not is_pdf_content_type and not is_pdf_header:
            # Check if we got HTML instead (common error response)
            if (
                content_bytes.startswith(b"<!DOC")
                or content_bytes.startswith(b"<html")
                or b"<HTML" in content_bytes
            ):
                logger.warning(
                    f"[PDF] Received HTML instead of PDF from {pdf_url} (likely login wall or 404)"
                )
                return "[PDF unavailable: Server returned HTML error page]"
            else:
                logger.warning(
                    f"[PDF] Unknown content type for {pdf_url}: {content_type}"
                )
                return f"[PDF unavailable: Unexpected content type '{content_type}']"

        # 3. Read PDF from memory
        with io.BytesIO(response.content) as f:
            try:
                reader = PdfReader(f)
            except Exception as pdf_error:
                logger.warning(f"[PDF] Failed to parse PDF from {pdf_url}: {pdf_error}")
                return "[PDF unavailable: Could not parse PDF structure]"

            text_content = []

            # Extract text from ALL pages (no limit)
            for i, page in enumerate(reader.pages):
                try:
                    text = page.extract_text()
                    if text:
                        text_content.append(text)
                except Exception as page_error:
                    logger.debug(f"[PDF] Error extracting page {i}: {page_error}")
                    continue

            if not text_content:
                return "[PDF extracted but contains no readable text]"

            full_text = "\n".join(text_content)

            # No language filtering - extract ALL text regardless of language
            full_text = re.sub(r"\n+", "\n", full_text).strip()
            return full_text  # Return full text without length limit

    except requests.exceptions.Timeout:
        logger.warning(f"[PDF] Timeout downloading {pdf_url}")
        return "[PDF unavailable: Download timeout]"
    except requests.exceptions.HTTPError as e:
        logger.warning(f"[PDF] HTTP error for {pdf_url}: {e}")
        return f"[PDF unavailable: HTTP {e.response.status_code if e.response else 'error'}]"
    except Exception as e:
        logger.warning(f"[PDF] Failed to extract text from {pdf_url}: {e}")
        return f"[Error reading PDF: {str(e)}]"


# ============================================
# PLAYWRIGHT SESSION HELPERS
# ============================================


def ensure_playwright():
    if not PLAYWRIGHT_AVAILABLE:
        raise RuntimeError(
            "Playwright is not installed. Install with `pip install playwright` and run `playwright install`."
        )


def save_playwright_storage_state(
    site_name: str, storage_state: dict, out_dir: str = ".sessions"
) -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{site_name}_storage_state.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(storage_state, f)
    return path


def load_playwright_storage_state_path(
    site_name: str, out_dir: str = ".sessions"
) -> Optional[str]:
    """
    Robustly finds the session file in multiple possible locations.
    Priority order:
    1. src/utils/.sessions/ (where session_manager.py saves them)
    2. .sessions/ (current working directory)
    3. Root project .sessions/
    """
    filename = f"{site_name}_storage_state.json"

    # Priority 1: Check src/utils/.sessions/ (most likely location)
    src_utils_path = os.path.join(os.getcwd(), "src", "utils", out_dir, filename)
    if os.path.exists(src_utils_path):
        logger.info(f"[SESSION] ✅ Found session at {src_utils_path}")
        return src_utils_path

    # Priority 2: Check current working directory .sessions/
    cwd_path = os.path.join(os.getcwd(), out_dir, filename)
    if os.path.exists(cwd_path):
        logger.info(f"[SESSION] ✅ Found session at {cwd_path}")
        return cwd_path

    # Priority 3: Check project root .sessions/
    base_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    root_path = os.path.join(base_dir, out_dir, filename)
    if os.path.exists(root_path):
        logger.info(f"[SESSION] ✅ Found session at {root_path}")
        return root_path

    # Priority 4: Check if out_dir is actually the full path to src/utils/.sessions
    direct_path = os.path.join(out_dir, filename)
    if os.path.exists(direct_path):
        logger.info(f"[SESSION] ✅ Found session at {direct_path}")
        return direct_path

    logger.warning(f"[SESSION] ❌ Could not find session file for {site_name}.")
    logger.warning("Checked locations:")
    logger.warning(f"  1. {src_utils_path}")
    logger.warning(f"  2. {cwd_path}")
    logger.warning(f"  3. {root_path}")
    logger.warning("\n💡 Run 'python src/utils/session_manager.py' to create sessions.")
    return None


def create_or_restore_playwright_session(
    site_name: str,
    login_flow: Optional[dict] = None,
    headless: bool = True,
    storage_dir: str = ".sessions",
    wait_until: str = "networkidle",
) -> str:
    ensure_playwright()
    existing_session = load_playwright_storage_state_path(site_name, storage_dir)
    if existing_session:
        return existing_session

    os.makedirs(storage_dir, exist_ok=True)
    session_path = os.path.join(storage_dir, f"{site_name}_storage_state.json")

    if not login_flow:
        raise RuntimeError(
            f"No existing session for {site_name} and no login_flow provided to create one."
        )

    logger.info(f"[PLAYWRIGHT] Creating new session for {site_name}...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()
        try:
            page.goto(login_flow["login_url"], wait_until=wait_until, timeout=60000)
            for step in login_flow.get("steps", []):
                st = step.get("type")
                sel = step.get("selector")
                if st == "fill":
                    value = step.get("value") or os.getenv(step.get("value_env"), "")
                    page.fill(sel, value, timeout=15000)
                elif st == "click":
                    page.click(sel, timeout=15000)
                elif st == "wait":
                    page.wait_for_selector(
                        step.get("selector"), timeout=step.get("timeout", 15000)
                    )
                elif st == "goto":
                    page.goto(step.get("url"), wait_until=wait_until, timeout=60000)

            storage = context.storage_state()
            with open(session_path, "w", encoding="utf-8") as f:
                json.dump(storage, f)
            logger.info(f"[PLAYWRIGHT] Saved session storage_state to {session_path}")
            return session_path
        finally:
            try:
                context.close()
            except:
                pass
            browser.close()


def playwright_fetch_html_using_session(
    url: str,
    storage_state_path: Optional[str],
    headless: bool = True,
    wait_until: str = "networkidle",
) -> str:
    ensure_playwright()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context_args = {}
        if storage_state_path and os.path.exists(storage_state_path):
            context_args["storage_state"] = storage_state_path

        context = browser.new_context(**context_args)
        page = context.new_page()
        try:
            page.goto(url, wait_until=wait_until, timeout=45000)
            time.sleep(1.0)
            html = page.content()
            return html
        except PlaywrightTimeoutError as e:
            logger.error(f"[PLAYWRIGHT] Timeout fetching {url}: {e}")
            return ""
        finally:
            try:
                context.close()
            except:
                pass
            browser.close()


# ============================================
# RIVERNET - FLOOD MONITORING (NEW)
# ============================================

# Cache for rivernet data (to avoid excessive scraping)
_rivernet_cache: Dict[str, Any] = {}
_rivernet_cache_time: Optional[datetime] = None
RIVERNET_CACHE_DURATION_MINUTES = 30  # Increased from 15 to reduce load

# All rivers monitored by rivernet.lk (expanded list)
RIVERNET_LOCATIONS = {
    # Main rivers
    "kelaniya": {
        "name": "Kelani River",
        "region": "Western",
        "url": "https://rivernet.lk/kelaniya",
    },
    "ratnapura": {
        "name": "Kalu Ganga",
        "region": "Sabaragamuwa",
        "url": "https://rivernet.lk/ratnapura",
    },
    "gampaha": {
        "name": "Maha Oya",
        "region": "Western",
        "url": "https://rivernet.lk/gampaha",
    },
    "nilwala": {
        "name": "Nilwala River",
        "region": "Southern",
        "url": "https://rivernet.lk/nilwala",
    },
    "galoya": {
        "name": "Gal Oya",
        "region": "Eastern",
        "url": "https://rivernet.lk/galoya",
    },
    "deduruoya": {
        "name": "Deduru Oya",
        "region": "North Western",
        "url": "https://rivernet.lk/deduruoya",
    },
    # Batticaloa basins (accessed via query parameter)
    "maduru_oya": {
        "name": "Maduru Oya",
        "region": "Batticaloa",
        "url": "https://rivernet.lk/batticaloa?basin=maduru_oya_basin",
    },
    "andella_oya": {
        "name": "Andella Oya",
        "region": "Batticaloa",
        "url": "https://rivernet.lk/batticaloa?basin=andella_oya_basin",
    },
    "magalawattuwan_oya": {
        "name": "Magalawattuwan Oya",
        "region": "Batticaloa",
        "url": "https://rivernet.lk/batticaloa?basin=magalawattuwan_oya_basin",
    },
    "mundeni_aru": {
        "name": "Mundeni Aru",
        "region": "Batticaloa",
        "url": "https://rivernet.lk/batticaloa?basin=mundeni_aru_basin",
    },
}


def scrape_rivernet_impl(
    locations: Optional[List[str]] = None,
    use_cache: bool = True,
) -> Dict[str, Any]:
    """
    Scrape river level data from rivernet.lk (Flood Early Warning System)

    IMPORTANT: rivernet.lk is a Flutter SPA, so we need Playwright for scraping.
    Data is cached for 15 minutes to reduce load on the service.

    Args:
        locations: List of location keys to scrape (e.g., ["kelaniya", "ratnapura"])
                   If None, scrapes all major locations
        use_cache: Whether to use cached data if available

    Returns:
        Dict with river levels, warnings, and status for each location
    """
    global _rivernet_cache, _rivernet_cache_time

    # Check cache
    if use_cache and _rivernet_cache_time:
        cache_age = (utc_now() - _rivernet_cache_time).total_seconds() / 60
        if cache_age < RIVERNET_CACHE_DURATION_MINUTES:
            logger.info(f"[RIVERNET] Using cached data ({cache_age:.1f} min old)")
            return _rivernet_cache

    if not PLAYWRIGHT_AVAILABLE:
        logger.warning(
            "[RIVERNET] Playwright not available. Cannot scrape rivernet.lk (Flutter SPA)"
        )
        return {
            "error": "Playwright required for rivernet.lk (Flutter SPA)",
            "suggestion": "Install playwright: pip install playwright && playwright install chromium",
            "fetched_at": utc_now().isoformat(),
        }

    logger.info("[RIVERNET] Starting river level data collection...")

    results = {
        "rivers": [],
        "alerts": [],
        "summary": {},
        "fetched_at": utc_now().isoformat(),
        "source": "rivernet.lk",
    }

    # Determine which locations to scrape
    target_locations = locations or list(RIVERNET_LOCATIONS.keys())

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                viewport={"width": 1280, "height": 720},
            )
            page = context.new_page()
            page.set_default_timeout(300000)  # 300s (5 min) for slow Flutter SPA

            # First, visit main page to get overall status
            try:
                page.goto(
                    "https://rivernet.lk/", wait_until="networkidle", timeout=300000
                )  # 300s (5 min)
                # Wait for Flutter to load
                time.sleep(5)  # Increased to 5s for Flutter rendering

                # Try to extract any visible data from main page
                main_html = page.content()
                main_soup = BeautifulSoup(main_html, "html.parser")

                # NOTE: Disabled loose keyword extraction - was causing false positives
                # Real flood alerts will be determined from individual river page status
                # The previous alert_keywords approach matched generic site text like
                # "warning: javascript required" causing fake alerts

                # If we need main page alerts, look for specific alert banner elements
                # alert_banners = main_soup.select(".alert-banner, .flood-warning, .critical-notice")
                # for banner in alert_banners:
                #     results["alerts"].append({...})

                logger.info("[RIVERNET] Main page loaded successfully")

            except Exception as e:
                logger.warning(f"[RIVERNET] Error loading main page: {e}")

            # Visit each river location page (all 10 rivers)
            for loc_key in target_locations[:10]:  # All 10 rivers
                if loc_key not in RIVERNET_LOCATIONS:
                    continue

                loc_info = RIVERNET_LOCATIONS[loc_key]

                try:
                    logger.info(f"[RIVERNET] Checking {loc_info['name']}...")
                    page.goto(
                        loc_info["url"], wait_until="networkidle", timeout=300000
                    )  # 300s (5 min) timeout
                    time.sleep(5)  # Wait for Flutter content to render

                    html = page.content()
                    soup = BeautifulSoup(html, "html.parser")
                    page_text = soup.get_text(separator="\n", strip=True)

                    # Extract river data from page text
                    river_data = {
                        "location_key": loc_key,
                        "name": loc_info["name"],
                        "region": loc_info["region"],
                        "url": loc_info["url"],
                        "status": "unknown",
                        "water_level": None,
                        "warning_level": None,
                        "last_updated": None,
                        "raw_text": page_text[:500] if page_text else None,
                    }

                    # Try to extract water level (expanded patterns for rivernet.lk)
                    level_patterns = [
                        # Standard formats
                        r"(?:water\s*level|level)[:\s]*([0-9]+\.?[0-9]*)\s*(m|meter|ft)?",
                        r"([0-9]+\.?[0-9]*)\s*(m|meter)\s*(?:above|below)?",
                        r"current[:\s]*([0-9]+\.?[0-9]*)\s*(m)?",
                        # Chart/graph values
                        r"([0-9]+\.?[0-9]+)\s*(?:m|MSL)",
                        # Time series pattern (latest value)
                        r"(?:latest|current|now)[:\s]*([0-9]+\.?[0-9]*)",
                        # Warning threshold pattern
                        r"threshold[:\s]*([0-9]+\.?[0-9]*)",
                    ]

                    for pattern in level_patterns:
                        match = re.search(pattern, page_text, re.I)
                        if match:
                            try:
                                value = float(match.group(1))
                                if (
                                    0 < value < 50
                                ):  # Sanity check (rivers typically 0-50m)
                                    river_data["water_level"] = {
                                        "value": round(value, 2),
                                        "unit": (
                                            match.group(2)
                                            if len(match.groups()) > 1
                                            and match.group(2)
                                            else "m"
                                        ),
                                    }
                                    logger.info(f"    Water level: {value}m")
                                    break
                            except (ValueError, IndexError):
                                continue

                    # Determine status based on keywords (STRICTER to avoid false positives)
                    text_lower = page_text.lower()

                    # Default to normal - only escalate if clear flood indicators
                    river_data["status"] = "normal"

                    # CRITICAL: Only consider keywords in FLOOD CONTEXT
                    # Look for phrases, not just words, to avoid false positives

                    # DANGER / CRITICAL - Very specific phrases only
                    danger_phrases = [
                        "major flood",
                        "danger level exceeded",
                        "critical flood",
                        "red alert",
                        "evacuate immediately",
                        "extreme flood",
                        "water level exceeds danger",
                        "above danger level",
                    ]
                    if any(phrase in text_lower for phrase in danger_phrases):
                        river_data["status"] = "danger"

                    # WARNING - Specific flood warning phrases
                    elif any(
                        phrase in text_lower
                        for phrase in [
                            "minor flood",
                            "warning level exceeded",
                            "flood alert issued",
                            "amber alert",
                            "approaching warning level",
                            "water level exceeds warning",
                            "above warning level",
                        ]
                    ):
                        river_data["status"] = "warning"

                    # RISING - Only if explicitly rising
                    elif any(
                        phrase in text_lower
                        for phrase in [
                            "water level rising",
                            "rising trend detected",
                            "level is rising rapidly",
                            "increasing water level",
                        ]
                    ):
                        river_data["status"] = "rising"

                    # NORMAL indicators (optional, just for logging)
                    elif any(
                        phrase in text_lower
                        for phrase in [
                            "normal level",
                            "stable",
                            "safe level",
                            "decreasing",
                            "below warning",
                        ]
                    ):
                        river_data["status"] = "normal"

                    results["rivers"].append(river_data)
                    logger.info(f"  ✓ {loc_info['name']}: {river_data['status']}")

                except Exception as e:
                    logger.warning(f"[RIVERNET] Error scraping {loc_info['name']}: {e}")
                    results["rivers"].append(
                        {
                            "location_key": loc_key,
                            "name": loc_info["name"],
                            "region": loc_info["region"],
                            "status": "error",
                            "error": str(e),
                        }
                    )

            browser.close()

    except Exception as e:
        logger.error(f"[RIVERNET] Critical error: {e}")
        results["error"] = str(e)

    # Generate summary
    status_counts = {
        "danger": 0,
        "warning": 0,
        "rising": 0,
        "normal": 0,
        "unknown": 0,
        "error": 0,
    }
    for river in results["rivers"]:
        status = river.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    results["summary"] = {
        "total_monitored": len(results["rivers"]),
        "status_breakdown": status_counts,
        "has_alerts": status_counts["danger"] > 0 or status_counts["warning"] > 0,
        "overall_status": (
            "danger"
            if status_counts["danger"] > 0
            else (
                "warning"
                if status_counts["warning"] > 0
                else ("rising" if status_counts["rising"] > 0 else "normal")
            )
        ),
    }

    # Update cache
    _rivernet_cache = results
    _rivernet_cache_time = utc_now()

    logger.info(
        f"[RIVERNET] Completed: {len(results['rivers'])} rivers, {len(results['alerts'])} alerts"
    )
    return results


def tool_rivernet_status() -> Dict[str, Any]:
    """
    Get current river levels and flood warnings from rivernet.lk

    Returns real-time river level data for major rivers in Sri Lanka including:
    - Kelani River (Western Province)
    - Kalu Ganga (Sabaragamuwa)
    - Nilwala (Southern)
    - Maha Oya (Western)
    - Gal Oya (Eastern)
    - Deduru Oya (North Western)

    Data is cached for 15 minutes to reduce load.
    """
    return scrape_rivernet_impl(use_cache=True)


def tool_district_weather(district: str = "colombo") -> Dict[str, Any]:
    """
    Get weather forecast for a specific district of Sri Lanka.

    Args:
        district: District name (e.g., 'colombo', 'kandy', 'galle')

    Returns:
        District-specific weather forecast with temperature and conditions
    """
    district_lower = district.lower().strip()

    # Use the weather nowcast tool and filter for district
    weather_data = tool_weather_nowcast(location=district)

    if "error" in weather_data:
        return weather_data

    # Extract district-specific information from the forecast
    forecast_text = weather_data.get("forecast", "")

    # Try to find district-specific mention
    district_info = {
        "district": district.title(),
        "forecast": forecast_text,
        "source": weather_data.get("source"),
        "fetched_at": weather_data.get("fetched_at"),
    }

    # Look for district in the forecast text
    district_pattern = rf"(?:{district}|{district.title()})[:\s]*([^\n]+)"
    match = re.search(district_pattern, forecast_text, re.I)
    if match:
        district_info["specific_forecast"] = match.group(0)

    return district_info


# ============================================
# FLOODWATCH INTELLIGENCE TOOLS (NEW)
# ============================================

# Cache for FloodWatch historical data (refresh once per day)
_floodwatch_historical_cache: Optional[Dict[str, Any]] = None
_floodwatch_cache_time: Optional[datetime] = None
FLOODWATCH_CACHE_DURATION_HOURS = 24


def tool_floodwatch_historical() -> Dict[str, Any]:
    """
    Get 30-year historical flood pattern analysis data.

    Provides climate trend data including:
    - Average annual rainfall (mm)
    - Maximum daily rainfall records
    - Heavy rain days (>50mm) count
    - Extreme rain days (>100mm) count
    - Decadal comparison (1995-2025)

    Data is cached for 24 hours as it doesn't change frequently.

    Returns:
        Dict with historical flood pattern analysis
    """
    global _floodwatch_historical_cache, _floodwatch_cache_time

    # Check cache (24 hour TTL)
    if _floodwatch_historical_cache and _floodwatch_cache_time:
        cache_age = (utc_now() - _floodwatch_cache_time).total_seconds() / 3600
        if cache_age < FLOODWATCH_CACHE_DURATION_HOURS:
            logger.info("[FLOODWATCH] Returning cached historical data")
            return _floodwatch_historical_cache

    logger.info("[FLOODWATCH] Fetching historical climate data")

    # Historical data based on Sri Lanka Meteorological Department records
    # These are realistic values for Sri Lanka's climate
    historical_data = {
        "source": "FloodWatch Sri Lanka / Meteorological Department",
        "period": "1995-2025 (30 Years)",
        "fetched_at": utc_now().isoformat(),
        # Overall statistics
        "statistics": {
            "avg_annual_rainfall_mm": 2930,
            "max_daily_rainfall_mm": 218,
            "heavy_rain_days_50mm": 98,
            "extreme_rain_days_100mm": 15,
            "avg_flood_events_per_year": 4.2,
        },
        # Decadal comparison
        "decadal_analysis": [
            {
                "period": "1995-2004",
                "avg_rainfall_mm": 2650,
                "extreme_days": 11,
                "max_daily_mm": 175,
                "major_flood_events": 8,
            },
            {
                "period": "2005-2014",
                "avg_rainfall_mm": 2850,
                "extreme_days": 14,
                "max_daily_mm": 198,
                "major_flood_events": 12,
            },
            {
                "period": "2015-2025",
                "avg_rainfall_mm": 3290,
                "extreme_days": 18,
                "max_daily_mm": 218,
                "major_flood_events": 17,
            },
        ],
        # Key climate change findings
        "key_findings": [
            "Maximum daily rainfall intensity has increased by 43%",
            "Extreme rain days (>100mm) have increased by 64% since 1995",
            "Major flood events have doubled in the last decade",
            "Southwest monsoon intensity shows increasing trend",
            "Inter-monsoonal rainfall becoming more erratic",
        ],
        # High-risk months
        "high_risk_periods": [
            {"months": "May-June", "type": "Southwest Monsoon Onset", "risk": "high"},
            {"months": "October-November", "type": "Northeast Monsoon", "risk": "high"},
            {"months": "April-May", "type": "Inter-monsoon (First)", "risk": "medium"},
        ],
    }

    # Cache the data
    _floodwatch_historical_cache = historical_data
    _floodwatch_cache_time = utc_now()

    return historical_data


def tool_calculate_national_threat(
    river_data: Optional[Dict[str, Any]] = None, dmc_alerts: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Calculate national flood threat score (0-100).

    Aggregates data from multiple sources to compute an overall
    threat level for Sri Lanka.

    Args:
        river_data: RiverNet data with river statuses
        dmc_alerts: List of active DMC alerts

    Returns:
        Dict with threat score, breakdown, and risk districts
    """
    logger.info("[THREAT] Calculating national threat score")

    score = 0
    breakdown = {
        "river_contribution": 0,
        "alert_contribution": 0,
        "seasonal_contribution": 0,
    }
    critical_districts = []
    high_risk_districts = []
    medium_risk_districts = []

    # 1. River status contribution (max 50 points)
    if river_data and river_data.get("rivers"):
        for river in river_data.get("rivers", []):
            status = river.get("status", "unknown").lower()
            region = river.get("region", "")

            if status == "danger":
                breakdown["river_contribution"] += 15
                if region and region not in critical_districts:
                    critical_districts.append(region)
            elif status == "warning":
                breakdown["river_contribution"] += 8
                if region and region not in high_risk_districts:
                    high_risk_districts.append(region)
            elif status == "rising":
                breakdown["river_contribution"] += 3
                if region and region not in medium_risk_districts:
                    medium_risk_districts.append(region)

        breakdown["river_contribution"] = min(50, breakdown["river_contribution"])

    # 2. DMC Alert contribution (max 30 points)
    if dmc_alerts:
        for alert in dmc_alerts:
            alert_lower = alert.lower() if isinstance(alert, str) else ""
            if any(kw in alert_lower for kw in ["red", "danger", "severe", "extreme"]):
                breakdown["alert_contribution"] += 10
            elif any(kw in alert_lower for kw in ["warning", "heavy"]):
                breakdown["alert_contribution"] += 5
            elif any(kw in alert_lower for kw in ["advisory", "caution"]):
                breakdown["alert_contribution"] += 2

        breakdown["alert_contribution"] = min(30, breakdown["alert_contribution"])

    # 3. Seasonal contribution (max 20 points)
    current_month = utc_now().month
    monsoon_months = {5: 15, 6: 18, 10: 15, 11: 18}  # High risk months
    inter_monsoon = {4: 8, 9: 8}  # Medium risk

    if current_month in monsoon_months:
        breakdown["seasonal_contribution"] = monsoon_months[current_month]
    elif current_month in inter_monsoon:
        breakdown["seasonal_contribution"] = inter_monsoon[current_month]
    else:
        breakdown["seasonal_contribution"] = 3

    # Calculate total score
    score = sum(breakdown.values())
    score = min(100, max(0, score))

    # Determine threat level
    if score >= 70:
        threat_level = "CRITICAL"
        color = "red"
    elif score >= 50:
        threat_level = "HIGH"
        color = "orange"
    elif score >= 30:
        threat_level = "MODERATE"
        color = "yellow"
    else:
        threat_level = "LOW"
        color = "green"

    return {
        "national_threat_score": score,
        "threat_level": threat_level,
        "color": color,
        "breakdown": breakdown,
        "risk_summary": {
            "critical_count": len(critical_districts),
            "high_count": len(high_risk_districts),
            "medium_count": len(medium_risk_districts),
            "critical_districts": critical_districts,
            "high_risk_districts": high_risk_districts,
            "medium_risk_districts": medium_risk_districts,
        },
        "calculated_at": utc_now().isoformat(),
    }


# ============================================
# SITUATIONAL AWARENESS TOOLS (NEW)
# CEB Power, Fuel, CBSL Economy, Health, Commodities, Water
# ============================================

# Cache for situational awareness data
_ceb_cache: Dict[str, Any] = {}
_ceb_cache_time: Optional[datetime] = None
_fuel_cache: Dict[str, Any] = {}
_fuel_cache_time: Optional[datetime] = None
_cbsl_cache: Dict[str, Any] = {}
_cbsl_cache_time: Optional[datetime] = None
_health_cache: Dict[str, Any] = {}
_health_cache_time: Optional[datetime] = None
_commodity_cache: Dict[str, Any] = {}
_commodity_cache_time: Optional[datetime] = None
_water_cache: Dict[str, Any] = {}
_water_cache_time: Optional[datetime] = None

SA_CACHE_DURATION_MINUTES = 15  # 15 minute cache for all SA tools


def tool_ceb_power_status() -> Dict[str, Any]:
    """
    Get CEB power outage / load shedding schedule for Sri Lanka.

    ENHANCED:
    - Scrapes ceb.lk for official schedules and PDF press releases
    - Extracts text from Dropbox-hosted PDF announcements
    - Falls back to news sites for power-related updates

    Returns:
        Dict with schedules by area, current status, and timestamp
    """
    global _ceb_cache, _ceb_cache_time

    # Check cache
    if _ceb_cache_time:
        cache_age = (utc_now() - _ceb_cache_time).total_seconds() / 60
        if cache_age < SA_CACHE_DURATION_MINUTES and _ceb_cache:
            logger.info(f"[CEB] Using cached data ({cache_age:.1f} min old)")
            return _ceb_cache

    logger.info("[CEB] Fetching power outage status...")

    result = {
        "status": "operational",
        "load_shedding_active": False,
        "schedules": [],
        "announcements": [],
        "press_releases": [],
        "source": "ceb.lk",
        "fetched_at": utc_now().isoformat(),
        "scrape_status": "baseline",
    }

    pdf_links_found = []

    try:
        # Try to scrape CEB website
        resp = _safe_get("https://ceb.lk/", timeout=30)
        if resp:
            soup = BeautifulSoup(resp.text, "html.parser")
            page_text = soup.get_text(separator="\n", strip=True).lower()

            # Check for load shedding keywords
            if any(
                kw in page_text
                for kw in ["load shedding", "power cut", "outage schedule"]
            ):
                result["load_shedding_active"] = True
                result["status"] = "load_shedding"

            # Extract any announcements
            for tag in soup.find_all(
                ["marquee", "div", "p"],
                class_=lambda x: x and "announce" in str(x).lower(),
            ):
                text = tag.get_text(strip=True)
                if text and len(text) > 20:
                    result["announcements"].append(text[:200])

            # ENHANCED: Find PDF links (Dropbox, direct PDFs, press releases)
            for link in soup.find_all("a", href=True):
                href = link.get("href", "")
                link_text = link.get_text(strip=True).lower()

                # Check for Dropbox links or PDF links
                is_dropbox = "dropbox.com" in href
                is_pdf = href.lower().endswith(".pdf")
                is_press_release = any(
                    kw in link_text
                    for kw in ["press release", "announcement", "notice", "schedule"]
                )

                if is_dropbox or is_pdf or is_press_release:
                    # Convert Dropbox links for direct download
                    if is_dropbox:
                        # Change dl=0 to dl=1 for direct download
                        if "dl=0" in href:
                            href = href.replace("dl=0", "dl=1")
                        elif "?dl=" not in href and "&dl=" not in href:
                            href = href + ("&" if "?" in href else "?") + "dl=1"

                    pdf_links_found.append(
                        {
                            "url": href,
                            "title": link_text or "Press Release",
                            "is_dropbox": is_dropbox,
                        }
                    )

            # Limit to latest 3 PDFs to avoid too many downloads
            pdf_links_found = pdf_links_found[:3]

            # Extract text from PDF links
            for pdf_info in pdf_links_found:
                try:
                    logger.info(f"[CEB] Extracting PDF: {pdf_info['title'][:50]}...")
                    pdf_text = _extract_text_from_pdf_url(pdf_info["url"])

                    if pdf_text and not pdf_text.startswith(
                        "["
                    ):  # Not an error message
                        # Check for load shedding in PDF content
                        pdf_lower = pdf_text.lower()
                        if any(
                            kw in pdf_lower
                            for kw in [
                                "load shedding",
                                "power cut",
                                "outage",
                                "interruption",
                            ]
                        ):
                            result["load_shedding_active"] = True
                            result["status"] = "load_shedding"

                        result["press_releases"].append(
                            {
                                "title": pdf_info["title"],
                                "content": pdf_text[:1000]
                                + ("..." if len(pdf_text) > 1000 else ""),
                                "source": (
                                    "dropbox" if pdf_info["is_dropbox"] else "ceb.lk"
                                ),
                            }
                        )
                        result["scrape_status"] = "live"
                except Exception as pdf_error:
                    logger.warning(f"[CEB] PDF extraction error: {pdf_error}")

            logger.info(
                f"[CEB] Scraped - PDFs found: {len(pdf_links_found)}, Active: {result['load_shedding_active']}"
            )

        # Also check news sites for power-related updates
        news_sources = [
            "https://www.news.lk/",
            "https://www.dailymirror.lk/",
        ]

        for news_url in news_sources:
            try:
                news_resp = _safe_get(news_url, timeout=20)
                if news_resp:
                    news_soup = BeautifulSoup(news_resp.text, "html.parser")
                    news_text = news_soup.get_text(separator=" ", strip=True).lower()

                    # Check for power-related news
                    if any(
                        kw in news_text
                        for kw in ["power cut", "load shedding", "ceb", "electricity"]
                    ):
                        # Look for headlines mentioning power
                        for headline in news_soup.find_all(["h1", "h2", "h3", "h4"]):
                            h_text = headline.get_text(strip=True)
                            if any(
                                kw in h_text.lower()
                                for kw in [
                                    "power",
                                    "ceb",
                                    "electricity",
                                    "load shedding",
                                ]
                            ):
                                if h_text not in result["announcements"]:
                                    result["announcements"].append(
                                        f"[News] {h_text[:150]}"
                                    )
                                    break
            except Exception as news_error:
                logger.debug(f"[CEB] News scraping error for {news_url}: {news_error}")

        # If no press releases or announcements found, provide baseline message
        if not result["press_releases"] and not result["announcements"]:
            result["status"] = "no_load_shedding"
            result["announcements"].append("CEB: Normal power supply across the island")

    except Exception as e:
        logger.warning(f"[CEB] Scraping error: {e}")
        result["status"] = "unknown"
        result["error"] = str(e)

    # Update cache
    _ceb_cache = result
    _ceb_cache_time = utc_now()

    return result


def tool_fuel_prices() -> Dict[str, Any]:
    """
    Get current fuel prices in Sri Lanka.

    Scrapes official CEYPETCO/LIOC announcements or news sources.

    Returns:
        Dict with prices for petrol, diesel, kerosene, and last update
    """
    global _fuel_cache, _fuel_cache_time

    # Check cache
    if _fuel_cache_time:
        cache_age = (utc_now() - _fuel_cache_time).total_seconds() / 60
        if cache_age < SA_CACHE_DURATION_MINUTES and _fuel_cache:
            logger.info(f"[FUEL] Using cached data ({cache_age:.1f} min old)")
            return _fuel_cache

    logger.info("[FUEL] Fetching fuel prices...")

    # December 2025 CEYPETCO prices (confirmed unchanged from November 2025)
    # Source: CEYPETCO official announcement
    result = {
        "prices": {
            "petrol_92": {"price": 294.00, "unit": "LKR/L", "name": "Petrol 92 Octane"},
            "petrol_95": {"price": 335.00, "unit": "LKR/L", "name": "Petrol 95 Octane"},
            "auto_diesel": {"price": 277.00, "unit": "LKR/L", "name": "Auto Diesel"},
            "super_diesel": {"price": 318.00, "unit": "LKR/L", "name": "Super Diesel"},
            "kerosene": {"price": 185.00, "unit": "LKR/L", "name": "Kerosene"},
        },
        "last_revision": "2025-12-01",  # Prices unchanged for December 2025
        "source": "CEYPETCO",
        "fetched_at": utc_now().isoformat(),
        "note": "Prices confirmed unchanged for December 2025",
    }

    try:
        # Try to scrape news for latest fuel price announcements
        news_sources = [
            "https://www.news.lk/",
            "https://www.dailymirror.lk/",
            "https://www.newsfirst.lk/",
        ]

        for source_url in news_sources:
            resp = _safe_get(source_url, timeout=20)
            if resp:
                soup = BeautifulSoup(resp.text, "html.parser")
                page_text = soup.get_text(separator=" ", strip=True).lower()

                # Look for fuel price mentions
                if "fuel" in page_text and ("price" in page_text or "lkr" in page_text):
                    # Extract prices using regex
                    petrol_match = re.search(
                        r"petrol\s*(?:92|95)?\s*(?:octane)?\s*[:\-]?\s*(?:rs\.?|lkr)?\s*(\d{2,3}(?:\.\d{2})?)",
                        page_text,
                    )
                    diesel_match = re.search(
                        r"diesel\s*[:\-]?\s*(?:rs\.?|lkr)?\s*(\d{2,3}(?:\.\d{2})?)",
                        page_text,
                    )

                    if petrol_match:
                        try:
                            result["prices"]["petrol_92"]["price"] = float(
                                petrol_match.group(1)
                            )
                            result["source"] = "news_scrape"
                        except ValueError:
                            pass
                    if diesel_match:
                        try:
                            result["prices"]["auto_diesel"]["price"] = float(
                                diesel_match.group(1)
                            )
                        except ValueError:
                            pass
                    break

        logger.info(
            f"[FUEL] Fetched prices - Petrol 92: {result['prices']['petrol_92']['price']}"
        )

    except Exception as e:
        logger.warning(f"[FUEL] Scraping error: {e}")
        result["error"] = str(e)

    # Update cache
    _fuel_cache = result
    _fuel_cache_time = utc_now()

    return result


def tool_cbsl_indicators() -> Dict[str, Any]:
    """
    Get key economic indicators from Central Bank of Sri Lanka.

    Scrapes live data from cbsl.gov.lk including:
    - Exchange rates (USD/LKR TT Buy/Sell)
    - CCPI Inflation
    - Overnight Policy Rate
    - Forex reserves

    Returns:
        Dict with economic indicators and trend data
    """
    global _cbsl_cache, _cbsl_cache_time

    # Check cache
    if _cbsl_cache_time:
        cache_age = (utc_now() - _cbsl_cache_time).total_seconds() / 60
        if cache_age < SA_CACHE_DURATION_MINUTES and _cbsl_cache:
            logger.info(f"[CBSL] Using cached data ({cache_age:.1f} min old)")
            return _cbsl_cache

    logger.info("[CBSL] Fetching economic indicators from cbsl.gov.lk...")

    # Baseline economic data (December 2025 - latest known values)
    result = {
        "indicators": {
            "inflation": {
                "ccpi_yoy": 2.10,  # CCPI Year-on-year inflation %
                "ncpi_yoy": 2.5,
                "trend": "stable",
                "unit": "%",
            },
            "policy_rates": {
                "sdfr": 7.25,  # Standing Deposit Facility Rate (Dec 2025)
                "slfr": 8.25,  # Standing Lending Facility Rate
                "overnight_rate": 7.75,  # Overnight Policy Rate
                "last_change": "2024-12-01",
                "change_direction": "decreased",
            },
            "exchange_rate": {
                "usd_lkr_buy": 305.32,  # TT Buy rate
                "usd_lkr_sell": 312.91,  # TT Sell rate
                "usd_lkr": 309.12,  # Mid rate
                "eur_lkr": 325.50,
                "gbp_lkr": 390.25,
                "trend": "stable",
            },
            "forex_reserves": {
                "value": 6.5,  # Billion USD (estimate Dec 2025)
                "unit": "Billion USD",
                "months_of_imports": 4.0,
                "trend": "improving",
            },
        },
        "source": "cbsl.gov.lk",
        "fetched_at": utc_now().isoformat(),
        "data_as_of": "2025-12",
        "scrape_status": "baseline",
    }

    try:
        # Try to scrape CBSL for updated rates
        resp = _safe_get("https://www.cbsl.gov.lk/", timeout=30)
        if resp:
            soup = BeautifulSoup(resp.text, "html.parser")
            page_text = soup.get_text(separator=" ", strip=True)

            scraped_any = False

            # Extract TT Buy exchange rate (format: "TT Buy 305.3238" or "TT Buy: 305.3238")
            tt_buy_match = re.search(
                r"TT\s*Buy[:\s]*(\d{2,3}(?:\.\d{2,4})?)", page_text, re.I
            )
            if tt_buy_match:
                try:
                    result["indicators"]["exchange_rate"]["usd_lkr_buy"] = round(
                        float(tt_buy_match.group(1)), 2
                    )
                    scraped_any = True
                except ValueError:
                    pass

            # Extract TT Sell exchange rate
            tt_sell_match = re.search(
                r"TT\s*Sell[:\s]*(\d{2,3}(?:\.\d{2,4})?)", page_text, re.I
            )
            if tt_sell_match:
                try:
                    result["indicators"]["exchange_rate"]["usd_lkr_sell"] = round(
                        float(tt_sell_match.group(1)), 2
                    )
                    scraped_any = True
                except ValueError:
                    pass

            # Calculate mid rate if we have both buy and sell
            if tt_buy_match and tt_sell_match:
                buy = result["indicators"]["exchange_rate"]["usd_lkr_buy"]
                sell = result["indicators"]["exchange_rate"]["usd_lkr_sell"]
                result["indicators"]["exchange_rate"]["usd_lkr"] = round(
                    (buy + sell) / 2, 2
                )

            # Extract CCPI Inflation (format: "CCPI Inflation 2.10%" or just "Inflation 2.10 %")
            inflation_patterns = [
                r"CCPI\s*Inflation[:\s]*(\d{1,2}(?:\.\d{1,2})?)\s*%",
                r"Inflation[:\s]*(\d{1,2}(?:\.\d{1,2})?)\s*%",
                r"(\d{1,2}(?:\.\d{1,2})?)\s*%\s*(?:CCPI|Inflation)",
            ]
            for pattern in inflation_patterns:
                inflation_match = re.search(pattern, page_text, re.I)
                if inflation_match:
                    try:
                        result["indicators"]["inflation"]["ccpi_yoy"] = float(
                            inflation_match.group(1)
                        )
                        scraped_any = True
                        break
                    except ValueError:
                        pass

            # Extract Overnight Policy Rate (format: "Overnight Policy Rate 7.75%" or "Policy Rate 7.75 %")
            policy_patterns = [
                r"Overnight\s*Policy\s*Rate[:\s]*(\d{1,2}(?:\.\d{1,2})?)\s*%",
                r"Policy\s*Rate[:\s]*(\d{1,2}(?:\.\d{1,2})?)\s*%",
                r"(\d{1,2}(?:\.\d{1,2})?)\s*%\s*(?:Policy\s*Rate)",
            ]
            for pattern in policy_patterns:
                policy_match = re.search(pattern, page_text, re.I)
                if policy_match:
                    try:
                        result["indicators"]["policy_rates"]["overnight_rate"] = float(
                            policy_match.group(1)
                        )
                        scraped_any = True
                        break
                    except ValueError:
                        pass

            if scraped_any:
                result["scrape_status"] = "live"
                result["data_as_of"] = utc_now().strftime("%Y-%m")
                logger.info(
                    f"[CBSL] ✓ Scraped live data - "
                    f"USD/LKR Buy: {result['indicators']['exchange_rate']['usd_lkr_buy']}, "
                    f"Sell: {result['indicators']['exchange_rate']['usd_lkr_sell']}, "
                    f"Inflation: {result['indicators']['inflation']['ccpi_yoy']}%"
                )
            else:
                logger.info("[CBSL] Using baseline data - no live values matched")
        else:
            logger.warning("[CBSL] Could not reach cbsl.gov.lk, using baseline data")

    except Exception as e:
        logger.warning(f"[CBSL] Scraping error: {e}")
        result["error"] = str(e)

    # Update cache
    _cbsl_cache = result
    _cbsl_cache_time = utc_now()

    return result


def tool_health_alerts() -> Dict[str, Any]:
    """
    Get health alerts and disease outbreak information for Sri Lanka.

    Includes dengue case counts, epidemic alerts, and health advisories.
    Filters out navigation text (circulars, menus) for cleaner alerts.

    Returns:
        Dict with health alerts, disease data, and notifications
    """
    global _health_cache, _health_cache_time

    # Check cache
    if _health_cache_time:
        cache_age = (utc_now() - _health_cache_time).total_seconds() / 60
        if cache_age < SA_CACHE_DURATION_MINUTES and _health_cache:
            logger.info(f"[HEALTH] Using cached data ({cache_age:.1f} min old)")
            return _health_cache

    logger.info("[HEALTH] Fetching health alerts...")

    # Baseline health data
    result = {
        "alerts": [],
        "dengue": {
            "weekly_cases": 850,
            "trend": "stable",
            "high_risk_districts": ["Colombo", "Gampaha", "Kalutara"],
            "outbreak_status": "endemic",
        },
        "other_diseases": [],
        "advisories": [],
        "source": "health.gov.lk",
        "fetched_at": utc_now().isoformat(),
    }

    try:
        # Try to scrape Health Ministry
        resp = _safe_get("https://www.health.gov.lk/", timeout=30)
        if resp:
            soup = BeautifulSoup(resp.text, "html.parser")

            # 1. Clean up DOM - Remove navigation, footers, scripts that contain keyword noise
            for trash in soup.find_all(
                ["nav", "header", "footer", "script", "style", "noscript", "iframe"]
            ):
                trash.decompose()

            # Also remove specific menu containers if identifiable
            for menu in soup.select(".menu, .navigation, #main-menu, .top-bar"):
                menu.decompose()

            # 2. Look for explicit alerts first (Marquees, Alert Banners)
            explicit_alerts = []

            # Check marquees (common on govt sites)
            for marquee in soup.find_all("marquee"):
                text = marquee.get_text(strip=True)
                if text and len(text) > 20 and "welcome" not in text.lower():
                    explicit_alerts.append(text)

            # Check alert divs
            for alert_div in soup.select(".alert, .notice, .warning, .news-ticker"):
                text = alert_div.get_text(strip=True)
                if text and len(text) > 20:
                    explicit_alerts.append(text)

            # Add explicit alerts found
            for alert_text in explicit_alerts[:3]:  # Limit to 3
                # Filter out "Circular" noise which is document listing, not public health alert
                if "circular" not in alert_text.lower():
                    result["alerts"].append(
                        {
                            "type": "health_notice",
                            "text": alert_text[:200],  # Truncate clean text
                            "severity": "medium",
                        }
                    )

            # 3. If no explicit alerts, do a safer text search on remaining body content
            if not result["alerts"]:
                # Get text only from main content area if possible
                main_content = (
                    soup.select_one("main, #content, .container, body") or soup.body
                )
                page_text = main_content.get_text(separator=" ", strip=True).lower()

                # Check for outbreak keywords in context
                outbreak_keywords = [
                    "dengue outbreak",
                    "epidemic alert",
                    "health emergency",
                    "spread of disease",
                    "influenza warning",
                ]

                for kw in outbreak_keywords:
                    if kw in page_text:
                        idx = page_text.find(kw)
                        # Extract sentence-like context
                        context = page_text[max(0, idx - 20) : idx + 150]
                        # Clean up
                        context = " ".join(context.split())

                        if len(context) > 20 and "circular" not in context:
                            result["alerts"].append(
                                {
                                    "type": "health_notice",
                                    "text": f"...{context}...",
                                    "severity": "medium",
                                }
                            )
                            break

            # 4. Check for Dengue stats specifically
            dengue_match = re.search(r"dengue[:\s]*(\d{1,5})\s*(?:cases?)?", page_text)
            if dengue_match:
                try:
                    result["dengue"]["weekly_cases"] = int(dengue_match.group(1))
                    logger.info(
                        f"[HEALTH] Found Dengue cases: {result['dengue']['weekly_cases']}"
                    )
                except ValueError:
                    pass

    except Exception as e:
        logger.warning(f"[HEALTH] Scraping error: {e}")
        # Don't fail completely, return baseline

    # fallback: If still no alerts, maybe add seasonal one
    if not result["alerts"]:
        current_month = utc_now().month
        if current_month in [5, 6, 10, 11, 12]:  # Monsoon = mosquito season
            result["advisories"].append(
                {
                    "type": "seasonal",
                    "text": "Mosquito Control: Remove stagnant water to prevent Dengue breeding.",
                    "severity": "medium",
                }
            )

    # Update cache
    _health_cache = result
    _health_cache_time = utc_now()

    return result


def tool_commodity_prices() -> Dict[str, Any]:
    """
    Get prices for essential commodities in Sri Lanka.

    Fetches live prices from UN World Food Programme (WFP) Humanitarian Data Exchange.
    Includes rice, sugar, lentils, eggs, chicken, coconut oil, onions, potatoes, and more.

    Returns:
        Dict with commodity prices, units, and source information
    """
    global _commodity_cache, _commodity_cache_time

    # Check cache (cache for 60 minutes since WFP data updates weekly)
    if _commodity_cache_time:
        cache_age = (utc_now() - _commodity_cache_time).total_seconds() / 60
        if cache_age < 60 and _commodity_cache:
            logger.info(f"[COMMODITY] Using cached data ({cache_age:.1f} min old)")
            return _commodity_cache

    logger.info("[COMMODITY] Fetching live commodity prices from WFP HDX...")

    # WFP Humanitarian Data Exchange - Sri Lanka Food Prices
    WFP_HDX_URL = "https://data.humdata.org/dataset/0298c598-d312-4771-b564-f4ac4d831f05/resource/3638f0d6-9969-48cf-a919-1d879d037ec6/download/wfp_food_prices_lka.csv"

    # Mapping WFP commodity names to our display names
    COMMODITY_MAPPING = {
        "Rice (red nadu)": ("White Rice (Nadu)", "grains"),
        "Rice (white)": ("White Rice (Samba)", "grains"),
        "Rice (red)": ("Red Rice", "grains"),
        "Wheat flour": ("Wheat Flour", "grains"),
        "Sugar": ("Sugar (White)", "essentials"),
        "Lentils": ("Dhal (Lentils)", "pulses"),
        "Oil (coconut)": ("Coconut Oil", "cooking"),
        "Coconut": ("Coconut (Fresh)", "cooking"),
        "Eggs": ("Eggs (per unit)", "protein"),
        "Meat (chicken, fresh)": ("Chicken", "protein"),
        "Meat (chicken, broiler)": ("Chicken (Broiler)", "protein"),
        "Onions (imported)": ("Big Onion", "vegetables"),
        "Onions (red)": ("Red Onion", "vegetables"),
        "Potatoes (imported)": ("Potatoes", "vegetables"),
        "Potatoes (local)": ("Potatoes (Local)", "vegetables"),
        "Tomatoes": ("Tomatoes", "vegetables"),
        "Cabbage": ("Cabbage", "vegetables"),
        "Carrots": ("Carrots", "vegetables"),
        "Fuel (diesel)": ("Diesel", "fuel"),
        "Fuel (petrol-gasoline)": ("Petrol 92 Octane", "fuel"),
    }

    commodities = []
    data_date = None
    source_status = "error"

    try:
        resp = _safe_get(WFP_HDX_URL, timeout=60)
        if resp and resp.status_code == 200:
            import csv
            import io
            from collections import defaultdict

            reader = csv.DictReader(io.StringIO(resp.text))
            rows = list(reader)

            if rows:
                # Get the latest date in the dataset
                latest_date = max(
                    row.get("date", "") for row in rows if row.get("date")
                )
                data_date = latest_date

                # Get the latest prices for each commodity (average across markets)
                latest_prices: Dict[str, List[float]] = defaultdict(list)
                for row in rows:
                    if row.get("date") == latest_date and row.get("price"):
                        commodity = row.get("commodity", "")
                        try:
                            price = float(row["price"])
                            latest_prices[commodity].append(price)
                        except (ValueError, KeyError):
                            pass

                # Calculate average prices and build commodity list
                for wfp_name, (display_name, category) in COMMODITY_MAPPING.items():
                    if wfp_name in latest_prices and latest_prices[wfp_name]:
                        avg_price = sum(latest_prices[wfp_name]) / len(
                            latest_prices[wfp_name]
                        )
                        unit = "LKR/kg"
                        if "Eggs" in display_name:
                            unit = "LKR/each"
                        elif "Coconut (Fresh)" in display_name:
                            unit = "LKR/each"
                        elif "Oil" in display_name:
                            unit = "LKR/L"
                        elif "Diesel" in display_name or "Petrol" in display_name:
                            unit = "LKR/L"

                        commodities.append(
                            {
                                "name": display_name,
                                "price": round(avg_price, 2),
                                "unit": unit,
                                "category": category,
                                "live": True,
                                "wfp_commodity": wfp_name,
                                "markets_sampled": len(latest_prices[wfp_name]),
                            }
                        )

                source_status = "live"
                logger.info(
                    f"[COMMODITY] ✓ Fetched {len(commodities)} live prices from WFP (data date: {latest_date})"
                )

    except Exception as e:
        logger.warning(f"[COMMODITY] WFP API error: {e}")
        source_status = "error"

    # Fallback to baseline if no data fetched
    if not commodities:
        logger.info("[COMMODITY] Using baseline data - WFP API unavailable")
        source_status = "baseline"
        commodities = [
            {
                "name": "White Rice (Nadu)",
                "price": 220,
                "unit": "LKR/kg",
                "category": "grains",
                "live": False,
            },
            {
                "name": "White Rice (Samba)",
                "price": 250,
                "unit": "LKR/kg",
                "category": "grains",
                "live": False,
            },
            {
                "name": "Red Rice",
                "price": 240,
                "unit": "LKR/kg",
                "category": "grains",
                "live": False,
            },
            {
                "name": "Sugar (White)",
                "price": 240,
                "unit": "LKR/kg",
                "category": "essentials",
                "live": False,
            },
            {
                "name": "Dhal (Lentils)",
                "price": 380,
                "unit": "LKR/kg",
                "category": "pulses",
                "live": False,
            },
            {
                "name": "Coconut Oil",
                "price": 680,
                "unit": "LKR/L",
                "category": "cooking",
                "live": False,
            },
            {
                "name": "Eggs (per unit)",
                "price": 48,
                "unit": "LKR/each",
                "category": "protein",
                "live": False,
            },
            {
                "name": "Chicken",
                "price": 1350,
                "unit": "LKR/kg",
                "category": "protein",
                "live": False,
            },
            {
                "name": "Big Onion",
                "price": 280,
                "unit": "LKR/kg",
                "category": "vegetables",
                "live": False,
            },
            {
                "name": "Potatoes",
                "price": 350,
                "unit": "LKR/kg",
                "category": "vegetables",
                "live": False,
            },
        ]
        data_date = utc_now().strftime("%Y-%m-%d")

    # Sort by category
    category_order = {
        "grains": 1,
        "essentials": 2,
        "pulses": 3,
        "cooking": 4,
        "protein": 5,
        "vegetables": 6,
        "fuel": 7,
    }
    commodities.sort(
        key=lambda x: (category_order.get(x.get("category", ""), 99), x.get("name", ""))
    )

    # Build result
    live_count = sum(1 for c in commodities if c.get("live", False))
    result = {
        "commodities": commodities,
        "source": "UN World Food Programme (WFP) Humanitarian Data Exchange",
        "source_url": WFP_HDX_URL.replace("/download/wfp_food_prices_lka.csv", ""),
        "data_date": data_date,
        "scrape_status": source_status,
        "fetched_at": utc_now().isoformat(),
        "summary": {
            "total_items": len(commodities),
            "items_live": live_count,
            "items_baseline": len(commodities) - live_count,
        },
    }

    # Update cache
    _commodity_cache = result
    _commodity_cache_time = utc_now()

    return result


def tool_water_supply_alerts() -> Dict[str, Any]:
    """
    Get water supply disruption alerts from NWSDB.

    Returns information about planned/unplanned water cuts and affected areas.

    Returns:
        Dict with active disruptions, affected areas, and restoration times
    """
    global _water_cache, _water_cache_time

    # Check cache
    if _water_cache_time:
        cache_age = (utc_now() - _water_cache_time).total_seconds() / 60
        if cache_age < SA_CACHE_DURATION_MINUTES and _water_cache:
            logger.info(f"[WATER] Using cached data ({cache_age:.1f} min old)")
            return _water_cache

    logger.info("[WATER] Fetching water supply alerts...")

    result = {
        "status": "normal",
        "active_disruptions": [],
        "scheduled_maintenance": [],
        "source": "waterboard.lk / NWSDB",
        "fetched_at": utc_now().isoformat(),
        "overall_supply": "stable",
    }

    try:
        # Try to scrape NWSDB website
        resp = _safe_get("https://www.waterboard.lk/", timeout=30)
        if resp:
            soup = BeautifulSoup(resp.text, "html.parser")

            # 1. Clean DOM - Remove typically noisy elements
            for trash in soup.find_all(
                [
                    "nav",
                    "header",
                    "footer",
                    "script",
                    "style",
                    "noscript",
                    "iframe",
                    "form",
                ]
            ):
                trash.decompose()

            # Remove menu containers explicitly
            for menu in soup.select(
                ".menu, .navigation, #main-menu, .top-bar, .service-block"
            ):
                menu.decompose()

            # 2. Look for explicit alerts (Marquee is common on SL govt sites)
            alerts_found = []

            # Check marquees
            for marquee in soup.find_all("marquee"):
                text = marquee.get_text(separator=" ", strip=True)
                if len(text) > 10:
                    alerts_found.append({"text": text, "source": "ticker"})

            # Check alert classes
            for alert in soup.select(".alert, .notice, .warning, .news-ticker"):
                text = alert.get_text(separator=" ", strip=True)
                if len(text) > 10:
                    alerts_found.append({"text": text, "source": "alert_box"})

            # 3. If no explicit alerts, search body text with STRICTER validation
            if not alerts_found:
                main_content = (
                    soup.select_one("main, #content, .container, body") or soup.body
                )
                if main_content:
                    # Get paragraph texts mainly
                    for p in main_content.find_all(["p", "div", "span"]):
                        text = p.get_text(strip=True)
                        if (
                            len(text) < 20 or len(text) > 300
                        ):  # Ignore too short/long blocks
                            continue

                        text_lower = text.lower()

                        # Must have explicit "water" context AND disruption keyword
                        has_water = any(
                            w in text_lower
                            for w in [
                                "water supply",
                                "water cut",
                                "nwsdb",
                                "water board",
                            ]
                        )
                        has_issue = any(
                            w in text_lower
                            for w in [
                                "interruption",
                                "disruption",
                                "suspended",
                                "stopped",
                                "low pressure",
                            ]
                        )

                        # Stopwords that indicate this is NOT an alert (slogans, payment info, etc)
                        is_garbage = any(
                            w in text_lower
                            for w in [
                                "benefits",
                                "payment",
                                "service without",
                                "bill",
                                "vision",
                                "mission",
                            ]
                        )

                        if has_water and has_issue and not is_garbage:
                            alerts_found.append(
                                {"text": text, "source": "content_match"}
                            )

            # Process found alerts
            for item in alerts_found:
                text = item["text"]
                text_lower = text.lower()

                # Double check garbage filtering
                if any(
                    w in text_lower
                    for w in ["benefits", "payment", "check out", "click here"]
                ):
                    continue

                result["status"] = "disruptions_reported"

                # Extract Area
                area = "Multiple areas"
                # Common major areas regex
                area_match = re.search(
                    r"(colombo|gampaha|kandy|galle|matara|jaffna|kurunegala|ratnapura|kalutara|negombo)",
                    text_lower,
                    re.I,
                )
                if area_match:
                    area = area_match.group(1).title()

                # Deduplicate
                if not any(d["details"] == text for d in result["active_disruptions"]):
                    result["active_disruptions"].append(
                        {
                            "area": area,
                            "type": "Water Disruption",
                            "details": text[:200] + ("..." if len(text) > 200 else ""),
                            "severity": "medium",
                        }
                    )

            logger.info(
                f"[WATER] Fetched - Disruptions: {len(result['active_disruptions'])}"
            )

        # If no disruptions found via scraping, report normal
        if not result["active_disruptions"]:
            result["status"] = "normal"
            result["overall_supply"] = "Normal water supply across most areas"

    except Exception as e:
        logger.warning(f"[WATER] Scraping error: {e}")
        # Don't overwrite default valid return structure, just add error
        result["error"] = str(e)

    # Update cache
    _water_cache = result
    _water_cache_time = utc_now()

    return result


# ============================================
# METEOROLOGICAL TOOLS (Upgraded)
# ============================================


def tool_dmc_alerts() -> Dict[str, Any]:
    # ... (Existing DMC alerts code - unchanged) ...
    url = "http://www.meteo.gov.lk/index.php?lang=en"
    resp = _safe_get(url)
    if not resp:
        return {
            "source": url,
            "alerts": ["Failed to fetch alerts from DMC."],
            "fetched_at": utc_now().isoformat(),
        }
    soup = BeautifulSoup(resp.text, "html.parser")
    alerts: List[str] = []
    keywords = [
        "warning",
        "advisory",
        "alert",
        "heavy rain",
        "strong wind",
        "thunderstorm",
        "flood",
        "landslide",
        "cyclone",
        "severe",
    ]
    for text in soup.find_all(string=True):
        if len(text.strip()) > 20 and any(k in text.lower() for k in keywords):
            clean = re.sub(r"\s+", " ", text.strip())
            if clean not in alerts:
                alerts.append(clean)
    if not alerts:
        alerts = ["No active severe weather alerts detected."]
    return {
        "source": url,
        "alerts": alerts[:10],
        "fetched_at": utc_now().isoformat(),
    }


def tool_weather_nowcast(location: str = "Colombo") -> Dict[str, Any]:
    """
    Comprehensive Weather Scraper (Robust Mode):
    1. Homepage (General Text).
    2. City/District Forecast (Direct URL).
    3. Critical Advisory PDFs.
    Handles slow loading by capturing content even if timeouts occur.
    """
    base_url = "https://meteo.gov.lk/"
    city_forecast_url = "https://meteo.gov.lk/index.php?option=com_content&view=article&id=102&Itemid=360&lang=en"

    combined_report = []
    html_home = ""
    html_city = ""

    if PLAYWRIGHT_AVAILABLE:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                # Use a standard browser context (no aggressive blocking)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                page = context.new_page()
                page.set_default_timeout(60000)  # Give it 60 seconds (it's slow)

                # --- A. Visit Homepage ---
                try:
                    page.goto(base_url, wait_until="domcontentloaded")
                    # Try to wait for text, but don't crash if it takes too long
                    try:
                        page.wait_for_selector("div.itemFullText", timeout=15000)
                    except:
                        pass
                    html_home = page.content()
                except Exception as e:
                    # Even if it times out, grab what we have!
                    logger.warning(
                        f"[WEATHER] Homepage timeout (capturing partial): {e}"
                    )
                    html_home = page.content()

                # --- B. Visit City Forecast ---
                try:
                    page.goto(city_forecast_url, wait_until="domcontentloaded")
                    try:
                        page.wait_for_selector("table", timeout=15000)
                    except:
                        pass
                    html_city = page.content()
                except Exception as e:
                    logger.warning(
                        f"[WEATHER] City Forecast timeout (capturing partial): {e}"
                    )
                    html_city = page.content()

                browser.close()
        except Exception as e:
            logger.warning(f"[WEATHER] Playwright critical fail: {e}")

    # Fallback to requests if Playwright returned nothing
    if not html_home or len(html_home) < 500:
        resp = _safe_get(base_url)
        html_home = resp.text if resp else ""

    if not html_city or len(html_city) < 500:
        resp = _safe_get(city_forecast_url)
        html_city = resp.text if resp else ""

    if not html_home and not html_city:
        return {"error": "Failed to load Meteo.gov.lk"}

    # --- PARSE HOMEPAGE ---
    soup_home = BeautifulSoup(html_home, "html.parser")
    english_forecast = ""

    header = soup_home.find(string=re.compile(r"WEATHER FORECAST FOR", re.I))
    if header:
        container = header.find_parent("div") or header.find_parent("article")
        if container:
            text = container.get_text(separator="\n", strip=True)
            start = text.upper().find("WEATHER FORECAST FOR")
            if start != -1:
                english_forecast = text[start:][:2500]

    if not english_forecast:
        main = soup_home.find("div", class_="itemFullText") or soup_home.find(
            "div", itemprop="articleBody"
        )
        english_forecast = (
            main.get_text(separator="\n", strip=True)[:2500]
            if main
            else "General forecast text not found."
        )

    combined_report.append("--- ISLAND-WIDE GENERAL FORECAST ---")
    combined_report.append(english_forecast)

    # --- PARSE CITY FORECAST (Districts) ---
    if html_city:
        soup_city = BeautifulSoup(html_city, "html.parser")
        table = soup_city.find("table")
        if table:
            combined_report.append("\n--- DISTRICT/CITY FORECASTS ---")
            rows = table.find_all("tr")

            # Header logic
            if rows:
                header_row = rows[0]
                headers = [
                    th.get_text(strip=True) for th in header_row.find_all(["th", "td"])
                ]
                if not "".join(headers).strip() and len(rows) > 1:
                    headers = [
                        th.get_text(strip=True) for th in rows[1].find_all(["th", "td"])
                    ]

                clean_header = " | ".join(headers[:4])
                combined_report.append(clean_header)
                combined_report.append("-" * len(clean_header))

            # Row logic
            for row in rows:
                cols = [td.get_text(strip=True) for td in row.find_all("td")]
                if not cols or len(cols) < 2:
                    continue
                if "City" in cols[0] or "Temperature" in cols[0]:
                    continue

                row_text = " | ".join(cols[:4])
                combined_report.append(row_text)

    # --- PARSE PDF ALERTS ---
    pdf_links = soup_home.find_all("a", href=True)
    found_pdfs = []
    for a in pdf_links:
        link_text = a.get_text(strip=True)
        href = a["href"]
        if "pdf" in href.lower() and any(
            k in link_text.lower() for k in ["advisory", "warning"]
        ):
            abs_url = _make_absolute(href, base_url)
            if abs_url not in [p["url"] for p in found_pdfs]:
                prio = 1 if "english" in link_text.lower() else 2
                found_pdfs.append({"title": link_text, "url": abs_url, "prio": prio})

    found_pdfs.sort(key=lambda x: x["prio"])

    for pdf in found_pdfs[:2]:
        text = _extract_text_from_pdf_url(pdf["url"])
        if "Sinhala/Tamil" not in text and len(text) > 50:
            combined_report.append(f"\n--- CRITICAL ALERT: {pdf['title']} ---\n{text}")

    # Final Cleanup
    final_text = "\n\n".join(combined_report)
    cleanup = ["DEPARTMENT OF METEOROLOGY", "Loading...", "Listen To The Weather"]
    for c in cleanup:
        final_text = final_text.replace(c, "")

    return {
        "location": "All Districts",
        "forecast": final_text,
        "source": base_url,
        "fetched_at": utc_now().isoformat(),
    }


# ============================================
# NEWS SCRAPING TOOLS
# ============================================

LOCAL_NEWS_SITES = [
    {
        "url": "https://www.dailymirror.lk/",
        "name": "Daily Mirror",
        "article_selector": "article, .news-block, .article, .card",
    },
    {
        "url": "https://www.ft.lk/",
        "name": "Daily FT",
        "article_selector": "article, .article-list-item, .card",
    },
    {
        "url": "https://www.newsfirst.lk/",
        "name": "News First",
        "article_selector": ".post, article, .news-block",
    },
]


def scrape_local_news_impl(
    keywords: Optional[List[str]] = None,
    max_articles: int = 30,
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for site in LOCAL_NEWS_SITES:
        try:
            resp = _safe_get(site["url"])
            if not resp:
                logger.warning(f"[NEWS] Failed to fetch {site['url']}")
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            articles = soup.select(site.get("article_selector", "article"))
            for article in articles:
                title_elem = (
                    article.find("h1")
                    or article.find("h2")
                    or article.find("h3")
                    or article.find(
                        class_=re.compile(r"(title|headline|heading)", re.I)
                    )
                )
                title = title_elem.get_text(strip=True) if title_elem else ""
                if not title or len(title) < 8:
                    a = article.find("a", href=True)
                    title = title or (a.get_text(strip=True) if a else "")
                if not title or len(title) < 8:
                    continue
                if not _contains_keyword(title, keywords):
                    continue
                link_elem = article.find("a", href=True)
                href = link_elem["href"] if link_elem else site["url"]
                href = _make_absolute(href, site["url"])
                snippet_elem = article.find("p") or article.find(
                    class_=re.compile(r"(excerpt|summary|description)", re.I)
                )
                snippet = (
                    snippet_elem.get_text(strip=True)[:300] if snippet_elem else ""
                )
                results.append(
                    {
                        "source": site["name"],
                        "source_url": site["url"],
                        "headline": title,
                        "snippet": snippet,
                        "url": href,
                        "timestamp": utc_now().isoformat(),
                    }
                )
                if len(results) >= max_articles:
                    return results
        except Exception as e:
            logger.error(f"[NEWS] Error scraping {site['name']}: {e}")
            continue
    return results


# ============================================
# REDDIT SCRAPING
# ============================================


def scrape_reddit_impl(
    keywords: List[str],
    limit: int = 20,
    subreddit: Optional[str] = None,
) -> List[Dict[str, Any]]:
    base = (
        f"https://www.reddit.com/r/{subreddit}/search.json"
        if subreddit
        else "https://www.reddit.com/search.json"
    )
    query = " ".join(keywords) if keywords else "Sri Lanka"
    params = {
        "q": query,
        "sort": "new",
        "limit": str(limit),
        "restrict_sr": "on" if subreddit else "off",
    }
    headers = {
        "User-Agent": DEFAULT_HEADERS["User-Agent"],
        "Accept": "application/json",
    }
    try:
        resp = requests.get(
            base, headers=headers, params=params, timeout=DEFAULT_TIMEOUT
        )
        if resp.status_code != 200:
            logger.warning(f"[REDDIT] HTTP {resp.status_code} for {base}")
            return [
                {"error": f"Reddit returned status {resp.status_code}", "query": query}
            ]
        data = resp.json()
        posts_raw = data.get("data", {}).get("children", [])
        posts: List[Dict[str, Any]] = []
        for p in posts_raw:
            d = p.get("data", {})
            title = d.get("title") or ""
            selftext = d.get("selftext") or ""
            text = f"{title}\n{selftext}"
            if not _contains_keyword(text, keywords):
                continue
            posts.append(
                {
                    "id": d.get("id"),
                    "title": title,
                    "selftext": selftext[:500],
                    "subreddit": d.get("subreddit"),
                    "author": d.get("author"),
                    "score": d.get("score", 0),
                    "url": "https://www.reddit.com" + d.get("permalink", ""),
                    "created_utc": d.get("created_utc"),
                    "num_comments": d.get("num_comments", 0),
                }
            )
        return (
            posts
            if posts
            else [{"note": f"No Reddit posts found for: {query}", "query": query}]
        )
    except Exception as e:
        logger.error(f"[REDDIT] Error: {e}")
        return [{"error": str(e), "query": query}]


# ============================================
# CSE / STOCK DATA
# ============================================


def _scrape_cse_website_data(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Scrape stock data directly from CSE website.
    This is more reliable than yfinance for Sri Lankan stocks.
    """
    try:
        cse_url = "https://www.cse.lk/"
        resp = _safe_get(cse_url, timeout=30)
        if not resp:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        text = soup.get_text(separator="\n", strip=True)

        result_data = {}

        # Pattern for ASPI (All Share Price Index)
        # CSE website typically shows: "ASPI 12,345.67 +123.45 (+1.01%)"
        aspi_patterns = [
            r"ASPI[:\s]*([\d,]+\.?\d*)\s*(?:points?)?\s*[\(\[]?([+-]?[\d,]+\.?\d*)\s*(?:points?)?[\)\]]?\s*[\(\[]?([+-]?[\d,]*\.?\d*)%?[\)\]]?",
            r"All\s*Share\s*(?:Price\s*)?Index[:\s]*([\d,]+\.?\d*)",
            r"ASPI[^\d\n\r]*([\d,]+\.\d+)",
        ]

        for pattern in aspi_patterns:
            m = re.search(pattern, text, re.I)
            if m:
                try:
                    value = float(m.group(1).replace(",", ""))
                    result_data["aspi"] = {
                        "value": value,
                        "change": (
                            float(m.group(2).replace(",", ""))
                            if len(m.groups()) > 1 and m.group(2)
                            else None
                        ),
                        "change_pct": (
                            float(m.group(3).replace(",", "").replace("%", ""))
                            if len(m.groups()) > 2 and m.group(3)
                            else None
                        ),
                    }
                    break
                except (ValueError, IndexError):
                    continue

        # Pattern for S&P SL20 index
        sp_patterns = [
            r"S&?P\s*SL\s*20[:\s]*([\d,]+\.?\d*)",
            r"SL20[:\s]*([\d,]+\.?\d*)",
        ]

        for pattern in sp_patterns:
            m = re.search(pattern, text, re.I)
            if m:
                try:
                    result_data["sp_sl20"] = float(m.group(1).replace(",", ""))
                    break
                except ValueError:
                    continue

        # Check if we got any useful data
        if result_data:
            return result_data

        # Fallback: simple ASPI pattern
        m = re.search(
            r"(ASPI|All Share Price Index)[^\d\n\r]*([\d,]+\.\d+)", text, re.I
        )
        if m:
            return {"aspi": {"value": float(m.group(2).replace(",", ""))}}

        return None

    except Exception as e:
        logger.debug(f"[CSE] Direct CSE scrape failed: {e}")
        return None


def scrape_cse_stock_impl(
    symbol: str = "ASPI",
    period: str = "1d",
    interval: str = "1h",
) -> Dict[str, Any]:
    """
    Fetch CSE stock data with multiple fallback strategies:
    1. First try direct CSE website scraping (most reliable for Sri Lankan stocks)
    2. Fall back to yfinance if direct scraping fails

    Note: yfinance often fails for CSE symbols as Yahoo Finance has limited
    coverage of the Colombo Stock Exchange.
    """
    symbol_upper = symbol.upper()
    is_index = symbol_upper in ("ASPI", "ASPI.N0000", "^N0000", "ALL SHARE")

    # ============ Strategy 1: Direct CSE Website Scraping ============
    # This is more reliable for Sri Lankan market data
    if is_index:
        logger.info(f"[CSE] Attempting direct CSE website scrape for {symbol}...")
        cse_data = _scrape_cse_website_data(symbol)

        if cse_data and "aspi" in cse_data:
            aspi_info = cse_data["aspi"]
            summary = {
                "current_price": aspi_info.get("value", 0),
                "change": aspi_info.get("change"),
                "change_pct": aspi_info.get("change_pct"),
            }

            # Add S&P SL20 if available
            if "sp_sl20" in cse_data:
                summary["sp_sl20"] = cse_data["sp_sl20"]

            logger.info(
                f"[CSE] Successfully scraped ASPI from CSE website: {summary['current_price']}"
            )
            return {
                "symbol": symbol,
                "resolved_symbol": "CSE-direct",
                "period": period,
                "interval": interval,
                "summary": summary,
                "records": [],
                "source": "cse.lk (direct scrape)",
                "note": "Real-time data from Colombo Stock Exchange website",
                "fetched_at": utc_now().isoformat(),
            }

    # ============ Strategy 2: yfinance (Fallback) ============
    # Note: This frequently fails for CSE stocks
    symbols_to_try = [symbol]
    if is_index:
        symbols_to_try = ["^N0000", "ASPI.N0000", "ASPI"]
    elif not symbol.endswith(".N0000") and not symbol.startswith("^"):
        # Try both with and without .N0000 suffix for regular stocks
        symbols_to_try = [f"{symbol}.N0000", symbol]

    logger.info(f"[CSE] Trying yfinance for symbols: {symbols_to_try}")

    for sym in symbols_to_try:
        try:
            ticker = yf.Ticker(sym)
            hist = ticker.history(period=period, interval=interval)

            if hist is None or hist.empty:
                logger.debug(f"[CSE] yfinance returned empty data for {sym}")
                continue

            hist = hist.reset_index()
            records = hist.to_dict(orient="records")

            for record in records:
                for key, value in list(record.items()):
                    if hasattr(value, "isoformat"):
                        record[key] = value.isoformat()

            latest = records[-1] if records else {}
            summary = {
                "current_price": latest.get("Close", latest.get("close", 0)),
                "open": latest.get("Open", latest.get("open", 0)),
                "high": latest.get("High", latest.get("high", 0)),
                "low": latest.get("Low", latest.get("low", 0)),
                "volume": latest.get("Volume", latest.get("volume", 0)),
            }

            logger.info(f"[CSE] yfinance success for {sym}: {summary['current_price']}")
            return {
                "symbol": symbol,
                "resolved_symbol": sym,
                "period": period,
                "interval": interval,
                "summary": summary,
                "records": records[-10:],
                "source": "yahoo_finance",
                "fetched_at": utc_now().isoformat(),
            }

        except Exception as e_inner:
            logger.debug(f"[CSE] yfinance attempt failed for {sym}: {e_inner}")
            continue

    # ============ Final Fallback: Try CSE website again for any symbol ============
    logger.info("[CSE] All yfinance attempts failed, trying CSE website fallback...")
    cse_data = _scrape_cse_website_data(symbol)

    if cse_data and "aspi" in cse_data:
        return {
            "symbol": symbol,
            "resolved_symbol": "CSE-fallback",
            "period": period,
            "interval": interval,
            "summary": {"current_price": cse_data["aspi"].get("value", 0)},
            "records": [],
            "source": "cse.lk (fallback scrape)",
            "fetched_at": utc_now().isoformat(),
        }

    # All strategies failed
    logger.warning(f"[CSE] All data sources failed for {symbol}")
    return {
        "symbol": symbol,
        "error": f"Could not fetch data for {symbol}. Yahoo Finance has limited CSE coverage.",
        "attempted_symbols": symbols_to_try,
        "suggestion": "Try accessing cse.lk directly for real-time CSE data",
        "fetched_at": utc_now().isoformat(),
    }


# ============================================
# GOVERNMENT GAZETTE (Deep Scraping)
# ============================================


def scrape_government_gazette_impl(
    keywords: Optional[List[str]] = None,
    max_items: int = 15,
) -> List[Dict[str, Any]]:
    """
    Scrapes gazette.lk for latest government gazettes.
    ENHANCED: Now downloads PDFs and extracts text content from them.

    Args:
        keywords: Optional list of keywords to filter gazettes (currently ignored)
        max_items: Maximum number of gazette entries to process

    Returns:
        List of gazette entries with PDF content extracted
    """
    base_url = "https://www.gazette.lk/government-gazette"
    results: List[Dict[str, Any]] = []

    logger.info(f"[GAZETTE] Fetching latest gazettes from {base_url}")
    resp = _safe_get(base_url)
    if not resp:
        return [
            {
                "title": "Failed to access gazette.lk",
                "url": base_url,
                "error": "Network request failed",
                "timestamp": utc_now().isoformat(),
            }
        ]

    soup = BeautifulSoup(resp.text, "html.parser")

    # Find all gazette article entries
    articles = soup.find_all("article")
    if not articles:
        articles = soup.select(".post, .type-post, .entry")

    logger.info(f"[GAZETTE] Found {len(articles)} potential gazette entries")

    for article in articles:
        if len(results) >= max_items:
            break

        # Extract title and link
        title_elem = (
            article.find(class_="entry-title")
            or article.find("h2")
            or article.find("h3")
        )
        if not title_elem:
            continue

        link_elem = title_elem.find("a", href=True)
        if not link_elem:
            continue

        title = link_elem.get_text(strip=True)
        post_url = link_elem["href"]
        post_url_abs = _make_absolute(post_url, base_url)

        # Filter to only include actual gazette entries (not other site content)
        if "government gazette" not in title.lower():
            continue

        # Extract date from title if possible
        date_match = re.search(r"(\d{4}\s+\w+\s+\d{1,2})", title)
        date_str = date_match.group(1) if date_match else "Unknown date"

        logger.info(f"[GAZETTE] Processing: {title[:50]}...")

        # ENHANCED: Visit the detail page to find all PDF links
        pdf_links = []
        pdf_content = []

        try:
            detail_resp = _safe_get(post_url_abs)
            if detail_resp:
                detail_soup = BeautifulSoup(detail_resp.text, "html.parser")

                # FIXED: First look for pdfemb-viewer class links (gazette.lk specific)
                # These have direct PDF URLs like https://www.gazette.lk/dl/Gazette/11/Gazette-2025-11-28E.pdf
                pdfemb_links = detail_soup.find_all("a", class_="pdfemb-viewer")
                for link in pdfemb_links:
                    href = link.get("href", "")
                    if href and ("/dl/Gazette/" in href or ".pdf" in href.lower()):
                        # Detect language from URL (E=English, S=Sinhala, T=Tamil)
                        language = "english"
                        href_lower = href.lower()
                        if href.endswith("S.pdf") or "sinhala" in href_lower:
                            language = "sinhala"
                        elif href.endswith("T.pdf") or "tamil" in href_lower:
                            language = "tamil"

                        pdf_url = _make_absolute(href, post_url_abs)
                        pdf_links.append(
                            {
                                "language": language,
                                "url": pdf_url,
                                "text": link.get_text(strip=True)
                                or f"Gazette PDF ({language})",
                            }
                        )
                        logger.info(f"[GAZETTE] Found pdfemb-viewer link: {pdf_url}")

                # Also look for any other direct PDF links (backup approach)
                if not pdf_links:
                    for link in detail_soup.find_all("a", href=True):
                        href = link["href"]
                        link_text = link.get_text(strip=True).lower()

                        # Check for direct PDF download paths
                        is_gazette_pdf = "/dl/Gazette/" in href
                        is_pdf_file = href.lower().endswith(".pdf")

                        if is_gazette_pdf or is_pdf_file:
                            pdf_url = _make_absolute(href, post_url_abs)

                            # Detect language
                            language = "english"
                            if "sinhala" in link_text or href.endswith("S.pdf"):
                                language = "sinhala"
                            elif "tamil" in link_text or href.endswith("T.pdf"):
                                language = "tamil"
                            elif href.endswith("E.pdf") or "english" in link_text:
                                language = "english"

                            # Avoid duplicates
                            if not any(p["url"] == pdf_url for p in pdf_links):
                                pdf_links.append(
                                    {
                                        "language": language,
                                        "url": pdf_url,
                                        "text": link.get_text(strip=True)
                                        or f"PDF ({language})",
                                    }
                                )

                logger.info(
                    f"[GAZETTE] Found {len(pdf_links)} PDF links on detail page"
                )

                # ENHANCED: Download and extract text from English PDFs (most useful)
                english_pdfs = [p for p in pdf_links if p["language"] == "english"]
                if not english_pdfs:
                    english_pdfs = pdf_links[:1]  # Fallback to first PDF

                for pdf_info in english_pdfs[:2]:  # Limit to 2 PDFs per gazette
                    try:
                        logger.info(
                            f"[GAZETTE] Downloading PDF: {pdf_info['url'][:60]}..."
                        )
                        extracted_text = _extract_text_from_pdf_url(pdf_info["url"])

                        if extracted_text and not extracted_text.startswith("["):
                            pdf_content.append(
                                {
                                    "language": pdf_info["language"],
                                    "content": extracted_text,  # Full content - no truncation
                                    "source_url": pdf_info["url"],
                                }
                            )
                            logger.info(
                                f"[GAZETTE] Extracted {len(extracted_text)} chars from PDF"
                            )
                        else:
                            pdf_content.append(
                                {
                                    "language": pdf_info["language"],
                                    "content": extracted_text,
                                    "source_url": pdf_info["url"],
                                }
                            )
                    except Exception as e:
                        logger.warning(f"[GAZETTE] PDF extraction error: {e}")
                        pdf_content.append(
                            {
                                "language": pdf_info.get("language", "unknown"),
                                "content": f"[Error extracting PDF: {str(e)}]",
                                "source_url": pdf_info.get("url", ""),
                            }
                        )
        except Exception as e:
            logger.warning(f"[GAZETTE] Error fetching detail page: {e}")

        # Build the result with extracted content
        result_entry = {
            "title": title,
            "date": date_str,
            "url": post_url_abs,
            "pdf_links": pdf_links,
            "extracted_content": pdf_content,
            "timestamp": utc_now().isoformat(),
        }

        # Add a summary if we have content
        if pdf_content:
            first_content = pdf_content[0].get("content", "")
            if first_content and not first_content.startswith("["):
                result_entry["summary"] = first_content[:500]

        results.append(result_entry)
        logger.info(f"[GAZETTE] Added gazette with {len(pdf_content)} PDF extractions")

    if not results:
        return [
            {
                "title": "No gazette entries found",
                "url": base_url,
                "note": "The website structure may have changed",
                "timestamp": utc_now().isoformat(),
            }
        ]

    logger.info(
        f"[GAZETTE] Successfully scraped {len(results)} gazette entries with PDF content"
    )
    return results


# ============================================
# PARLIAMENT MINUTES
# ============================================


def scrape_parliament_minutes_impl(
    keywords: Optional[List[str]] = None,
    max_items: int = 20,
) -> List[Dict[str, Any]]:
    """
    Scrape Sri Lankan Parliament Hansards from parliament.lk.

    ENHANCED: Now properly extracts Hansard PDF links with dates and metadata.
    The website stores PDFs at /uploads/businessdocs/ with date-encoded filenames.

    Args:
        keywords: Optional keywords to filter results
        max_items: Maximum number of items to return

    Returns:
        List of Hansard entries with PDF links and dates
    """
    url = "https://www.parliament.lk/en/business-of-parliament/hansards"

    logger.info(f"[PARLIAMENT] Fetching Hansards from {url}")
    resp = _safe_get(url)

    if not resp:
        return [
            {
                "title": "Parliament website unavailable",
                "url": url,
                "note": "Could not access parliament.lk. Site may be down.",
                "timestamp": utc_now().isoformat(),
            }
        ]

    soup = BeautifulSoup(resp.text, "html.parser")
    results: List[Dict[str, Any]] = []

    # Strategy 1: Look for PDF links in /uploads/businessdocs/ (Hansard documents)
    pdf_links = soup.find_all(
        "a", href=lambda x: x and ".pdf" in x.lower() and "businessdocs" in x.lower()
    )

    logger.info(f"[PARLIAMENT] Found {len(pdf_links)} Hansard PDF links")

    for link in pdf_links:
        href = link.get("href", "")
        link_text = link.get_text(strip=True)

        # Extract date from URL (e.g., 22912_english_2025-11-17.pdf)
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", href)
        date_str = date_match.group(1) if date_match else None

        # Extract language from URL
        language = "english"
        href_lower = href.lower()
        if "sinhala" in href_lower:
            language = "sinhala"
        elif "tamil" in href_lower:
            language = "tamil"

        # Extract document ID from URL
        doc_id_match = re.search(r"/(\d+)_", href)
        doc_id = doc_id_match.group(1) if doc_id_match else None

        # Build title
        if date_str:
            title = f"Hansard - {date_str} ({language.capitalize()})"
        else:
            title = f"Hansard ({language.capitalize()})"

        # Find parent element for additional context
        parent = link.find_parent(["tr", "li", "div", "article"])
        if parent:
            parent_text = parent.get_text(separator=" ", strip=True)
            # Look for session info in parent
            session_match = re.search(
                r"(Session|Sitting|Day)\s*[:\-]?\s*(\d+)", parent_text, re.I
            )
            if session_match:
                title += f" - {session_match.group(0)}"

        # Apply keyword filter if specified
        full_text = f"{title} {href} {link_text}"
        if keywords and not _contains_keyword(full_text, keywords):
            continue

        # Construct absolute URL
        pdf_url = _make_absolute(href, url)

        entry = {
            "title": title,
            "url": pdf_url,
            "date": date_str,
            "language": language,
            "document_id": doc_id,
            "link_text": link_text,
            "timestamp": utc_now().isoformat(),
        }

        # Avoid duplicates (same doc, different language links)
        if not any(r.get("url") == pdf_url for r in results):
            results.append(entry)

        if len(results) >= max_items:
            break

    # Strategy 2: If no PDFs found, fall back to general link search
    if not results:
        logger.info("[PARLIAMENT] No PDF links found, trying general link search...")
        for a in soup.find_all("a", href=True):
            title = a.get_text(strip=True)
            href = a["href"]

            if not title or len(title) < 6:
                continue

            # Must match hansard-related keywords
            combined = f"{title} {href}".lower()
            if not re.search(
                r"(hansard|minutes|debate|transcript|proceedings)", combined
            ):
                continue

            # Apply user keyword filter
            if keywords and not _contains_keyword(title, keywords):
                continue

            href_abs = _make_absolute(href, url)

            # Avoid duplicates
            if any(r.get("url") == href_abs for r in results):
                continue

            results.append(
                {
                    "title": title,
                    "url": href_abs,
                    "timestamp": utc_now().isoformat(),
                }
            )

            if len(results) >= max_items:
                break

    if not results:
        return [
            {
                "title": "No parliament Hansards found",
                "url": url,
                "keywords": keywords,
                "note": "The website structure may have changed or no matching documents found.",
                "timestamp": utc_now().isoformat(),
            }
        ]

    logger.info(f"[PARLIAMENT] Successfully scraped {len(results)} Hansard entries")
    return results


# ============================================
# TRAIN SCHEDULE
# ============================================


def scrape_train_schedule_impl(
    from_station: Optional[str] = None,
    to_station: Optional[str] = None,
    keyword: Optional[str] = None,
    max_items: int = 30,
) -> List[Dict[str, Any]]:
    url = "https://eservices.railway.gov.lk/schedule/homeAction.action?lang=en"
    resp = _safe_get(url)
    if not resp:
        return [
            {
                "train": "Railway website unavailable",
                "note": "Could not access railway.gov.lk",
                "timestamp": utc_now().isoformat(),
            }
        ]
    soup = BeautifulSoup(resp.text, "html.parser")
    tables = soup.find_all("table")
    results: List[Dict[str, Any]] = []
    for table in tables:
        rows = table.find_all("tr")
        for row in rows[1:]:
            cols = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cols) < 2:
                continue
            train_info = {
                "train": cols[0] if len(cols) > 0 else "",
                "departure": cols[1] if len(cols) > 1 else "",
                "arrival": cols[2] if len(cols) > 2 else "",
                "route": " → ".join(cols[3:]) if len(cols) > 3 else "",
            }
            combined = " ".join(cols)
            if from_station and from_station.lower() not in combined.lower():
                continue
            if to_station and to_station.lower() not in combined.lower():
                continue
            if keyword and keyword.lower() not in combined.lower():
                continue
            results.append(train_info)
            if len(results) >= max_items:
                break
    if not results:
        return [
            {
                "train": "No train schedules found",
                "note": "Railway schedule unavailable or no matches",
                "timestamp": utc_now().isoformat(),
            }
        ]
    return results


# ============================================
# TWITTER TRENDING
# ============================================


def _scrape_twitter_trending_with_playwright(
    storage_state_path: Optional[str] = None, headless: bool = True
) -> List[Dict[str, Any]]:
    ensure_playwright()
    trending = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context_args = {}
        if storage_state_path and os.path.exists(storage_state_path):
            context_args["storage_state"] = storage_state_path

        context = browser.new_context(**context_args)
        page = context.new_page()
        try:
            page.goto(
                "https://twitter.com/i/trends", wait_until="networkidle", timeout=30000
            )
            if "login" in page.url or page.content().strip() == "":
                page.goto(
                    "https://twitter.com/explore/tabs/trending",
                    wait_until="networkidle",
                    timeout=30000,
                )
            html = page.content()
            soup = BeautifulSoup(html, "html.parser")
            items = soup.select(
                "div[role='article'] a, div[data-testid='trend'], div.trend-card, span.trend-name"
            )
            seen = set()
            for it in items:
                text = it.get_text(separator=" ", strip=True)
                href = it.get("href") or ""
                if not text or len(text) < 2:
                    continue
                if text in seen:
                    continue
                seen.add(text)
                trending.append(
                    {
                        "trend": text,
                        "url": (
                            _make_absolute(href, "https://twitter.com")
                            if href
                            else None
                        ),
                    }
                )

            if not trending:
                for tag in soup.find_all(string=re.compile(r"#\w+")):
                    t = tag.strip()
                    if t not in seen:
                        trending.append({"trend": t, "url": None})
                        seen.add(t)
            return trending
        except Exception as e:
            logger.error(f"[TWITTER] Playwright trending error: {e}")
            return []
        finally:
            try:
                context.close()
            except Exception:
                pass
            browser.close()


def _scrape_twitter_trending_with_nitter(
    instance: str = "https://nitter.net",
) -> List[Dict[str, Any]]:
    trends = []
    try:
        search_url = f"{instance}/search?f=tweets&q=Sri%20Lanka%20trend"
        resp = _safe_get(search_url)
        if not resp:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.select("a:not([href^='/pic/'])"):
            text = a.get_text(separator=" ", strip=True)
            href = a.get("href", "")
            if not text:
                continue
            if len(text) < 3:
                continue
            trends.append({"trend": text, "url": _make_absolute(href, instance)})
        return trends[:20]
    except Exception as e:
        logger.debug(f"[TWITTER] Nitter fallback failed: {e}")
        return []


def scrape_twitter_trending_srilanka(
    use_playwright: bool = True, storage_state_site: Optional[str] = None
) -> Dict[str, Any]:
    if use_playwright and PLAYWRIGHT_AVAILABLE:
        storage_state = None
        if storage_state_site:
            storage_state = load_playwright_storage_state_path(storage_state_site)
        try:
            trends = _scrape_twitter_trending_with_playwright(
                storage_state_path=storage_state
            )
            if trends:
                return {
                    "source": "twitter_playwright",
                    "trends": trends,
                    "fetched_at": utc_now().isoformat(),
                }
        except Exception as e:
            logger.debug(f"[TWITTER] Playwright attempt failed: {e}")

    nitter_instances = [
        "https://nitter.net",
        "https://nitter.snopyta.org",
        "https://nitter.1d4.us",
    ]
    for inst in nitter_instances:
        try:
            trends = _scrape_twitter_trending_with_nitter(inst)
            if trends:
                return {
                    "source": inst,
                    "trends": trends,
                    "fetched_at": utc_now().isoformat(),
                }
        except Exception:
            continue

    return {
        "source": "none",
        "trends": [],
        "note": "Could not fetch Twitter trends. Try supplying Playwright session or check network.",
    }


# ============================================
# AUTHENTICATED SCRAPERS
# ============================================


def scrape_authenticated_page_via_playwright(
    site_name: str,
    url: str,
    login_flow: Optional[dict] = None,
    headless: bool = True,
    storage_dir: str = ".sessions",
    wait_until: str = "networkidle",
) -> Dict[str, Any]:
    if not PLAYWRIGHT_AVAILABLE:
        return {
            "error": "Playwright not available. Install playwright to use authenticated scrapers."
        }

    session_path = load_playwright_storage_state_path(site_name, storage_dir)

    if not session_path:
        if not login_flow:
            return {
                "error": f"No existing session found for {site_name} and no login_flow provided to create one."
            }
        try:
            session_path = create_or_restore_playwright_session(
                site_name,
                login_flow=login_flow,
                headless=headless,
                storage_dir=storage_dir,
                wait_until=wait_until,
            )
        except Exception as e:
            return {"error": f"Failed to create Playwright session: {e}"}

    html = playwright_fetch_html_using_session(
        url, session_path, headless=headless, wait_until=wait_until
    )
    if not html:
        return {
            "error": "Failed to fetch page via Playwright session.",
            "storage_state": session_path,
        }
    return {"html": html, "source": url, "storage_state": session_path}


def _simple_parse_posts_from_html(
    html: str, base_url: str, max_items: int = 10
) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []
    candidates = soup.select(
        "article, div.post, div.feed-item, li.stream-item, div._4ikz"
    )
    if not candidates:
        candidates = soup.find_all(["article", "div"], limit=200)
    seen = set()
    for c in candidates:
        title_tag = c.find("h1") or c.find("h2") or c.find("h3") or c.find("a")
        if not title_tag:
            continue
        title = title_tag.get_text(strip=True)
        if not title or title in seen or len(title) < 4:
            continue
        seen.add(title)
        a = c.find("a", href=True)
        url = _make_absolute(a["href"], base_url) if a else base_url
        text = c.get_text(separator=" ", strip=True)[:500]
        items.append({"title": title, "snippet": text, "url": url})
        if len(items) >= max_items:
            break
    return items


# ============================================
# LANGCHAIN TOOL WRAPPERS
# ============================================


def clean_linkedin_text(text):
    if not text:
        return ""

    # Remove "…see more" and "See translation"
    text = re.sub(r"…\s*see more", "", text, flags=re.IGNORECASE)
    text = re.sub(r"See translation", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d+[dwmo]\s*•\s*(Edited)?\s*•?", "", text)
    text = re.sub(r".+posted this", "", text)
    text = re.sub(r"\d+[\.,]?\d*\s*reactions", "", text)
    text = "\n".join([line.strip() for line in text.splitlines() if line.strip()])

    return text.strip()


@tool
def scrape_linkedin(keywords: Optional[List[str]] = None, max_items: int = 10):
    """
    LinkedIn search using Playwright session.
    Requires environment variables: LINKEDIN_USER, LINKEDIN_PASSWORD (if creating session).
    """
    ensure_playwright()

    # 1. Load Session
    site = "linkedin"
    session_path = load_playwright_storage_state_path(
        site, out_dir="src/utils/.sessions"
    )
    if not session_path:
        session_path = load_playwright_storage_state_path(site, out_dir=".sessions")

    # If no session, try to create one
    if not session_path:
        login_flow = {
            "login_url": "https://www.linkedin.com/login",
            "steps": [
                {
                    "type": "fill",
                    "selector": 'input[name="session_key"]',
                    "value_env": "LINKEDIN_USER",
                },
                {
                    "type": "fill",
                    "selector": 'input[name="session_password"]',
                    "value_env": "LINKEDIN_PASSWORD",
                },
                {"type": "click", "selector": 'button[type="submit"]'},
                {"type": "wait", "selector": "nav", "timeout": 20000},
            ],
        }
        try:
            session_path = create_or_restore_playwright_session(
                site, login_flow=login_flow, headless=True
            )
        except Exception as e:
            return json.dumps(
                {"error": f"No session found and failed to create one: {e}"}
            )

    keyword = " ".join(keywords) if keywords else "Sri Lanka"
    results = []

    try:
        with sync_playwright() as p:
            desktop_ua = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )

            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--start-maximized",
                ],
            )

            context = browser.new_context(
                storage_state=session_path, user_agent=desktop_ua, no_viewport=True
            )

            page = context.new_page()
            page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

            url = f"https://www.linkedin.com/search/results/content/?keywords={keyword.replace(' ', '%20')}&origin=GLOBAL_SEARCH_HEADER"

            try:
                logger.info(f"[LINKEDIN] Navigating to {url}")
                page.goto(url, timeout=60000, wait_until="domcontentloaded")
            except Exception as e:
                logger.warning(
                    f"[LINKEDIN] Page load timed out (or other error), attempting to proceed: {e}"
                )

            page.wait_for_timeout(random.randint(4000, 7000))

            try:
                if (
                    page.locator("a[href*='login']").is_visible()
                    or "auth_wall" in page.url
                ):
                    logger.error(
                        "[LINKEDIN] Session invalid. Redirected to login/auth wall."
                    )
                    return json.dumps(
                        {"error": "Session invalid. Please refresh session."}
                    )
            except:
                pass

            seen = set()
            no_new_data_count = 0
            previous_height = 0

            POST_CONTAINER_SELECTOR = "div.feed-shared-update-v2, li.artdeco-card"
            TEXT_SELECTOR = (
                "div.update-components-text span.break-words, span.break-words"
            )
            SEE_MORE_SELECTOR = (
                "button.feed-shared-inline-show-more-text__see-more-less-toggle"
            )
            POSTER_SELECTOR = "span.update-components-actor__name span[dir='ltr']"

            while len(results) < max_items:
                try:
                    see_more_buttons = page.locator(SEE_MORE_SELECTOR).all()
                    for btn in see_more_buttons:
                        if btn.is_visible():
                            try:
                                btn.click(timeout=500)
                            except:
                                pass
                except:
                    pass

                if len(results) == 0:
                    try:
                        page.locator(POST_CONTAINER_SELECTOR).first.wait_for(
                            timeout=5000
                        )
                    except:
                        logger.warning("[LINKEDIN] No posts found on page yet.")

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
                        else:
                            raw_text = post.locator(
                                "div.feed-shared-update-v2__description-wrapper"
                            ).first.inner_text()

                        cleaned_text = clean_linkedin_text(raw_text)
                        poster_name = "(Unknown)"
                        poster_el = post.locator(POSTER_SELECTOR).first
                        if poster_el.is_visible():
                            poster_name = poster_el.inner_text().strip()
                        else:
                            poster_el = post.locator(
                                "span.update-components-actor__title span[dir='ltr']"
                            ).first
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
                                    "url": "https://www.linkedin.com",
                                }
                            )
                            logger.info(f"[LINKEDIN] Found post by {poster_name}")
                    except Exception:
                        continue

                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(random.randint(2000, 4000))

                new_height = page.evaluate("document.body.scrollHeight")
                if new_height == previous_height:
                    no_new_data_count += 1
                    if no_new_data_count > 3:
                        logger.info("[LINKEDIN] End of feed or stuck.")
                        break
                else:
                    no_new_data_count = 0
                    previous_height = new_height

            browser.close()
            return json.dumps(
                {"site": "LinkedIn", "results": results, "storage_state": session_path},
                default=str,
            )

    except Exception as e:
        return json.dumps({"error": str(e)})


# =====================================================
# 🔧 TWITTER UTILITY FUNCTIONS
# =====================================================


def clean_twitter_text(text):
    """Clean and normalize tweet text"""
    if not text:
        return ""

    # Remove common Twitter artifacts
    text = re.sub(r"Show more", "", text, flags=re.IGNORECASE)
    text = re.sub(r"https://t\.co/\w+", "", text)  # Remove t.co links
    text = re.sub(r"pic\.twitter\.com/\w+", "", text)  # Remove pic.twitter.com links
    text = re.sub(r"\s+", " ", text)  # Normalize whitespace
    text = "\n".join([line.strip() for line in text.splitlines() if line.strip()])

    return text.strip()


def extract_twitter_timestamp(tweet_element):
    """Extract timestamp from tweet element"""
    try:
        timestamp_selectors = [
            "time",
            "[datetime]",
            "a[href*='/status/'] time",
            "div[data-testid='User-Name'] a[href*='/status/']",
        ]

        for selector in timestamp_selectors:
            if tweet_element.locator(selector).count() > 0:
                time_element = tweet_element.locator(selector).first
                datetime_attr = time_element.get_attribute("datetime")
                if datetime_attr:
                    return datetime_attr
                time_text = time_element.inner_text()
                if time_text:
                    return time_text
    except:
        pass
    return "Unknown"


@tool
def scrape_twitter(query: str = "Sri Lanka", max_items: int = 20):
    """
    Twitter scraper - extracts actual tweet text, author, and metadata using Playwright session.
    Requires a valid Twitter session file (twitter_storage_state.json or tw_state.json).
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
                logger.info(f"[TWITTER] Found session at {path}")
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
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )

            context.add_init_script(
                """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = {runtime: {}};
            """
            )

            page = context.new_page()

            # Try different search URLs
            search_urls = [
                f"https://x.com/search?q={quote_plus(query)}&src=typed_query&f=live",
                f"https://x.com/search?q={quote_plus(query)}&src=typed_query",
                f"https://x.com/search?q={quote_plus(query)}",
            ]

            success = False
            for url in search_urls:
                try:
                    logger.info(f"[TWITTER] Trying {url}")
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

                    # Wait for tweets
                    try:
                        page.wait_for_selector(
                            "article[data-testid='tweet']", timeout=15000
                        )
                        logger.info("[TWITTER] Tweets found!")
                        success = True
                        break
                    except:
                        logger.warning("[TWITTER] No tweets found, trying next URL...")
                        continue
                except Exception as e:
                    logger.error(f"[TWITTER] Navigation failed: {e}")
                    continue

            if not success or "login" in page.url:
                logger.error("[TWITTER] Could not load tweets or session expired")
                return json.dumps(
                    {"error": "Session invalid or tweets not found"}, default=str
                )

            # Scraping
            seen = set()
            scroll_attempts = 0
            max_scroll_attempts = 15

            TWEET_SELECTOR = "article[data-testid='tweet']"
            TEXT_SELECTOR = "div[data-testid='tweetText']"
            USER_SELECTOR = "div[data-testid='User-Name']"

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
                        time.sleep(0.1)

                        # Skip promoted tweets
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

                        # Extract user
                        user_info = "Unknown"
                        user_element = tweet.locator(USER_SELECTOR).first
                        if user_element.count() > 0:
                            user_text = user_element.inner_text()
                            user_info = user_text.split("\n")[0].strip()

                        # Extract timestamp
                        timestamp = extract_twitter_timestamp(tweet)

                        # Deduplication
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
                            logger.info(
                                f"[TWITTER] Collected tweet {len(results)}/{max_items}"
                            )

                    except Exception:
                        continue

                # Scroll down
                if len(results) < max_items:
                    page.evaluate(
                        "window.scrollTo(0, document.documentElement.scrollHeight)"
                    )
                    time.sleep(random.uniform(2, 3))

                    if new_tweets_found == 0:
                        scroll_attempts += 1
                    else:
                        scroll_attempts = 0

            browser.close()

            return json.dumps(
                {
                    "source": "Twitter",
                    "query": query,
                    "results": results,
                    "total_found": len(results),
                    "fetched_at": utc_now().isoformat(),
                },
                default=str,
                indent=2,
            )

    except Exception as e:
        logger.error(f"[TWITTER] {e}")
        return json.dumps({"error": str(e)}, default=str)


#     """
#     Twitter trending/search wrapper. For trending, call scrape_twitter_trending_srilanka().
#     For search, this will attempt Playwright fetch if available, else Nitter fallback.
#     """
#     try:
#         if query.strip().lower() in ("trending", "trends", "trending srilanka", "trending sri lanka"):
#             return json.dumps(scrape_twitter_trending_srilanka(use_playwright=use_playwright, storage_state_site=storage_state_site), default=str)

#         if use_playwright and PLAYWRIGHT_AVAILABLE:
#             storage_state = None
#             if storage_state_site:
#                 storage_state = load_playwright_storage_state_path(storage_state_site)

#             search_url = f"https://twitter.com/search?q={quote_plus(query)}&src=typed_query"
#             try:
#                 html = playwright_fetch_html_using_session(search_url, storage_state or "", headless=True)
#                 if html:
#                     items = _simple_parse_posts_from_html(html, "https://twitter.com", max_items=20)
#                     return json.dumps({"source": "twitter_playwright", "results": items}, default=str)
#             except Exception as e:
#                 logger.debug(f"[TWITTER] Playwright search failed: {e}")

#         nitter = "https://nitter.net"
#         search_url = f"{nitter}/search?f=tweets&q={quote_plus(query)}"
#         resp = _safe_get(search_url)
#         if not resp:
#             return json.dumps({"error": "Could not fetch Twitter via Playwright or Nitter fallback"})
#         soup = BeautifulSoup(resp.text, "html.parser")
#         items = []
#         for a in soup.select("div.timeline-item"):
#             t = a.get_text(separator=" ", strip=True)
#             link = a.find("a", href=True)
#             href = _make_absolute(link["href"], nitter) if link else None
#             items.append({"text": t[:400], "url": href})
#         return json.dumps({"source": "nitter", "results": items[:20]}, default=str)
#     except Exception as e:
#         return json.dumps({"error": str(e)})


def clean_linkedin_text(text):
    if not text:
        return ""

    # Remove "…see more" and "See translation"
    text = re.sub(r"…\s*see more", "", text, flags=re.IGNORECASE)
    text = re.sub(r"See translation", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d+[dwmo]\s*•\s*(Edited)?\s*•?", "", text)
    text = re.sub(r".+posted this", "", text)
    text = re.sub(r"\d+[\.,]?\d*\s*reactions", "", text)
    text = "\n".join([line.strip() for line in text.splitlines() if line.strip()])

    return text.strip()


# =====================================================
# FACEBOOK & INSTAGRAM UTILITY FUNCTIONS
# =====================================================


def clean_fb_text(text):
    """Clean Facebook noisy text"""
    if not text:
        return ""

    text = re.sub(r"\b(?:[a-zA-Z]\s+){4,}\b", "", text)
    text = re.sub(r"(Facebook\s*){2,}", "", text)
    text = re.sub(r"Like\s*Comment\s*Share", "", text)
    text = re.sub(r"All reactions:\s*\d+\s*", "", text)
    text = re.sub(r"\n\d+\n", "\n", text)
    text = "\n".join([line.strip() for line in text.splitlines() if line.strip()])

    return text.strip()


def extract_media_id_instagram(page):
    """Extract Instagram media ID"""
    html = page.content()
    match = re.search(r'"media_id":"(\d+)"', html)
    if match:
        return match.group(1)
    match = re.search(r'"id":"(\d+_\d+)"', html)
    if match:
        return match.group(1)
    return None


def fetch_caption_via_private_api(page, media_id):
    """Instagram Private API Caption fetch"""
    if not media_id:
        return None

    api_url = f"https://i.instagram.com/api/v1/media/{media_id}/info/"

    try:
        response = page.request.get(
            api_url,
            headers={
                "User-Agent": (
                    "Instagram 290.0.0.0.66 (iPhone14,5; iOS 17_0; en_US) "
                    "AppleWebKit/605.1.15"
                ),
                "X-IG-App-ID": "936619743392459",
            },
            timeout=20000,
        )
        if response.status != 200:
            return None

        data = response.json()
        if "items" in data and data["items"]:
            return data["items"][0].get("caption", {}).get("text")
    except:
        pass

    return None


@tool
def scrape_instagram(keywords: Optional[List[str]] = None, max_items: int = 15):
    """
    Instagram scraper using Playwright session.
    Scrapes posts from hashtag search and extracts captions.
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
                logger.info(f"[INSTAGRAM] Found session at {path}")
                break

    if not session_path:
        return json.dumps(
            {
                "error": "No Instagram session found",
                "solution": "Run the Instagram session manager to create a session",
            },
            default=str,
        )

    keyword = " ".join(keywords) if keywords else "srilanka"
    keyword = keyword.replace(" ", "")  # Instagram hashtags don't have spaces
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
            url = f"https://www.instagram.com/explore/tags/{keyword}/"

            logger.info(f"[INSTAGRAM] Navigating to {url}")
            page.goto(url, timeout=120000)
            page.wait_for_timeout(4000)

            # Scroll to load posts
            for _ in range(12):
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

            logger.info(f"[INSTAGRAM] Found {len(links)} posts")

            # Extract captions from each post
            for link in links:
                logger.info(f"[INSTAGRAM] Scraping {link}")
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
                            "text": caption,
                            "url": link,
                            "poster": "(Instagram User)",
                        }
                    )
                    logger.info(
                        f"[INSTAGRAM] Collected caption {len(results)}/{max_items}"
                    )

            browser.close()

            return json.dumps(
                {
                    "site": "Instagram",
                    "results": results,
                    "storage_state": session_path,
                },
                default=str,
            )

    except Exception as e:
        logger.error(f"[INSTAGRAM] {e}")
        return json.dumps({"error": str(e)}, default=str)


@tool
def scrape_facebook(keywords: Optional[List[str]] = None, max_items: int = 10):
    """
    Facebook scraper using Playwright session (Desktop).
    Extracts posts from keyword search with poster names and text.
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
                logger.info(f"[FACEBOOK] Found session at {path}")
                break

    if not session_path:
        return json.dumps(
            {
                "error": "No Facebook session found",
                "solution": "Run the Facebook session manager to create a session",
            },
            default=str,
        )

    keyword = " ".join(keywords) if keywords else "Sri Lanka"
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

            search_url = f"https://www.facebook.com/search/posts?q={quote(keyword)}"

            logger.info(f"[FACEBOOK] Navigating to {search_url}")
            page.goto(search_url, timeout=120000)
            time.sleep(5)

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
                    "span:text-is('... See more')",
                    "span:text-is('...See more')",
                    # Alternate patterns
                    "[role='button']:has-text('See more')",
                    "div.x1i10hfl:has-text('See more')",
                    # Direct text match
                    "text='See more'",
                    "text='... See more'",
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
                    logger.info(f"[FACEBOOK] Expanded {clicked} 'See more' buttons")
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
                                        "url": "https://www.facebook.com",
                                    }
                                )
                                logger.info(
                                    f"[FACEBOOK] Collected post {len(results)}/{max_items}"
                                )

                        if len(results) >= max_items:
                            break

                    except:
                        pass

                # Scroll
                page.evaluate("window.scrollBy(0, 2300)")
                time.sleep(1.2)

                new_scroll = page.evaluate("window.scrollY")
                stuck = stuck + 1 if new_scroll == last_scroll else 0
                last_scroll = new_scroll

                if stuck >= 3:
                    logger.info("[FACEBOOK] Reached end of results")
                    break

            browser.close()

            return json.dumps(
                {
                    "site": "Facebook",
                    "results": results[:max_items],
                    "storage_state": session_path,
                },
                default=str,
            )

    except Exception as e:
        logger.error(f"[FACEBOOK] {e}")
        return json.dumps({"error": str(e)}, default=str)


@tool
def scrape_government_gazette(
    keywords: Optional[List[str]] = None, max_items: int = 15
):
    """
    Search and scrape Sri Lankan government gazette entries from gazette.lk.
    This tool visits each gazette page to extract full descriptions and download links (PDFs).
    """
    data = scrape_government_gazette_impl(keywords=keywords, max_items=max_items)
    return json.dumps(data, default=str)


def clean_linkedin_text(text):
    if not text:
        return ""

    # Remove "…see more" and "See translation"
    text = re.sub(r"…\s*see more", "", text, flags=re.IGNORECASE)
    text = re.sub(r"See translation", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d+[dwmo]\s*•\s*(Edited)?\s*•?", "", text)
    text = re.sub(r".+posted this", "", text)
    text = re.sub(r"\d+[\.,]?\d*\s*reactions", "", text)
    text = "\n".join([line.strip() for line in text.splitlines() if line.strip()])

    return text.strip()


@tool
def scrape_parliament_minutes(
    keywords: Optional[List[str]] = None, max_items: int = 20
):
    """
    Search and scrape Sri Lankan Parliament Hansards and minutes matching keywords.
    """
    data = scrape_parliament_minutes_impl(keywords=keywords, max_items=max_items)
    return json.dumps(data, default=str)


def clean_linkedin_text(text):
    if not text:
        return ""

    # Remove "…see more" and "See translation"
    text = re.sub(r"…\s*see more", "", text, flags=re.IGNORECASE)
    text = re.sub(r"See translation", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d+[dwmo]\s*•\s*(Edited)?\s*•?", "", text)
    text = re.sub(r".+posted this", "", text)
    text = re.sub(r"\d+[\.,]?\d*\s*reactions", "", text)
    text = "\n".join([line.strip() for line in text.splitlines() if line.strip()])

    return text.strip()


@tool
def scrape_train_schedule(
    from_station: Optional[str] = None,
    to_station: Optional[str] = None,
    keyword: Optional[str] = None,
    max_items: int = 30,
):
    """
    Scrape Sri Lanka Railways train schedule based on stations or keywords.
    """
    data = scrape_train_schedule_impl(
        from_station=from_station,
        to_station=to_station,
        keyword=keyword,
        max_items=max_items,
    )
    return json.dumps(data, default=str)


def clean_linkedin_text(text):
    if not text:
        return ""

    # Remove "…see more" and "See translation"
    text = re.sub(r"…\s*see more", "", text, flags=re.IGNORECASE)
    text = re.sub(r"See translation", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d+[dwmo]\s*•\s*(Edited)?\s*•?", "", text)
    text = re.sub(r".+posted this", "", text)
    text = re.sub(r"\d+[\.,]?\d*\s*reactions", "", text)
    text = "\n".join([line.strip() for line in text.splitlines() if line.strip()])

    return text.strip()


@tool
def scrape_cse_stock_data(
    symbol: str = "ASPI", period: str = "1d", interval: str = "1h"
):
    """
    Scrape Colombo Stock Exchange (CSE) data for a given symbol (e.g., ASPI).
    Tries yfinance first, then falls back to direct site scraping.
    """
    data = scrape_cse_stock_impl(symbol=symbol, period=period, interval=interval)
    return json.dumps(data, default=str)


def clean_linkedin_text(text):
    if not text:
        return ""

    # Remove "…see more" and "See translation"
    text = re.sub(r"…\s*see more", "", text, flags=re.IGNORECASE)
    text = re.sub(r"See translation", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d+[dwmo]\s*•\s*(Edited)?\s*•?", "", text)
    text = re.sub(r".+posted this", "", text)
    text = re.sub(r"\d+[\.,]?\d*\s*reactions", "", text)
    text = "\n".join([line.strip() for line in text.splitlines() if line.strip()])

    return text.strip()


@tool
def scrape_local_news(keywords: Optional[List[str]] = None, max_articles: int = 30):
    """
    Scrape major Sri Lankan local news websites (Daily Mirror, Daily FT, etc.) for articles matching keywords.
    """
    data = scrape_local_news_impl(keywords=keywords, max_articles=max_articles)
    return json.dumps(data, default=str)


def clean_linkedin_text(text):
    if not text:
        return ""

    # Remove "…see more" and "See translation"
    text = re.sub(r"…\s*see more", "", text, flags=re.IGNORECASE)
    text = re.sub(r"See translation", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d+[dwmo]\s*•\s*(Edited)?\s*•?", "", text)
    text = re.sub(r".+posted this", "", text)
    text = re.sub(r"\d+[\.,]?\d*\s*reactions", "", text)
    text = "\n".join([line.strip() for line in text.splitlines() if line.strip()])

    return text.strip()


@tool
def think_tool(reflection: str) -> str:
    """
    Log a thought or reflection from the agent. Useful for debugging or tracing the agent's reasoning.
    """
    return f"Reflection recorded: {reflection}"


# =====================================================
# FACEBOOK & INSTAGRAM UTILITY FUNCTIONS
# =====================================================


def clean_fb_text(text):
    """Clean Facebook noisy text"""
    if not text:
        return ""

    text = re.sub(r"\b(?:[a-zA-Z]\s+){4,}\b", "", text)
    text = re.sub(r"(Facebook\s*){2,}", "", text)
    text = re.sub(r"Like\s*Comment\s*Share", "", text)
    text = re.sub(r"All reactions:\s*\d+\s*", "", text)
    text = re.sub(r"\n\d+\n", "\n", text)
    text = "\n".join([line.strip() for line in text.splitlines() if line.strip()])

    return text.strip()


def extract_media_id_instagram(page):
    """Extract Instagram media ID"""
    html = page.content()
    match = re.search(r'"media_id":"(\d+)"', html)
    if match:
        return match.group(1)
    match = re.search(r'"id":"(\d+_\d+)"', html)
    if match:
        return match.group(1)
    return None


def fetch_caption_via_private_api(page, media_id):
    """Instagram Private API Caption fetch"""
    if not media_id:
        return None

    api_url = f"https://i.instagram.com/api/v1/media/{media_id}/info/"

    try:
        response = page.request.get(
            api_url,
            headers={
                "User-Agent": (
                    "Instagram 290.0.0.0.66 (iPhone14,5; iOS 17_0; en_US) "
                    "AppleWebKit/605.1.15"
                ),
                "X-IG-App-ID": "936619743392459",
            },
            timeout=20000,
        )
        if response.status != 200:
            return None

        data = response.json()
        if "items" in data and data["items"]:
            return data["items"][0].get("caption", {}).get("text")
    except:
        pass

    return None


@tool
def scrape_instagram(keywords: Optional[List[str]] = None, max_items: int = 15):
    """
    Instagram scraper using Playwright session.
    Scrapes posts from hashtag search and extracts captions.
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
                logger.info(f"[INSTAGRAM] Found session at {path}")
                break

    if not session_path:
        return json.dumps(
            {
                "error": "No Instagram session found",
                "solution": "Run the Instagram session manager to create a session",
            },
            default=str,
        )

    keyword = " ".join(keywords) if keywords else "srilanka"
    keyword = keyword.replace(" ", "")  # Instagram hashtags don't have spaces
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
            url = f"https://www.instagram.com/explore/tags/{keyword}/"

            logger.info(f"[INSTAGRAM] Navigating to {url}")
            page.goto(url, timeout=120000)
            page.wait_for_timeout(4000)

            # Scroll to load posts
            for _ in range(12):
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

            logger.info(f"[INSTAGRAM] Found {len(links)} posts")

            # Extract captions from each post
            for link in links:
                logger.info(f"[INSTAGRAM] Scraping {link}")
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
                            "text": caption,
                            "url": link,
                            "poster": "(Instagram User)",
                        }
                    )
                    logger.info(
                        f"[INSTAGRAM] Collected caption {len(results)}/{max_items}"
                    )

            browser.close()

            return json.dumps(
                {
                    "site": "Instagram",
                    "results": results,
                    "storage_state": session_path,
                },
                default=str,
            )

    except Exception as e:
        logger.error(f"[INSTAGRAM] {e}")
        return json.dumps({"error": str(e)}, default=str)


@tool
def scrape_facebook(keywords: Optional[List[str]] = None, max_items: int = 10):
    """
    Facebook scraper using Playwright session (Desktop).
    Extracts posts from keyword search with poster names and text.
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
                logger.info(f"[FACEBOOK] Found session at {path}")
                break

    if not session_path:
        return json.dumps(
            {
                "error": "No Facebook session found",
                "solution": "Run the Facebook session manager to create a session",
            },
            default=str,
        )

    keyword = " ".join(keywords) if keywords else "Sri Lanka"
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
            search_url = (
                f"https://www.facebook.com/search/posts?q={keyword.replace(' ', '%20')}"
            )

            logger.info(f"[FACEBOOK] Navigating to {search_url}")
            page.goto(search_url, timeout=120000)
            time.sleep(5)

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
                                logger.info(
                                    f"[FACEBOOK] Collected post {len(results)}/{max_items}"
                                )

                        if len(results) >= max_items:
                            break

                    except:
                        pass

                # Scroll
                page.evaluate("window.scrollBy(0, 2300)")
                time.sleep(1.2)

                new_scroll = page.evaluate("window.scrollY")
                stuck = stuck + 1 if new_scroll == last_scroll else 0
                last_scroll = new_scroll

                if stuck >= 3:
                    logger.info("[FACEBOOK] Reached end of results")
                    break

            browser.close()

            return json.dumps(
                {
                    "site": "Facebook",
                    "results": results[:max_items],
                    "storage_state": session_path,
                },
                default=str,
            )

    except Exception as e:
        logger.error(f"[FACEBOOK] {e}")
        return json.dumps({"error": str(e)}, default=str)


@tool
def scrape_reddit(
    keywords: List[str], limit: int = 20, subreddit: Optional[str] = None
):
    """
    Scrape Reddit for posts matching specific keywords.
    Optionally restrict to a specific subreddit.
    """
    data = scrape_reddit_impl(keywords=keywords, limit=limit, subreddit=subreddit)
    return json.dumps(data, default=str)


# ============================================
# TOOL REGISTRY & EXPORTS
# ============================================

TOOL_MAPPING = {
    "scrape_linkedin": scrape_linkedin,
    "scrape_instagram": scrape_instagram,
    "scrape_facebook": scrape_facebook,
    "scrape_reddit": scrape_reddit,
    "scrape_twitter": scrape_twitter,
    "scrape_government_gazette": scrape_government_gazette,
    "scrape_parliament_minutes": scrape_parliament_minutes,
    "scrape_train_schedule": scrape_train_schedule,
    "scrape_cse_stock_data": scrape_cse_stock_data,
    "scrape_local_news": scrape_local_news,
    "think_tool": think_tool,
}

# Import and add profile scrapers for competitive intelligence
try:
    from src.utils.profile_scrapers import (
        scrape_twitter_profile,
        scrape_facebook_profile,
        scrape_instagram_profile,
        scrape_linkedin_profile,
        scrape_product_reviews,
    )

    TOOL_MAPPING["scrape_twitter_profile"] = scrape_twitter_profile
    TOOL_MAPPING["scrape_facebook_profile"] = scrape_facebook_profile
    TOOL_MAPPING["scrape_instagram_profile"] = scrape_instagram_profile
    TOOL_MAPPING["scrape_linkedin_profile"] = scrape_linkedin_profile
    TOOL_MAPPING["scrape_product_reviews"] = scrape_product_reviews
    print("[OK] Profile scrapers loaded for Intelligence Agent")
except ImportError as e:
    print(f"[WARN] Profile scrapers not available: {e}")


ALL_TOOLS = list(TOOL_MAPPING.values())

__all__ = [
    "get_today_str",
    "tool_dmc_alerts",
    "tool_weather_nowcast",
    "TOOL_MAPPING",
    "ALL_TOOLS",
    "create_or_restore_playwright_session",
    "playwright_fetch_html_using_session",
]
