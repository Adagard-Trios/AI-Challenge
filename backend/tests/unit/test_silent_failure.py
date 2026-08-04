"""
Guards against silent failure returning.

This is the pattern that made every other defect in this codebase hard to find:
code that catches an exception, discards it, and returns a shape indistinguishable
from success. A Facebook scraper truncated every long post for months; two agents
discarded every LLM insight they paid for; a rivernet scraper ran perfectly and had
its output thrown away. In each case the logs showed a tick and the API returned 200.

These tests assert the swallowing itself is gone, not just its symptoms.
"""

import ast
import io
import json
import sys
import tokenize
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SRC = PROJECT_ROOT / "src"


def _python_files():
    for path in SRC.rglob("*.py"):
        if "__pycache__" not in path.parts:
            yield path


# --- structural ------------------------------------------------------------

def test_no_bare_except_anywhere():
    """
    A bare `except:` also catches KeyboardInterrupt and SystemExit, so it makes
    a process unkillable mid-scrape as well as hiding real errors.
    """
    offenders = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                offenders.append(f"{path.relative_to(SRC)}:{node.lineno}")
    assert not offenders, (
        "bare `except:` found (catches KeyboardInterrupt, hides everything): "
        + ", ".join(offenders)
    )


def test_no_swallowed_errors_in_the_result_producing_layer():
    """
    `except ...: pass` is only dangerous where it makes a FAILURE look like an
    EMPTY RESULT. That is the node and tool layer: whatever they return becomes
    the agent's view of the world, so a swallowed error there is a silent lie.

    Deliberately scoped rather than a blanket ban. The remaining sites in
    src/scrapers and src/utils were inspected and are genuine best-effort
    cleanup -- Playwright request routing, os.chmod (a no-op on Windows),
    optional float parsing with a documented fallback. Banning those outright
    would produce suppressions rather than safety, and the scrapers layer
    already reports failure explicitly through ScrapeResult.status.
    """
    watched = [SRC / "nodes", SRC / "utils" / "tool_factory.py"]

    offenders = []
    for target in watched:
        files = target.rglob("*.py") if target.is_dir() else [target]
        for path in files:
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                body = [s for s in node.body if not (isinstance(s, ast.Expr)
                                                     and isinstance(s.value, ast.Constant))]
                if len(body) == 1 and isinstance(body[0], ast.Pass):
                    offenders.append(f"{path.relative_to(SRC)}:{node.lineno}")

    assert not offenders, (
        f"{len(offenders)} handler(s) in the result-producing layer swallow an "
        "exception with only `pass`, so a failure is indistinguishable from an "
        "empty result:\n    " + "\n    ".join(offenders)
    )


def test_categorisers_report_unparseable_results():
    """
    The categorisation loops used `except Exception: continue`, so a scraper
    changing its output shape looked exactly like a quiet news day -- the node
    printed "Categorized: 0, 0, 0" and returned successfully.
    """
    for name in ("socialAgentNode.py", "politicalAgentNode.py",
                 "economicalAgentNode.py", "meteorologicalAgentNode.py"):
        src = (SRC / "nodes" / name).read_text(encoding="utf-8")
        assert "Unparseable result skipped" in src, (
            f"{name} still drops parse failures silently"
        )


# --- behavioural -----------------------------------------------------------

def test_product_reviews_reports_total_failure(monkeypatch):
    """
    REGRESSION. Two bare `except: pass` meant that when BOTH platforms threw,
    the tool still returned a well-formed
    {"total_reviews": 0, "reviews": []} -- indistinguishable from "this product
    genuinely has no reviews". This is the Intelligence agent's only Module-2B
    source, so it had no way to know its input was missing.
    """
    from src.utils.tool_factory import create_tool_set

    ts = create_tool_set()

    class Exploding:
        def invoke(self, *a, **k):
            raise RuntimeError("scraper down")

    monkeypatch.setattr(ts, "_tools", {**ts._tools,
                                       "scrape_reddit": Exploding(),
                                       "scrape_twitter": Exploding()})

    out = json.loads(ts.get("scrape_product_reviews").invoke(
        {"product_keyword": "widget", "platforms": ["reddit", "twitter"]}
    ))

    assert out["status"] == "error", (
        "every platform failed but the tool reported success"
    )
    assert {f["platform"] for f in out["platforms_failed"]} == {"reddit", "twitter"}
    assert out["total_reviews"] == 0


def test_product_reviews_partial_failure_is_still_ok(monkeypatch):
    """One platform down is a degraded result, not a failed one."""
    from src.utils.tool_factory import create_tool_set

    ts = create_tool_set()

    class Exploding:
        def invoke(self, *a, **k):
            raise RuntimeError("down")

    class Fine:
        def invoke(self, *a, **k):
            return json.dumps({"results": [{"text": "great", "url": "u"}]})

    monkeypatch.setattr(ts, "_tools", {**ts._tools,
                                       "scrape_reddit": Exploding(),
                                       "scrape_twitter": Fine()})

    out = json.loads(ts.get("scrape_product_reviews").invoke(
        {"product_keyword": "widget", "platforms": ["reddit", "twitter"]}
    ))

    assert out["status"] == "ok"
    assert [f["platform"] for f in out["platforms_failed"]] == ["reddit"]


def test_corrupt_intel_config_is_announced(tmp_path, capsys, monkeypatch):
    """
    REGRESSION. A malformed config was swallowed and became an empty config, so
    the agent printed the same "no targets configured" message as a genuinely
    empty one -- the user's settings appeared ignored with no error anywhere.
    """
    from src.nodes import socialAgentNode

    bad = tmp_path / "intel_config.json"
    bad.write_text("{not json", encoding="utf-8")

    real_join = socialAgentNode.os.path.join
    monkeypatch.setattr(socialAgentNode.os.path, "join",
                        lambda *a: str(bad) if "intel_config.json" in a[-1] else real_join(*a))

    cfg = socialAgentNode.load_intel_config()

    assert cfg["user_keywords"] == []          # still degrades safely
    out = capsys.readouterr().out
    assert "could not be read" in out, "corrupt config was swallowed silently"
    assert "will NOT be collected" in out


def test_missing_config_is_not_reported_as_corrupt(tmp_path, capsys, monkeypatch):
    """Never-configured must stay distinct from configured-but-broken."""
    from src.nodes import socialAgentNode

    missing = tmp_path / "nope.json"
    real_join = socialAgentNode.os.path.join
    monkeypatch.setattr(socialAgentNode.os.path, "join",
                        lambda *a: str(missing) if "intel_config.json" in a[-1] else real_join(*a))

    socialAgentNode.load_intel_config()
    assert "could not be read" not in capsys.readouterr().out
