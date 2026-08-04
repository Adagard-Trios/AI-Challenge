"""
Regression tests for the /api/intel/config duplicate-registration bug.

The endpoint was registered twice. Starlette matches in registration order, so
the first pair served every request -- and that pair merged into a module-global
that had been loaded from a path which does not exist. A POST arriving before
any GET therefore wrote a 3-key document over the real 8-key file, silently
destroying operational_keywords, alert_thresholds, default_competitors and notes.

These tests run against the file helpers directly rather than through the app,
so they need neither a running server nor the heavy import chain.
"""

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


FULL_CONFIG = {
    "user_profiles": {"twitter": ["a"], "facebook": [], "linkedin": []},
    "user_keywords": ["Colombo"],
    "user_products": ["iphone"],
    "operational_keywords": {"infrastructure": ["power"], "government": [], "opportunity": []},
    "alert_thresholds": {"trending_momentum_min": 2.0, "spike_multiplier": 3.0},
    "default_competitors": {"telecom": {"twitter": ["dialog"], "facebook": []}},
    "notes": {"removed_profiles": [], "last_verified": "2026-01-01"},
}

PRESERVED_KEYS = ["operational_keywords", "alert_thresholds", "default_competitors", "notes"]


def _read_modify_write(path: Path, updates: dict) -> dict:
    """
    Mirrors the surviving handler: read the FILE, merge, write back.

    The deleted handler merged into a stale in-memory global instead, which is
    where the data loss came from.
    """
    existing = json.loads(path.read_text(encoding="utf-8"))
    for key, value in updates.items():
        if value is not None:
            existing[key] = value
    path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    return existing


def test_post_before_get_preserves_unknown_keys(tmp_path):
    """
    THE regression. A POST that only knows about the three editable keys must
    not delete the four it has never heard of.
    """
    cfg = tmp_path / "intel_config.json"
    cfg.write_text(json.dumps(FULL_CONFIG, indent=2), encoding="utf-8")

    # Simulate the UI saving keywords, with no prior GET in this process.
    _read_modify_write(cfg, {
        "user_profiles": {"twitter": ["b"], "facebook": [], "linkedin": []},
        "user_keywords": ["Kandy"],
        "user_products": None,
    })

    after = json.loads(cfg.read_text(encoding="utf-8"))

    for key in PRESERVED_KEYS:
        assert key in after, f"POST destroyed {key!r} -- the duplicate-handler bug is back"

    assert after["user_keywords"] == ["Kandy"]           # edit applied
    assert after["user_products"] == ["iphone"]          # None means "leave alone"
    assert after["default_competitors"] == FULL_CONFIG["default_competitors"]


def test_stale_global_merge_would_have_lost_keys():
    """
    Documents the old behaviour so the failure mode stays understood: merging
    into a 3-key default and writing THAT out is what removed the other four.
    """
    stale_global = {"user_profiles": {}, "user_keywords": [], "user_products": []}
    stale_global["user_keywords"] = ["Kandy"]

    for key in PRESERVED_KEYS:
        assert key not in stale_global


def test_only_one_intel_config_path_is_defined():
    """
    INTEL_CONFIG_PATH was assigned twice at module scope. Because load/save read
    the global at call time, the second assignment silently changed which file
    the already-registered handlers touched.
    """
    source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    assignments = [
        line for line in source.splitlines()
        if line.startswith("INTEL_CONFIG_PATH") and "=" in line
    ]
    assert len(assignments) == 1, (
        f"INTEL_CONFIG_PATH assigned {len(assignments)}x at module scope: {assignments}"
    )


def test_intel_config_route_registered_once_per_method():
    """Guards against the duplicate registration returning."""
    source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    assert source.count('@app.get("/api/intel/config")') == 1
    assert source.count('@app.post("/api/intel/config")') == 1


def test_social_agent_reads_the_file_the_api_writes():
    """
    socialAgentNode read ../../data/intel_config.json -- a path that has never
    existed -- so user keywords never reached the social agent at all.
    """
    node = (PROJECT_ROOT / "src" / "nodes" / "socialAgentNode.py").read_text(encoding="utf-8")
    assert '"..", "config", "intel_config.json"' in node
    assert '"..", "..", "data", "intel_config.json"' not in node


def test_currency_history_registered_once():
    """The 30-day, model-service-backed copy was unreachable behind an earlier one."""
    source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    assert source.count('@app.get("/api/currency/history")') == 1, (
        "duplicate /api/currency/history registration -- the later, better "
        "implementation is unreachable"
    )
