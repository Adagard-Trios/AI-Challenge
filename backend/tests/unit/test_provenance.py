"""
Every tool must say where its data came from.

Six of the ten public-source tools returned no provenance at all, which is how a
hardcoded 2.1 % inflation figure sat on the dashboard looking exactly like a
live one. Two went further and made affirmative claims off a failed fetch:

  - CEB announced "Normal power supply across the island" without having read
    anything, with load_shedding_active=False.
  - The water board tool reported "Normal water supply across most areas" on the
    same basis.

Those are the dangerous ones. A stale number is bad; asserting the grid is up
when you did not look is worse, and it is the case a business acts on.

These tests are static or offline by design -- the live sites are slow and
sometimes unreachable, and a test suite that depends on them is a test suite
people learn to ignore.
"""

import ast
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

UTILS = PROJECT_ROOT / "src" / "utils" / "utils.py"

# The public-source tools whose output reaches a dashboard card.
SOURCE_TOOLS = [
    "tool_rivernet_status",
    "tool_district_weather",
    "tool_weather_nowcast",
    "tool_dmc_alerts",
    "tool_ceb_power_status",
    "tool_fuel_prices",
    "tool_cbsl_indicators",
    "tool_health_alerts",
    "tool_commodity_prices",
    "tool_water_supply_alerts",
]


@pytest.fixture(scope="module")
def utils_tree():
    return ast.parse(UTILS.read_text(encoding="utf-8"))


def _function(tree, name):
    return next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == name),
        None,
    )


def _mentions_scrape_status(tree, fn, _depth=0) -> bool:
    """
    Either a literal "scrape_status" key or a stamp() call.

    Follows one level of delegation: tool_rivernet_status is a thin wrapper
    around scrape_rivernet_impl, and the stamp belongs in the implementation,
    not duplicated in the wrapper.
    """
    delegates = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Constant) and node.value == "scrape_status":
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "stamp":
                return True
            delegates.append(node.func.id)

    if _depth == 0:
        for name in delegates:
            target = _function(tree, name)
            if target is not None and _mentions_scrape_status(tree, target, 1):
                return True
    return False


# --- the vocabulary --------------------------------------------------------

def test_status_vocabulary_is_closed():
    """The UI switches on these; adding one must be deliberate."""
    from src.utils.utils import PROVENANCE_STATUSES

    assert PROVENANCE_STATUSES == {
        "live", "partial", "baseline", "unavailable", "error"
    }


def test_stamp_rejects_an_unknown_status():
    from src.utils.utils import stamp

    with pytest.raises(ValueError, match="unknown provenance status"):
        stamp({}, "probably_fine")


def test_stamp_separates_when_the_data_is_from_when_it_was_fetched():
    """
    CBSL's July figure retrieved in August is as_of "July 2026", fetched now.
    Conflating the two is what made stale numbers look current -- the old code
    stamped utc_now() even when every value was a baseline constant.
    """
    from src.utils.utils import stamp

    out = stamp({}, "live", as_of="July 2026")

    assert out["data_as_of"] == "July 2026"
    assert out["fetched_at"] != "July 2026"
    assert out["scrape_status"] == "live"


def test_stamp_does_not_clobber_an_existing_fetched_at():
    from src.utils.utils import stamp

    out = stamp({"fetched_at": "earlier"}, "live")
    assert out["fetched_at"] == "earlier"


# --- coverage --------------------------------------------------------------

@pytest.mark.parametrize("name", SOURCE_TOOLS)
def test_every_source_tool_reports_provenance(name, utils_tree):
    fn = _function(utils_tree, name)
    assert fn is not None, f"{name} no longer exists"
    assert _mentions_scrape_status(utils_tree, fn), (
        f"{name} returns no scrape_status, so a caller cannot tell live data "
        "from a hardcoded fallback"
    )


# --- the dangerous claims --------------------------------------------------

def test_no_tool_asserts_a_utility_is_healthy_without_evidence():
    """
    REGRESSION. Both of these sentences were emitted on the failure path.
    """
    code = "\n".join(
        line for line in UTILS.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("#")
    )

    for claim in (
        "Normal power supply across the island",
        "Normal water supply across most areas",
    ):
        assert claim not in code, (
            f"{claim!r} is asserted somewhere; a failed fetch must not report "
            "a healthy utility"
        )


def test_dmc_errors_do_not_masquerade_as_weather_alerts():
    """
    REGRESSION. "Failed to fetch alerts from DMC." and "No active severe
    weather alerts detected." were both pushed into the `alerts` list.
    Consumers count that list and keyword-match it -- the national threat score
    scans each entry for "severe"/"danger" -- so the second string scored +10,
    and the ABSENCE of alerts raised the national threat level.
    """
    code = "\n".join(
        line for line in UTILS.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("#")
    )

    assert "Failed to fetch alerts from DMC" not in code
    assert "No active severe weather alerts detected" not in code


def test_no_alerts_scores_lower_than_a_real_alert():
    """The behavioural version of the above."""
    from src.utils.utils import tool_calculate_national_threat as threat

    quiet = threat(river_data={"rivers": []}, dmc_alerts=[])
    severe = threat(
        river_data={"rivers": []},
        dmc_alerts=["Red warning: severe thunderstorms expected"],
    )

    assert quiet["breakdown"]["alert_contribution"] == 0
    assert severe["breakdown"]["alert_contribution"] > 0


# --- the threat score's river half ----------------------------------------

def test_threat_score_reads_the_field_rivernet_actually_emits():
    """
    REGRESSION. It read river["status"] with a danger/warning/rising
    vocabulary. fetch_rivernet_levels emits "severity"
    (normal/alert/warning/critical), "trend" and "reporting" -- never "status".
    So the 50-point river half of the national flood threat scored 0 on every
    cycle, over a live 30-station feed.
    """
    from src.utils.utils import tool_calculate_national_threat as threat

    rivers = {
        "rivers": [
            {"severity": "critical", "region": "kelaniya", "trend": "rising",
             "reporting": True},
            {"severity": "warning", "region": "ratnapura", "trend": "rising",
             "reporting": True},
            {"severity": "normal", "region": "galle", "trend": "rising",
             "reporting": True},
        ]
    }

    out = threat(river_data=rivers, dmc_alerts=[])

    assert out["breakdown"]["river_contribution"] > 0, (
        "rivers at critical and warning contributed nothing to the flood threat"
    )
    assert "kelaniya" in out["risk_summary"]["critical_districts"]
    assert "ratnapura" in out["risk_summary"]["high_risk_districts"]
    assert "galle" in out["risk_summary"]["medium_risk_districts"]


def test_the_old_status_vocabulary_scores_nothing():
    """A payload in the shape the old code expected must not silently work."""
    from src.utils.utils import tool_calculate_national_threat as threat

    out = threat(
        river_data={"rivers": [{"status": "danger", "region": "kelaniya"}]},
        dmc_alerts=[],
    )
    assert out["breakdown"]["river_contribution"] == 0


def test_a_silent_gauge_is_not_counted_as_rising():
    """A station that stopped reporting has no trend worth scoring."""
    from src.utils.utils import tool_calculate_national_threat as threat

    out = threat(
        river_data={"rivers": [
            {"severity": "normal", "region": "galle", "trend": "rising",
             "reporting": False},
        ]},
        dmc_alerts=[],
    )
    assert out["breakdown"]["river_contribution"] == 0
