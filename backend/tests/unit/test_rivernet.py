"""
Tests for the rivernet.lk river-level scraper.

Two things are pinned here:

1. It works with NO browser. It used to drive Chromium against a Flutter SPA,
   waiting up to five minutes for it to render. That was the last reason the
   server image needed a browser, and removing the browser is what broke it.

2. Severity comes from the API's alertType field, NOT from alertColor. The
   colours are not a severity ramp -- live, 29 of 30 stations are Blue with
   alertType "normal" while the single Green station is the one at "alert". The
   intuitive reading (green = safe, blue = alert) inverts it and reports 29
   false flood alerts out of 30 stations. On a flood-warning dashboard that is
   the difference between a useful signal and noise nobody trusts.

Offline only -- responses are fixtures, so no test hits the live service.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _station(unit="I97", name="Kalu Ganga (Ratnapura)", region="ratnapura",
             level="5.440", before="5.500", colour="#44518C",
             alert_type="normal", change=-1, comms=True, max_level=12):
    return {
        "id": 75, "unitId": unit, "deviceKey": "abc", "type": "river_level",
        "region": region,
        "additional": {"offset": 0, "location": name, "maxLevel": max_level,
                       "coordinates": {"latitude": 6.7, "longitude": 80.1}},
        "latest": {
            "name": name, "alertColor": colour, "alertType": alert_type,
            "change": change, "communication": comms,
            "time": "2026-08-05 02:20:00", "datetime": "2026-08-05 02:20:00",
            "latestLevel": level, "latestLevelUnit": "m",
            "before30mLevel": before,
        },
        "alerts": [],
    }


def _payload(stations):
    return {"results": {"data": stations, "pagination": {}}, "debug": {}}


class _Resp:
    def __init__(self, data): self._d = data
    def raise_for_status(self): pass
    def json(self): return self._d


@pytest.fixture(autouse=True)
def _clear_cache():
    from src.utils import utils
    utils._rivernet_cache = {}
    utils._rivernet_cache_time = None
    yield
    utils._rivernet_cache = {}
    utils._rivernet_cache_time = None


def _run(stations):
    from src.utils import utils
    with patch.object(utils.requests, "get", return_value=_Resp(_payload(stations))):
        return utils.scrape_rivernet_impl(use_cache=False)


# --- no browser ------------------------------------------------------------

def test_works_without_playwright():
    """
    REGRESSION. This is why rivernet disappeared from the dashboard: the old
    implementation needed Chromium, which was removed with the browser.
    """
    from src.utils import utils
    result = _run([_station()])
    assert "error" not in result
    assert len(result["rivers"]) == 1


def test_implementation_uses_no_browser():
    """Structural: a reintroduced sync_playwright would silently re-break it."""
    import ast
    import inspect
    from src.utils import utils

    src = inspect.getsource(utils.scrape_rivernet_impl)
    tree = ast.parse(src.strip())
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "sync_playwright" not in names
    assert "PLAYWRIGHT_AVAILABLE" not in names


def test_calls_the_documented_endpoint():
    from src.utils import utils
    with patch.object(utils.requests, "get", return_value=_Resp(_payload([]))) as g:
        utils.scrape_rivernet_impl(use_cache=False)
    url = g.call_args[0][0]
    params = g.call_args.kwargs["params"]
    assert url == utils.RIVERNET_API_URL
    # camelCase is required: device_type and type both return HTTP 400.
    assert params == {"deviceType": "river_level"}


# --- THE severity inversion ------------------------------------------------

def test_blue_stations_are_normal_not_alerts():
    """
    REGRESSION. Blue (#44518C) is the normal state -- 29 of 30 live stations
    are blue with alertType "normal". Treating blue as an alert produced 29
    false flood warnings.
    """
    stations = [_station(unit=f"U{i}", colour="#44518C", alert_type="normal")
                for i in range(29)]
    result = _run(stations)
    assert all(r["severity"] == "normal" for r in result["rivers"])
    assert result["summary"]["alerts"] == 0


def test_green_station_at_alert_is_reported():
    """
    And the counterpart: the single live station at alertType "alert" is
    GREEN. Colour is not a severity ramp.
    """
    result = _run([_station(colour="#A9FF6E", alert_type="alert")])
    assert result["rivers"][0]["severity"] == "alert"
    assert result["summary"]["alerts"] == 1


@pytest.mark.parametrize("alert_type,expected", [
    ("normal", "normal"),
    ("alert", "alert"),
    ("warning", "warning"),
    ("danger", "critical"),
    ("critical", "critical"),
    ("something-new", "unknown"),
])
def test_severity_comes_from_alert_type(alert_type, expected):
    result = _run([_station(alert_type=alert_type)])
    assert result["rivers"][0]["severity"] == expected


# --- reading fidelity ------------------------------------------------------

def test_levels_and_trend_are_parsed():
    result = _run([_station(level="5.440", before="5.500", change=-1)])
    r = result["rivers"][0]
    assert r["level_m"] == 5.44
    assert r["previous_level_m"] == 5.5
    assert r["trend"] == "falling"


@pytest.mark.parametrize("change,trend", [(1, "rising"), (-1, "falling"),
                                          (0, "steady"), (None, "unknown")])
def test_trend_flags(change, trend):
    assert _run([_station(change=change)])["rivers"][0]["trend"] == trend


def test_offline_station_is_surfaced_not_silently_normal():
    """
    A gauge that stopped reporting during a flood is itself signal. Treating
    silence as "no alert" is the failure mode that matters here.
    """
    result = _run([_station(comms=False)])
    assert result["rivers"][0]["reporting"] is False
    assert result["summary"]["offline"] == 1
    assert any(a["severity"] == "no_data" for a in result["alerts"])


def test_location_filter():
    stations = [_station(unit="A", region="ratnapura"),
                _station(unit="B", region="kelaniya")]
    assert len(_run(stations)["rivers"]) == 2
    from src.utils import utils
    with patch.object(utils.requests, "get", return_value=_Resp(_payload(stations))):
        filtered = utils.scrape_rivernet_impl(locations=["kelaniya"], use_cache=False)
    assert [r["region"] for r in filtered["rivers"]] == ["kelaniya"]


# --- robustness ------------------------------------------------------------

def test_network_failure_returns_an_error_not_an_exception():
    from src.utils import utils
    with patch.object(utils.requests, "get", side_effect=OSError("no route")):
        result = utils.scrape_rivernet_impl(use_cache=False)
    assert "error" in result
    assert result["rivers"] == []


def test_malformed_station_is_skipped_not_fatal():
    good = _station(unit="OK")
    bad = {"unitId": "BAD", "latest": {"latestLevel": "not-a-number"}}
    result = _run([bad, good])
    assert len(result["rivers"]) == 1
    assert result["rivers"][0]["unit_id"] == "OK"


def test_empty_response_is_handled():
    result = _run([])
    assert result["rivers"] == []
    assert result["summary"]["total_stations"] == 0


def test_cache_prevents_a_second_request():
    from src.utils import utils
    with patch.object(utils.requests, "get", return_value=_Resp(_payload([_station()]))) as g:
        utils.scrape_rivernet_impl(use_cache=False)
        utils.scrape_rivernet_impl(use_cache=True)
    assert g.call_count == 1
