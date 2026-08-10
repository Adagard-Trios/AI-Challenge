"""
Tests for tool_weather_nowcast (meteo.gov.lk).

Two independent breakages, fixed together:

1. It drove Chromium. Unnecessary -- meteo.gov.lk is server-rendered and a
   plain GET returns the full page.
2. Its selectors were stale. The site was redesigned away from Joomla, so
   div.itemFullText, div[itemprop=articleBody] and the literal string
   "WEATHER FORECAST FOR" all match ZERO elements now. The function had been
   returning "General forecast text not found." for every request, and doing so
   without erroring -- which is why nobody noticed.

Fixtures mirror the live markup. No test touches the network.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Shape of the real page: readings live in a data-weather JSON attribute on the
# map markers, not in prose.
PAGE = """
<html><body>
  <div class="main-content">
    <div class="district-point" data-name="COLOMBO"
         data-weather='{"lastUpdated":"2026-08-04 2030","rainfall":"0.0","totalRainfall":"0.0","temp":"28.2","rh":"80","forecast":"cloudy"}'
         style="left:100px"></div>
    <div class="district-point" data-name="RATNAPURA"
         data-weather='{"lastUpdated":"2026-08-04 2030","rainfall":"1.4","totalRainfall":"3.2","temp":"25.1","rh":"91","forecast":"rain"}'
         style="left:120px"></div>
    <div class="district-point" data-name="JAFFNA"
         data-weather='{"lastUpdated":"2026-08-04 2030","rainfall":"0.0","totalRainfall":"0.0","temp":"29.4","rh":"78","forecast":"fairnight"}'
         style="left:80px"></div>
  </div>
</body></html>
"""

# The old layout: what the stale selectors were written against.
LEGACY_PAGE = """
<html><body>
  <div class="itemFullText">WEATHER FORECAST FOR 04 AUGUST, showers expected.</div>
</body></html>
"""


class _Resp:
    def __init__(self, text): self.text = text
    def raise_for_status(self): pass


def _run(html=PAGE, location="Colombo"):
    from src.utils import utils
    with patch.object(utils, "_safe_get", return_value=_Resp(html)):
        return utils.tool_weather_nowcast(location)


# --- no browser ------------------------------------------------------------

def test_works_without_playwright():
    result = _run()
    assert "error" not in result
    assert result["summary"]["stations"] == 3


def test_implementation_launches_no_browser():
    """Structural: a reintroduced sync_playwright would re-break the image."""
    import ast
    import inspect
    from src.utils import utils

    tree = ast.parse(inspect.getsource(utils.tool_weather_nowcast).strip())
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "sync_playwright" not in names
    assert "PLAYWRIGHT_AVAILABLE" not in names


# --- the stale-selector breakage -------------------------------------------

def test_returns_real_readings_not_the_not_found_placeholder():
    """
    REGRESSION. The old parser returned "General forecast text not found." on
    every request because its selectors no longer matched anything.
    """
    result = _run()
    assert "not found" not in result["forecast"].lower()
    assert result["selected"]["temperature_c"] == 28.2


def test_legacy_layout_now_reports_an_explicit_error():
    """
    Given the OLD markup, there are no district-point markers -- so the
    function must say the layout changed, not return an empty success. A silent
    empty result is exactly what let the previous breakage go unnoticed.
    """
    result = _run(LEGACY_PAGE)
    assert "error" in result
    assert "layout" in result["error"].lower()


# --- parsing ---------------------------------------------------------------

def test_all_districts_are_parsed():
    result = _run()
    names = {d["district"] for d in result["districts"]}
    assert names == {"Colombo", "Ratnapura", "Jaffna"}


def test_numeric_fields_are_numbers_not_strings():
    """The API sends numbers as strings; downstream does arithmetic on them."""
    d = _run()["districts"][0]
    for field in ("temperature_c", "humidity_pct", "rainfall_mm", "total_rainfall_mm"):
        assert isinstance(d[field], float), f"{field} is {type(d[field])}"


def test_summary_aggregates():
    s = _run()["summary"]
    assert s["stations"] == 3
    assert s["reporting_rain"] == 1          # only Ratnapura
    assert s["max_rainfall_mm"] == 1.4
    assert s["avg_temperature_c"] == pytest.approx(27.6, abs=0.1)


def test_location_selection_is_case_insensitive():
    for given in ("colombo", "COLOMBO", "Colombo"):
        assert _run(location=given)["selected"]["district"] == "Colombo"


def test_unknown_location_still_returns_other_districts():
    """A bad location must not throw away the data we did fetch."""
    result = _run(location="Atlantis")
    assert result["selected"] is None
    assert len(result["districts"]) == 3
    assert "other districts available" in result["forecast"]


# --- robustness ------------------------------------------------------------

def test_network_failure_is_an_error_not_an_exception():
    from src.utils import utils
    with patch.object(utils, "_safe_get", return_value=None):
        result = utils.tool_weather_nowcast("Colombo")
    assert "error" in result


def test_malformed_marker_is_skipped_not_fatal():
    html = PAGE.replace(
        '''data-weather='{"lastUpdated":"2026-08-04 2030","rainfall":"0.0","totalRainfall":"0.0","temp":"29.4","rh":"78","forecast":"fairnight"}\'''',
        """data-weather='{not json'""",
    )
    result = _run(html)
    assert result["summary"]["stations"] == 2      # the other two survive


def test_non_numeric_reading_becomes_none_not_a_crash():
    html = PAGE.replace('"temp":"28.2"', '"temp":"--"')
    result = _run(html)
    colombo = next(d for d in result["districts"] if d["district"] == "Colombo")
    assert colombo["temperature_c"] is None
