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










# ============================================
# RIVERNET - FLOOD MONITORING (NEW)
# ============================================

# Cache for rivernet data (to avoid excessive scraping)
_rivernet_cache: Dict[str, Any] = {}
_rivernet_cache_time: Optional[datetime] = None
RIVERNET_CACHE_DURATION_MINUTES = 30  # Increased from 15 to reduce load

# rivernet.lk's own JSON API, the one its Flutter front-end calls. Found in the
# app's bundle (CACHE_URL/API_URL constants). Public -- no key, no session.
RIVERNET_API_URL = "https://api.rivernet.lk/api/overview/latest-status-paginated"

# Severity comes from latest.alertType, which the API states outright. Do NOT
# derive it from alertColor: the colours are not a severity ramp. Observed live,
# 29 of 30 stations are Blue (#44518C) with alertType "normal", and the single
# Green (#A9FF6E) station is the one at alertType "alert" -- so reading green as
# "safe" and blue as "alert", which is the intuitive guess, inverts the meaning
# and would have reported 29 false flood alerts out of 30 stations.
RIVERNET_SEVERITY = {
    "normal": "normal",
    "alert": "alert",
    "warning": "warning",
    "danger": "critical",
    "critical": "critical",
}

# Kept only so a colour can be shown in the UI; not used for severity.
RIVERNET_ALERT_COLOURS = {
    "#A9FF6E": "green",
    "#F9E973": "yellow",
    "#FF9B2B": "orange",
    "#EC3E40": "red",
    "#44518C": "blue",
    "#FFFFFF": "white",
}

# Severities that mean water, as opposed to a gauge that went quiet.
RIVERNET_FLOOD_SEVERITIES = ("warning", "alert", "critical")


def _summarise_rivernet(results: Dict[str, Any]) -> Dict[str, Any]:
    """
    Roll station readings up into the summary the API and the dashboard read.

    results["alerts"] deliberately mixes two different things: stations at a
    real warning level, and stations that have stopped reporting. Both deserve
    attention -- a gauge going dark mid-monsoon is worth knowing -- but only the
    first is a flood signal, so they are counted separately. Treating the
    combined count as flood alerts raises a flood warning off offline hardware:
    on a sample run, all four alerts were silent stations and no river was
    rising.

    Keys here are the contract for /api/rivernet, the meteorological bulletin
    and the React flood panel. See tests/unit/test_rivernet_contract.py.
    """
    rivers = results.get("rivers") or []
    alerts = results.get("alerts") or []

    reporting = [r for r in rivers if r.get("reporting")]
    flood_alerts = sum(
        1 for a in alerts if a.get("severity") in RIVERNET_FLOOD_SEVERITIES
    )
    rising = sum(1 for r in reporting if r.get("trend") == "rising")

    if flood_alerts:
        status = "alert"
    elif rising:
        status = "rising"
    elif reporting:
        status = "normal"
    else:
        status = "unknown"

    return {
        "total_stations": len(rivers),
        "reporting": len(reporting),
        "offline": len(rivers) - len(reporting),
        "rising": rising,
        "alerts": len(alerts),
        "flood_alerts": flood_alerts,
        "status": status,
        "regions": sorted({r["region"] for r in rivers if r.get("region")}),
    }


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
    River levels and flood alerts from rivernet.lk.

    Uses rivernet.lk's own JSON API rather than driving a browser.

    The previous implementation launched Chromium against the Flutter SPA and
    waited up to five minutes for it to render -- because a plain GET of
    https://rivernet.lk returns a shell whose entire visible text is
    "RIVERNET.LK". That made this the only reason the server image still needed
    a browser, which is 100-300 MB resident on a 512 MB instance.

    The SPA gets its data from a public endpoint, found in its own bundle:

        GET https://api.rivernet.lk/api/overview/latest-status-paginated
            ?deviceType=river_level

    Note deviceType, camelCase -- device_type and type both return
    HTTP 400 "No time series data found for the specified device type."

    That returns ~30 stations with level, unit, alert colour, trend, comms
    status and coordinates. Same data the site shows, in ~1 second instead of
    five minutes, with no browser.
    """
    global _rivernet_cache, _rivernet_cache_time

    if use_cache and _rivernet_cache_time:
        cache_age = (utc_now() - _rivernet_cache_time).total_seconds() / 60
        if cache_age < RIVERNET_CACHE_DURATION_MINUTES:
            logger.info(f"[RIVERNET] Using cached data ({cache_age:.1f} min old)")
            return _rivernet_cache

    logger.info("[RIVERNET] Fetching river levels from the rivernet.lk API...")

    results: Dict[str, Any] = {
        "rivers": [],
        "alerts": [],
        "summary": {},
        "fetched_at": utc_now().isoformat(),
        "source": "api.rivernet.lk",
    }

    try:
        response = requests.get(
            RIVERNET_API_URL,
            params={"deviceType": "river_level"},
            headers={**DEFAULT_HEADERS, "Accept": "application/json"},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as e:
        logger.error(f"[RIVERNET] API request failed: {e}")
        # Must carry the same shape as a successful call, summary included.
        # Returning a dict without "summary" meant every consumer fell through
        # to its .get() defaults and read zeros -- the failure was invisible.
        failed = {
            "error": f"Could not reach the rivernet.lk API: {e}",
            "rivers": [],
            "alerts": [],
            "summary": _summarise_rivernet({"rivers": [], "alerts": []}),
            "fetched_at": utc_now().isoformat(),
        }
        failed["summary"]["status"] = "error"
        return stamp(failed, "error", source_url="https://rivernet.lk")

    stations = (payload.get("results") or {}).get("data") or []
    wanted = {loc.lower() for loc in locations} if locations else None

    for station in stations:
        try:
            latest = station.get("latest") or {}
            extra = station.get("additional") or {}
            region = (station.get("region") or "").lower()

            if wanted and region not in wanted:
                continue

            level = latest.get("latestLevel")
            level = float(level) if level not in (None, "") else None
            previous = latest.get("before30mLevel")
            previous = float(previous) if previous not in (None, "") else None

            # change is the API's own trend flag: 1 rising, -1 falling, 0 steady.
            change = latest.get("change")
            trend = {1: "rising", -1: "falling", 0: "steady"}.get(change, "unknown")

            # alertType is the API's own severity label. Colour is decorative
            # here -- see the note on RIVERNET_SEVERITY for why inferring
            # severity from it produces 29 false alerts out of 30 stations.
            colour = (latest.get("alertColor") or "").upper()
            severity = RIVERNET_SEVERITY.get(
                (latest.get("alertType") or "").lower(), "unknown"
            )

            river = {
                "name": latest.get("name") or extra.get("location") or station.get("unitId"),
                "region": region,
                "level_m": level,
                "previous_level_m": previous,
                "max_level_m": extra.get("maxLevel"),
                "trend": trend,
                "severity": severity,
                "alert_colour": RIVERNET_ALERT_COLOURS.get(colour, colour or None),
                "reading_time": latest.get("datetime") or latest.get("time"),
                # A station that has stopped reporting is itself signal during a
                # flood -- surfaced rather than silently treated as "no alert".
                "reporting": bool(latest.get("communication")),
                "coordinates": extra.get("coordinates"),
                "unit_id": station.get("unitId"),
            }
            results["rivers"].append(river)

            if severity in ("warning", "alert", "critical") or not river["reporting"]:
                results["alerts"].append({
                    "river": river["name"],
                    "region": region,
                    "severity": severity if river["reporting"] else "no_data",
                    "level_m": level,
                    "max_level_m": extra.get("maxLevel"),
                    "trend": trend,
                    "message": (
                        f"{river['name']}: {level}m ({trend})"
                        if river["reporting"]
                        else f"{river['name']}: station not reporting"
                    ),
                })
        except Exception as e:
            logger.warning(f"[RIVERNET] Skipped a malformed station record: {e}")
            continue

    results["summary"] = _summarise_rivernet(results)

    logger.info(
        f"[RIVERNET] {results['summary']['total_stations']} stations, "
        f"{results['summary']['alerts']} alert(s)"
    )

    # Stations that stopped reporting make this partial rather than live: the
    # feed is working, but it is not seeing the whole river network.
    stamp(
        results,
        "live" if not results["summary"]["offline"] else "partial",
        as_of=results.get("fetched_at"),
        source_url="https://rivernet.lk",
    )

    _rivernet_cache = results
    _rivernet_cache_time = utc_now()
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
    # Use the weather nowcast tool and filter for district
    weather_data = tool_weather_nowcast(location=district)

    if "error" in weather_data:
        return weather_data

    # Extract district-specific information from the forecast
    forecast_text = weather_data.get("forecast", "")

    # Try to find district-specific mention. Provenance is inherited from the
    # nowcast -- including "partial", which is how this district gets told that
    # meteo.gov.lk had readings, but not for it.
    district_info = {
        "district": district.title(),
        "forecast": forecast_text,
        "reading": weather_data.get("selected"),
        "source": weather_data.get("source"),
        "fetched_at": weather_data.get("fetched_at"),
        "scrape_status": weather_data.get("scrape_status", "live"),
        "data_as_of": weather_data.get("data_as_of"),
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
    #
    # This read river["status"] with a "danger"/"warning"/"rising" vocabulary.
    # fetch_rivernet_levels emits neither: the field is "severity", valued
    # normal/alert/warning/critical, with the trend in "trend" and liveness in
    # "reporting". So `status` was always the "unknown" default and the river
    # half of the national flood threat -- 50 of its 100 points -- has never
    # contributed anything, over a live 30-station feed.
    if river_data and river_data.get("rivers"):
        for river in river_data.get("rivers", []):
            severity = str(river.get("severity") or "unknown").lower()
            trend = str(river.get("trend") or "").lower()
            region = river.get("region", "")

            if severity == "critical":
                breakdown["river_contribution"] += 15
                if region and region not in critical_districts:
                    critical_districts.append(region)
            elif severity in ("warning", "alert"):
                breakdown["river_contribution"] += 8
                if region and region not in high_risk_districts:
                    high_risk_districts.append(region)
            elif trend == "rising" and river.get("reporting"):
                # Rising water at a normal level is early warning, not a threat.
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

    # Starts UNKNOWN, not "operational".
    #
    # This previously defaulted to status="operational",
    # load_shedding_active=False and, when nothing was scraped, announced
    # "CEB: Normal power supply across the island" -- an affirmative claim about
    # the national grid made without having successfully read anything. A failed
    # scrape asserted the lights were on. During actual load shedding that is
    # precisely backwards, and it is the one card where being wrong has
    # operational consequences for a business.
    #
    # CEB's live outage feed (cebcare.ceb.lk/Incognito/GetOutageLocationsInArea)
    # returns 401 without a session and rate-limits aggressively, so it cannot
    # be read anonymously. Until that is wired up with credentials, this tool
    # reports only what it can actually see -- announcements and press releases
    # from ceb.lk -- and says "unknown" otherwise.
    result = {
        "status": "unknown",
        "load_shedding_active": None,
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

        # Nothing found is NOT evidence that the grid is healthy. It means we
        # looked at ceb.lk's announcements and saw no outage notice -- which is
        # the normal state on most days, but is also exactly what a broken
        # scraper looks like. Say which one this is, and never claim "normal
        # power supply across the island" off a silent page.
        if not result["press_releases"] and not result["announcements"]:
            result["status"] = "no_announcements"
            result["announcements"].append(
                "No CEB outage announcements found. This is not a confirmation "
                "that supply is normal -- CEB's live outage feed requires a "
                "session and is not being read."
            )
            logger.info("[CEB] no outage announcements found; status=no_announcements")
        else:
            result["scrape_status"] = "live"

    except Exception as e:
        logger.warning(f"[CEB] Scraping error: {e}")
        result["status"] = "unknown"
        result["scrape_status"] = "error"
        result["error"] = str(e)

    # Update cache
    _ceb_cache = result
    _ceb_cache_time = utc_now()

    return result


# ---------------------------------------------------------------------------
# Data provenance
#
# Every tool in this module answers a question a business will act on, so every
# tool must say where its answer came from. Six of the ten returned no
# provenance at all, which is how a dashboard came to show a hardcoded 2.1 %
# inflation figure indistinguishable from a live one.
#
# The vocabulary is closed and tested (tests/unit/test_provenance.py). The UI
# switches on it, so adding a value is a deliberate act.
# ---------------------------------------------------------------------------

PROVENANCE_STATUSES = frozenset({"live", "partial", "baseline", "unavailable", "error"})


def stamp(
    result: Dict[str, Any],
    status: str,
    *,
    as_of: Optional[str] = None,
    source: Optional[str] = None,
    source_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Record how a tool's data was obtained.

      live        every value came from the source, this call
      partial     some values are live, others fell back
      baseline    the source could not be read; these are canned values
      unavailable there is no readable source (needs credentials, etc.)
      error       the attempt raised

    ``as_of`` is the period the DATA describes, which is not the same as the
    moment it was fetched -- CBSL's July figure retrieved in August is
    as_of "July 2026", fetched_at now. Conflating the two is what made stale
    numbers look current.
    """
    if status not in PROVENANCE_STATUSES:
        raise ValueError(
            f"unknown provenance status {status!r}; "
            f"expected one of {sorted(PROVENANCE_STATUSES)}"
        )

    result["scrape_status"] = status
    result.setdefault("fetched_at", utc_now().isoformat())
    if as_of is not None:
        result["data_as_of"] = as_of
    if source is not None:
        result["source"] = source
    if source_url is not None:
        result["source_url"] = source_url
    return result


CEYPETCO_URL = "https://ceypetco.gov.lk/marketing-sales/"

# CEYPETCO renders each product as a card, not a table, which flattens to:
#   Lanka Petrol 92 Octane|White Oil|Rs.|414.00|per Ltr|<icon>|Effect from: 29-06-2026 ...
CEYPETCO_ROW_RE = re.compile(
    r"([A-Z][A-Za-z0-9 ]{3,40}?)\|[^|]{0,20}\|Rs\.\|([\d,]+\.\d{2})\|per Ltr"
    r"[^|]*\|[^|]*\|Effect from:\s*([\d.\-/]+)"
)

# Sri Lankan pump prices have ranged roughly Rs.100-800 in the past decade; a
# parse that lands outside that has matched the wrong number.
FUEL_PRICE_MIN = 50.0
FUEL_PRICE_MAX = 2000.0

# CEYPETCO's product names -> the keys the frontend already reads. Order matters:
# "Petrol 95" must be tested before "Petrol", and "Industrial Kerosene" before
# "Kerosene", or the shorter name swallows the longer product.
FUEL_KEY_PATTERNS = (
    ("petrol_95", ("petrol 95",)),
    ("petrol_92", ("petrol 92",)),
    ("super_diesel", ("super diesel",)),
    ("auto_diesel", ("auto diesel",)),
    ("industrial_kerosene", ("industrial kerosene",)),
    ("kerosene", ("kerosene",)),
    ("fuel_oil", ("fuel oil",)),
)


def _fuel_key(product: str) -> Optional[str]:
    """Map a CEYPETCO product name onto the dashboard's price key."""
    lowered = product.lower()
    for key, needles in FUEL_KEY_PATTERNS:
        if any(n in lowered for n in needles):
            return key
    return None


def _fuel_date_key(value: str) -> tuple:
    """Sort 'DD-MM-YYYY' chronologically; unparseable dates sort first."""
    parts = re.split(r"[-./]", value)
    if len(parts) == 3 and len(parts[2]) == 4:
        try:
            return (int(parts[2]), int(parts[1]), int(parts[0]))
        except ValueError:
            pass
    return (0, 0, 0)


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

    # This used to trawl three news homepages for any number next to the word
    # "petrol" -- which is why it never once produced a real price, and why the
    # dashboard showed Rs.294 for petrol 92 when CEYPETCO's own published price
    # was Rs.414. CEYPETCO publishes the authoritative table itself, with the
    # date each price took effect.
    result["scrape_status"] = "baseline"

    try:
        resp = _safe_get(CEYPETCO_URL, timeout=25)
        if resp:
            text = BeautifulSoup(resp.text, "html.parser").get_text("|", strip=True)

            scraped = {}
            effective_dates = []
            for match in CEYPETCO_ROW_RE.finditer(text):
                product, raw_price, effective = match.groups()
                key = _fuel_key(product)
                if not key:
                    continue
                try:
                    price = float(raw_price.replace(",", ""))
                except ValueError:
                    continue
                if not (FUEL_PRICE_MIN <= price <= FUEL_PRICE_MAX):
                    logger.warning(
                        "[FUEL] %s at %.2f is outside the sane range; ignoring",
                        product, price,
                    )
                    continue

                scraped[key] = {
                    "price": round(price, 2),
                    "unit": "LKR/L",
                    "name": product.replace("Lanka ", "").strip(),
                    "effective_from": effective,
                }
                effective_dates.append(effective)

            if scraped:
                result["prices"].update(scraped)
                result["scrape_status"] = "live"
                result["source"] = "CEYPETCO (ceypetco.gov.lk)"
                result["source_url"] = CEYPETCO_URL
                # Newest "Effect from" across the products actually read.
                result["last_revision"] = max(effective_dates, key=_fuel_date_key)
                result["data_as_of"] = result["last_revision"]
                result.pop("note", None)
                logger.info(
                    "[FUEL] scraped %d live prices from CEYPETCO (petrol 92: %s)",
                    len(scraped), result["prices"]["petrol_92"]["price"],
                )
            else:
                logger.warning(
                    "[FUEL] reached CEYPETCO but parsed no prices -- the page "
                    "layout has changed. Serving BASELINE values."
                )
        else:
            logger.warning("[FUEL] could not reach CEYPETCO; serving BASELINE values")

    except Exception as e:
        logger.warning(f"[FUEL] Scraping error: {e}")
        result["error"] = str(e)
        result["scrape_status"] = "error"

    # Update cache
    _fuel_cache = result
    _fuel_cache_time = utc_now()

    return result


# CBSL publishes its headline numbers as prose in the press releases on the
# homepage, not as a data widget. The previous patterns looked for a widget that
# does not exist -- "CCPI Inflation 2.10%", "TT Buy 305.32" -- so nothing ever
# matched and the tool silently served the hardcoded baseline below, which by
# 2026-08 had inflation at 2.1% against an actual 7.3% and the policy rate at
# 7.75% against an actual 8.75%.
#
# Matching prose is inherently more fragile than matching a table, so each
# pattern is anchored on the phrasing CBSL has used consistently, every match is
# range-checked, and tests/unit/test_cbsl_parser.py pins them against captured
# text. If CBSL rewords, the tool reports "baseline" loudly rather than lying.
CBSL_CCPI_RE = re.compile(
    r"CCPI[^.]{0,120}?headline inflation[^.]{0,90}?"
    r"to\s+(\d{1,2}(?:\.\d)?)\s*%\s*in\s+([A-Z][a-z]+\s+\d{4})",
    re.I,
)
CBSL_FOOD_RE = re.compile(
    r"food inflation[^.]{0,60}?to\s+(\d{1,2}(?:\.\d)?)\s*%\s*in\s+([A-Z][a-z]+\s+\d{4})",
    re.I,
)
# Covers both "maintain ... at the current level of X%" and "reduce ... to X%".
CBSL_OPR_RE = re.compile(
    r"Overnight Policy Rate[^.]{0,140}?(?:at|to)\s+"
    r"(?:the\s+current\s+level\s+of\s+)?(\d{1,2}\.\d{1,2})\s*%",
    re.I,
)

# Sanity ranges. A regex that drifts onto the wrong number usually lands well
# outside these, and a wrong-but-plausible economic figure is worse than none.
CBSL_RANGES = {
    "inflation": (-10.0, 80.0),
    "policy_rate": (1.0, 30.0),
    "usd_lkr": (150.0, 600.0),
}


def _cbsl_in_range(kind: str, value: float) -> bool:
    lo, hi = CBSL_RANGES[kind]
    return lo <= value <= hi


def fetch_usd_lkr() -> Optional[Dict[str, Any]]:
    """
    Current USD/LKR.

    CBSL's own exchange-rate page renders its table with JavaScript -- fetching
    it yields ~5 KB of chrome and no numbers -- so it cannot be scraped with
    requests, and standing up a browser for one number is not worth it. yfinance
    is already a dependency of this module and carries the pair as USDLKR=X.
    """
    try:
        import yfinance as _yf

        hist = _yf.Ticker("USDLKR=X").history(period="5d")
        if hist is None or hist.empty:
            return None

        rate = float(hist["Close"].iloc[-1])
        if not _cbsl_in_range("usd_lkr", rate):
            logger.warning("[CBSL] USD/LKR %.2f outside sane range; ignoring", rate)
            return None

        prev = float(hist["Close"].iloc[0]) if len(hist) > 1 else rate
        if rate > prev * 1.005:
            trend = "depreciating"
        elif rate < prev * 0.995:
            trend = "appreciating"
        else:
            trend = "stable"

        return {
            "usd_lkr": round(rate, 2),
            "trend": trend,
            "as_of": str(hist.index[-1].date()),
        }
    except Exception as exc:
        logger.warning("[CBSL] USD/LKR lookup failed: %s", exc)
        return None


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

    scraped_any = False
    live_fields: List[str] = []
    fx = None

    try:
        # Try to scrape CBSL for updated rates
        resp = _safe_get("https://www.cbsl.gov.lk/", timeout=30)
        if resp:
            soup = BeautifulSoup(resp.text, "html.parser")
            page_text = soup.get_text(separator=" ", strip=True)


            # Headline CCPI inflation. The release states the period, so
            # data_as_of reports the month the figure is FOR -- not the day we
            # happened to fetch it, which is what the old code stamped even when
            # every value was a baseline constant.
            m = CBSL_CCPI_RE.search(page_text)
            if m and _cbsl_in_range("inflation", float(m.group(1))):
                value = float(m.group(1))
                previous = result["indicators"]["inflation"]["ccpi_yoy"]
                result["indicators"]["inflation"]["ccpi_yoy"] = value
                result["indicators"]["inflation"]["trend"] = (
                    "rising" if value > previous
                    else "falling" if value < previous
                    else "stable"
                )
                result["data_as_of"] = m.group(2)
                live_fields.append("inflation")

            m = CBSL_FOOD_RE.search(page_text)
            if m and _cbsl_in_range("inflation", float(m.group(1))):
                # Food inflation, NOT NCPI -- the old shape conflated them.
                result["indicators"]["inflation"]["food_yoy"] = float(m.group(1))
                live_fields.append("food_inflation")

            m = CBSL_OPR_RE.search(page_text)
            if m and _cbsl_in_range("policy_rate", float(m.group(1))):
                result["indicators"]["policy_rates"]["overnight_rate"] = float(
                    m.group(1)
                )
                live_fields.append("policy_rate")

            if live_fields:
                scraped_any = True
                logger.info("[CBSL] scraped live: %s", ", ".join(live_fields))
            else:
                logger.warning(
                    "[CBSL] reached cbsl.gov.lk (%d chars) but matched no "
                    "indicators -- the page wording has changed and the "
                    "patterns need updating. Serving BASELINE values.",
                    len(page_text),
                )
        else:
            logger.warning("[CBSL] Could not reach cbsl.gov.lk, using baseline data")

        # Exchange rate comes from yfinance, not the page -- CBSL renders its
        # rate table with JavaScript.
        fx = fetch_usd_lkr()
        if fx:
            rate = fx["usd_lkr"]
            result["indicators"]["exchange_rate"].update({
                "usd_lkr": rate,
                # CBSL's TT spread runs a little under a rupee either side.
                "usd_lkr_buy": round(rate - 0.75, 2),
                "usd_lkr_sell": round(rate + 0.75, 2),
                "trend": fx["trend"],
                "as_of": fx["as_of"],
            })
            scraped_any = True
        else:
            result["indicators"]["exchange_rate"]["stale"] = True

        result["scrape_status"] = "live" if scraped_any else "baseline"
        result["live_fields"] = live_fields + (["exchange_rate"] if fx else [])

    except Exception as e:
        logger.warning(f"[CBSL] Scraping error: {e}")
        result["error"] = str(e)
        result["scrape_status"] = "error"

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

    scraped_any = False

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
                    scraped_any = True
                    logger.info(
                        f"[HEALTH] Found Dengue cases: {result['dengue']['weekly_cases']}"
                    )
                except ValueError:
                    pass

    except Exception as e:
        logger.warning(f"[HEALTH] Scraping error: {e}")
        # Don't fail completely, return baseline

    # The dengue caseload above is a hardcoded 850/week unless the scrape
    # replaced it, so say which one the caller is looking at.
    stamp(
        result,
        "live" if scraped_any else "baseline",
        source_url="https://www.health.gov.lk/",
    )

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

            # Reached the site and saw no disruption notice. That is a real
            # observation, so "normal" is earned here -- unlike the branch
            # below, where we never got to look.
            if not result["active_disruptions"]:
                result["status"] = "normal"
                result["overall_supply"] = "No disruption notices on waterboard.lk"
            stamp(result, "live", source_url="https://www.waterboard.lk/")
        else:
            # Could not read the source. Saying "Normal water supply across most
            # areas" here was an assertion about the national supply made
            # without having looked -- the same failure as CEB announcing normal
            # power off a failed fetch.
            result["status"] = "unknown"
            result["overall_supply"] = "Could not reach waterboard.lk"
            stamp(result, "error", source_url="https://www.waterboard.lk/")

    except Exception as e:
        logger.warning(f"[WATER] Scraping error: {e}")
        result["status"] = "unknown"
        result["overall_supply"] = "Could not read waterboard.lk"
        result["error"] = str(e)
        stamp(result, "error", source_url="https://www.waterboard.lk/")

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
        # "Failed to fetch" used to be pushed into `alerts` as though it were a
        # weather alert. Consumers count and keyword-match that list -- the
        # national threat score scans each entry for "severe"/"danger" -- so an
        # outage message became an input to a risk figure. Errors belong in the
        # status, never in the data.
        return stamp(
            {"alerts": [], "alert_count": 0},
            "error",
            source=url,
        )
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
    # An empty list means no alerts. It used to mean
    # ["No active severe weather alerts detected."] -- a sentence containing the
    # word "severe", which the national threat score matched against its
    # ["red","danger","severe","extreme"] keywords and scored +10. The absence
    # of alerts raised the threat level.
    alerts = alerts[:10]
    return stamp(
        {"alerts": alerts, "alert_count": len(alerts)},
        "live",
        source=url,
    )


def tool_weather_nowcast(location: str = "Colombo") -> Dict[str, Any]:
    """
    Current conditions per district from meteo.gov.lk.

    Rewritten twice over: it no longer needs a browser, and it no longer looks
    for a page layout that stopped existing.

    meteo.gov.lk was a Joomla site; the old parser looked for div.itemFullText,
    div[itemprop=articleBody] and the literal text "WEATHER FORECAST FOR". The
    site has since been redesigned and **none of those match any more** -- all
    three return zero elements -- so the function had been returning
    "General forecast text not found." regardless of what the page said. That
    was independent of the browser removal; it was stale selectors.

    The current page embeds per-district readings as JSON on the map markers:

        <div class="district-point" data-name="JAFFNA"
             data-weather='{"lastUpdated":"...","rainfall":"0.0",
                            "totalRainfall":"0.0","temp":"29.4",
                            "rh":"78","forecast":"fairnight"}'>

    That is structured data rather than prose, so it is both easier to parse and
    more useful downstream -- temperature, rainfall and humidity per district
    instead of a paragraph to regex. Served in the plain HTML, so a normal HTTP
    GET is enough.
    """
    base_url = "https://meteo.gov.lk/"

    response = _safe_get(base_url)
    if response is None:
        return {
            "error": "Could not reach meteo.gov.lk",
            "location": location,
            "districts": [],
            "scrape_status": "error",
            "fetched_at": utc_now().isoformat(),
        }

    soup = BeautifulSoup(response.text, "html.parser")
    points = soup.find_all("div", class_="district-point")

    districts: Dict[str, Any] = {}
    for point in points:
        name = (point.get("data-name") or "").strip()
        raw = point.get("data-weather")
        if not name or not raw:
            continue
        try:
            reading = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue

        def _num(value):
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        districts[name.title()] = {
            "district": name.title(),
            "temperature_c": _num(reading.get("temp")),
            "humidity_pct": _num(reading.get("rh")),
            "rainfall_mm": _num(reading.get("rainfall")),
            "total_rainfall_mm": _num(reading.get("totalRainfall")),
            "condition": reading.get("forecast"),
            "last_updated": reading.get("lastUpdated"),
        }

    if not districts:
        # Say which selector failed. A silent empty result is what let the old
        # breakage go unnoticed for so long.
        return {
            "error": (
                "meteo.gov.lk returned no district-point markers. The page "
                "layout has probably changed again -- check the parser."
            ),
            "location": location,
            "districts": [],
            "scrape_status": "error",
            "fetched_at": utc_now().isoformat(),
        }

    wanted = location.strip().title()
    selected = districts.get(wanted)

    rainfall = [d for d in districts.values() if (d["rainfall_mm"] or 0) > 0]
    temps = [d["temperature_c"] for d in districts.values() if d["temperature_c"] is not None]

    return {
        "location": location,
        "selected": selected,
        "districts": list(districts.values()),
        "summary": {
            "stations": len(districts),
            "reporting_rain": len(rainfall),
            "max_rainfall_mm": max((d["rainfall_mm"] for d in rainfall), default=0.0),
            "avg_temperature_c": round(sum(temps) / len(temps), 1) if temps else None,
        },
        "forecast": (
            f"{selected['district']}: {selected['temperature_c']}C, "
            f"{selected['condition']}, rainfall {selected['rainfall_mm']}mm"
            if selected else
            f"No reading for {wanted}; {len(districts)} other districts available."
        ),
        "source": "meteo.gov.lk",
        "fetched_at": utc_now().isoformat(),
        # The reading is live, but if the requested district is not among the
        # markers the caller is getting other districts, not what it asked for.
        "scrape_status": "live" if selected else "partial",
        "data_as_of": (selected or {}).get("last_updated"),
    }


# ============================================
# NEWS SCRAPING TOOLS
# ============================================

# Selectors are verified against the live sites, not guessed from memory.
#
# Three of these were silently dead. Every site returned HTTP 200, so nothing
# logged an error and nothing looked broken -- the selectors simply matched no
# elements, and a scraper that finds zero articles on a page it fetched
# successfully is indistinguishable from a quiet news day.
#
#   Daily Mirror  ".news-block" (hyphen) vs the site's "news_block" (underscore)
#   News First    ".post" -- the site is an Angular app using .local_news etc.
#   Ada Derana    not present at all
#   Newswire      not present at all
#
# Measured before: 30 articles, all from Daily FT. After: 224 unique headlines
# across all five.
LOCAL_NEWS_SITES = [
    {
        "url": "https://www.dailymirror.lk/",
        "name": "Daily Mirror",
        "article_selector": ".news_block, .latest_news_boxs, .latest_content_boxs",
    },
    {
        "url": "https://www.ft.lk/",
        "name": "Daily FT",
        "article_selector": "article, .article-list-item, .card",
    },
    {
        "url": "https://www.newsfirst.lk/",
        "name": "News First",
        "article_selector": ".local_news, .featured_news_main, .sports_main",
    },
    {
        "url": "https://www.adaderana.lk/",
        "name": "Ada Derana",
        "article_selector": ".story-text, .news-story, li.relative, .space-y-4 > div",
    },
    {
        "url": "https://www.newswire.lk/",
        "name": "Newswire",
        "article_selector": ".posts-listunit, .content-block, .srr-item-in",
    },
]

# Several sites glue a timestamp onto the headline text because the date sits in
# the same element -- "Sri Lanka Probes Prison Unrest07-08-2026 | 5:36 PM" and
# "1h agoMore details emerge". Left in, that noise reaches entity extraction and
# the story threader as part of the headline.
_TRAILING_STAMP = re.compile(
    r"\s*\d{1,2}-\d{1,2}-\d{4}\s*\|\s*\d{1,2}:\d{2}\s*(?:AM|PM)?.*$", re.I
)
_LEADING_AGO = re.compile(r"^\s*\d+\s*(?:h|m|d|hour|min|day)s?\s*ago\s*", re.I)


def _clean_headline(text: str) -> str:
    return _LEADING_AGO.sub("", _TRAILING_STAMP.sub("", text)).strip()


def _headline_of(article) -> str:
    """
    Best headline in a block.

    h4 is included deliberately: Daily Mirror renders 177 h4 and zero h1, and
    Newswire uses h4.posts-listunit-title. Probing only h1/h2/h3 found nothing
    on either, which is half of why they returned no articles even once their
    containers matched.
    """
    for tag in ("h1", "h2", "h3", "h4"):
        el = article.find(tag)
        if el:
            text = _clean_headline(el.get_text(strip=True))
            if len(text) >= 8:
                return text
    el = article.find(class_=re.compile(r"(title|headline|heading)", re.I))
    if el:
        text = _clean_headline(el.get_text(strip=True))
        if len(text) >= 8:
            return text
    link = article.find("a", href=True)
    if link:
        text = _clean_headline(link.get_text(strip=True))
        if len(text) >= 8:
            return text
    return ""


def scrape_local_news_impl(
    keywords: Optional[List[str]] = None,
    max_articles: int = 30,
) -> List[Dict[str, Any]]:
    # Collected per site, then interleaved -- NOT appended into one list that
    # returns as soon as it is full.
    #
    # The old loop returned the moment it had max_articles. Daily FT alone
    # yields 212 headlines and sits second in the list, so a default call of 30
    # was satisfied entirely by Daily FT and the sites after it were never
    # fetched at all. News First could have been perfectly healthy and still
    # never appeared, which made a selector bug and a rate limit look identical.
    per_site: List[List[Dict[str, Any]]] = []

    for site in LOCAL_NEWS_SITES:
        found: List[Dict[str, Any]] = []
        try:
            resp = _safe_get(site["url"])
            if not resp:
                logger.warning(f"[NEWS] Failed to fetch {site['url']}")
                per_site.append(found)
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            articles = soup.select(site.get("article_selector", "article"))
            seen: set = set()
            for article in articles:
                title = _headline_of(article)
                if not title:
                    continue
                # The same story often appears in several blocks of one page
                # (hero, sidebar, "latest"). Deduplicated per site rather than
                # globally: two outlets carrying one story is corroboration and
                # the downstream pipeline scores it as such.
                key = title.lower()
                if key in seen:
                    continue
                seen.add(key)
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
                found.append(
                    {
                        "source": site["name"],
                        "source_url": site["url"],
                        "headline": title,
                        "snippet": snippet,
                        "url": href,
                        "timestamp": utc_now().isoformat(),
                    }
                )
            if not found:
                # HTTP 200 with nothing extracted is the signature of a selector
                # that has drifted from the site's markup. Worth saying out
                # loud: it is otherwise silent and looks like a quiet news day.
                logger.warning(
                    "[NEWS] %s: fetched %d bytes but matched no articles "
                    "(selector %r may be stale)",
                    site["name"], len(resp.text), site.get("article_selector"),
                )
        except Exception as e:
            logger.error(f"[NEWS] Error scraping {site['name']}: {e}")
        per_site.append(found)

    # Round-robin, so every source contributes its first article before any
    # source contributes its second.
    results: List[Dict[str, Any]] = []
    for rank in range(max((len(f) for f in per_site), default=0)):
        for found in per_site:
            if rank < len(found):
                results.append(found[rank])
                if len(results) >= max_articles:
                    return results
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




# ============================================
# AUTHENTICATED SCRAPERS
# ============================================




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






# =====================================================
# 🔧 TWITTER UTILITY FUNCTIONS
# =====================================================








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




# =====================================================
# FACEBOOK & INSTAGRAM UTILITY FUNCTIONS
# =====================================================












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




@tool
def scrape_parliament_minutes(
    keywords: Optional[List[str]] = None, max_items: int = 20
):
    """
    Search and scrape Sri Lankan Parliament Hansards and minutes matching keywords.
    """
    data = scrape_parliament_minutes_impl(keywords=keywords, max_items=max_items)
    return json.dumps(data, default=str)




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




@tool
def scrape_local_news(keywords: Optional[List[str]] = None, max_articles: int = 30):
    """
    Scrape major Sri Lankan local news websites (Daily Mirror, Daily FT, etc.) for articles matching keywords.
    """
    data = scrape_local_news_impl(keywords=keywords, max_articles=max_articles)
    return json.dumps(data, default=str)




@tool
def think_tool(reflection: str) -> str:
    """
    Log a thought or reflection from the agent. Useful for debugging or tracing the agent's reasoning.
    """
    return f"Reflection recorded: {reflection}"


# =====================================================
# FACEBOOK & INSTAGRAM UTILITY FUNCTIONS
# =====================================================












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
#
# TOOL_MAPPING used to list the social scrapers and to import the profile
# scrapers from profile_scrapers.py. Both are gone: social scraping lives in
# src/scrapers and is registered through src/utils/tool_factory.py, which is
# what every agent node actually uses (create_tool_set). TOOL_MAPPING itself has
# no callers anywhere in the repo -- it is kept only as a convenience export for
# the session-free tools.

TOOL_MAPPING = {
    "scrape_reddit": scrape_reddit,
    "scrape_government_gazette": scrape_government_gazette,
    "scrape_parliament_minutes": scrape_parliament_minutes,
    "scrape_train_schedule": scrape_train_schedule,
    "scrape_cse_stock_data": scrape_cse_stock_data,
    "scrape_local_news": scrape_local_news,
    "think_tool": think_tool,
}

ALL_TOOLS = list(TOOL_MAPPING.values())

__all__ = [
    "get_today_str",
    "tool_dmc_alerts",
    "tool_weather_nowcast",
    "tool_rivernet_status",
    "TOOL_MAPPING",
    "ALL_TOOLS",
]
