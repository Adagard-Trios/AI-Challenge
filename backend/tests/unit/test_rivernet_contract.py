"""
The /api/rivernet contract, pinned on both sides.

Every consumer of this endpoint was reading keys the producer had never emitted:

    producer (fetch_rivernet_levels)   consumer (node, API error path, React)
    total_stations                     total_monitored
    status                             overall_status
    flood_alerts                       has_alerts
    rivers[].severity                  rivers[].status
    rivers[].level_m                   rivers[].water_level.{value,unit}
    alerts[].message                   alerts[].text

Nothing raised on the Python side -- .get() returned the default, so the
meteorological bulletin reported "0 rivers monitored, status: unknown" over a
live 30-station feed and never once produced a flood alert. On the React side
`river.status.toUpperCase()` threw, which is why the panel did not render.

These tests pin the producer's keys and check the consumers against them, so the
next rename has to break a test rather than a dashboard.
"""

import ast
import json
import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

REPO_ROOT = PROJECT_ROOT.parent
FRONTEND = REPO_ROOT / "frontend"

SUMMARY_KEYS = {
    "total_stations", "reporting", "offline", "rising",
    "alerts", "flood_alerts", "status", "regions",
}
RIVER_KEYS = {
    "name", "region", "level_m", "previous_level_m", "max_level_m", "trend",
    "severity", "alert_colour", "reading_time", "reporting", "coordinates",
    "unit_id",
}
ALERT_KEYS = {"river", "region", "severity", "level_m", "max_level_m", "trend", "message"}

# Keys the consumers used to read. None of these were ever produced.
PHANTOM_KEYS = ["total_monitored", "overall_status", "has_alerts", "status_breakdown"]


def _strip_ts_comments(src: str) -> str:
    """
    Comments in these files quote the very identifiers the tests forbid, so
    they have to go before matching. The (?<!:) guard keeps `https://` intact.
    """
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)  # block and {/* JSX */}
    return "\n".join(re.sub(r"(?<!:)//.*$", "", line) for line in src.splitlines())


def _strip_py_comments(src: str) -> str:
    return "\n".join(re.sub(r"#.*$", "", line) for line in src.splitlines())


def _sample():
    """One station of each kind, in the producer's exact shape."""
    return {
        "rivers": [
            {"name": "Kelani at Nagalagam", "region": "kelaniya", "level_m": 1.7,
             "previous_level_m": 1.6, "max_level_m": 12, "trend": "rising",
             "severity": "warning", "alert_colour": "orange",
             "reading_time": "2026-08-05 07:20:00", "reporting": True,
             "coordinates": None, "unit_id": "u1"},
            {"name": "Kalu at Ratnapura", "region": "ratnapura", "level_m": None,
             "previous_level_m": None, "max_level_m": 12, "trend": "unknown",
             "severity": "unknown", "alert_colour": None,
             "reading_time": None, "reporting": False,
             "coordinates": None, "unit_id": "u2"},
        ],
        "alerts": [
            {"river": "Kelani at Nagalagam", "region": "kelaniya",
             "severity": "warning", "level_m": 1.7, "max_level_m": 12,
             "trend": "rising", "message": "Kelani at Nagalagam: 1.7m (rising)"},
            {"river": "Kalu at Ratnapura", "region": "ratnapura",
             "severity": "no_data", "level_m": None, "max_level_m": 12,
             "trend": "unknown", "message": "Kalu at Ratnapura: station not reporting"},
        ],
    }


# --- producer --------------------------------------------------------------

def test_summary_keys_are_stable():
    """
    Pins the contract. If a key is renamed here, every consumer test below
    fails too, which is the point.
    """
    src = (PROJECT_ROOT / "src" / "utils" / "utils.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    fn = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == "_summarise_rivernet"),
        None,
    )
    assert fn is not None, "_summarise_rivernet is gone"

    found = None
    for node in ast.walk(fn):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            found = {
                k.value for k in node.value.keys if isinstance(k, ast.Constant)
            }
            break

    assert found is not None, "could not locate the rivernet summary literal"
    assert found == SUMMARY_KEYS, (
        f"summary keys changed: added {found - SUMMARY_KEYS}, "
        f"removed {SUMMARY_KEYS - found}"
    )


def test_flood_alerts_excludes_stations_that_merely_stopped_reporting():
    """
    THE subtlety. `alerts` carries both real warning levels and silent gauges.
    Counting them together would raise a flood warning off offline hardware --
    on the day this was written, all 4 alerts were offline stations and no
    river was rising.
    """
    from src.utils.utils import _summarise_rivernet

    summary = _summarise_rivernet(_sample())

    assert summary["alerts"] == 2, "both entries belong in the alerts list"
    assert summary["flood_alerts"] == 1, (
        "only the warning-level station is a flood signal"
    )
    assert summary["offline"] == 1
    assert summary["status"] == "alert"


def test_status_is_normal_when_only_gauges_are_offline():
    from src.utils.utils import _summarise_rivernet

    data = _sample()
    data["rivers"][0]["severity"] = "normal"
    data["rivers"][0]["trend"] = "steady"
    data["alerts"] = [a for a in data["alerts"] if a["severity"] == "no_data"]

    summary = _summarise_rivernet(data)

    assert summary["flood_alerts"] == 0
    assert summary["status"] == "normal", (
        "offline stations alone must not put the network in an alert state"
    )


# --- consumers -------------------------------------------------------------

def test_meteorological_node_reads_real_keys():
    src = (PROJECT_ROOT / "src" / "nodes" / "meteorologicalAgentNode.py").read_text(
        encoding="utf-8"
    )
    code = "\n".join(
        line for line in src.splitlines() if not line.strip().startswith("#")
    )
    for phantom in PHANTOM_KEYS:
        assert f'"{phantom}"' not in code, (
            f"meteorologicalAgentNode still reads {phantom}, which the API "
            "never sends"
        )
    assert 'river_summary.get("flood_alerts"' in code
    assert 'river_summary.get("total_stations"' in code


def test_api_error_path_matches_the_success_shape():
    """
    The /api/rivernet exception handler returned a summary with entirely
    different keys, so a client was broken on exactly one of the two paths.
    """
    src = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    handler = src[src.index("def get_rivernet_status"):][:1600]
    code = "\n".join(
        line for line in handler.splitlines() if not line.strip().startswith("#")
    )

    for phantom in PHANTOM_KEYS:
        assert phantom not in code, f"error path still emits {phantom}"
    for key in ("total_stations", "flood_alerts", "status"):
        assert key in code, f"error path omits {key}"


@pytest.mark.parametrize(
    "relpath",
    ["app/hooks/use-roger-data.ts", "app/components/dashboard/RiverNetStatus.tsx"],
)
def test_frontend_types_match_the_api(relpath):
    path = FRONTEND / relpath
    if not path.exists():
        pytest.skip(f"{relpath} not present")

    code = _strip_ts_comments(path.read_text(encoding="utf-8"))

    for phantom in PHANTOM_KEYS:
        assert phantom not in code, (
            f"{relpath} still references {phantom}; the API does not send it"
        )
    assert "water_level" not in code, (
        f"{relpath} still reads water_level.{{value,unit}}; the field is level_m"
    )
    assert "alert.text" not in code, (
        f"{relpath} still reads alerts[].text; the field is message"
    )


def test_react_component_does_not_call_toupper_on_a_missing_field():
    """
    REGRESSION. `river.status.toUpperCase()` threw a TypeError on the first
    station, so the whole flood panel failed to render -- the visible symptom
    of every mismatch above.
    """
    path = FRONTEND / "app/components/dashboard/RiverNetStatus.tsx"
    if not path.exists():
        pytest.skip("component not present")

    code = _strip_ts_comments(path.read_text(encoding="utf-8"))
    assert "river.status" not in code, "river.status does not exist on the payload"
    assert "location_key" not in code, "location_key does not exist on the payload"
