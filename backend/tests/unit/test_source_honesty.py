"""
Sources that cannot be read must not produce numbers.

Each test here pins a defect that was live on the dashboard, not a hypothetical:

  * fuel served a hardcoded December 2025 table whenever CEYPETCO was
    unreachable. Measured against the site the day it came back, the baseline
    said petrol 92 = 294.00 and CEYPETCO said 414.00.
  * the stock panel showed US tickers labelled "CSE" in "LKR" with an 80%
    confidence badge, because it was trained against Yahoo Finance, which
    carries no Colombo Stock Exchange listing in any symbol format.
"""

import ast
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# --- fuel ---------------------------------------------------------------------

def test_a_stale_baseline_is_reported_as_unavailable_not_as_prices():
    from src.utils import utils

    assert utils._fuel_baseline_age_days("2025-12-01") > utils.FUEL_BASELINE_MAX_AGE_DAYS, (
        "the shipped baseline is inside the freshness window, so this test "
        "proves nothing; pick a date that is genuinely stale"
    )


def test_an_unparseable_revision_date_is_treated_as_stale():
    """
    None means "cannot tell how old this is", and an unknown age must not pass
    as fresh -- that is how a stale figure slips through a freshness check.
    """
    from src.utils import utils

    assert utils._fuel_baseline_age_days(None) is None
    assert utils._fuel_baseline_age_days("not a date") is None

    source = (PROJECT_ROOT / "src" / "utils" / "utils.py").read_text(encoding="utf-8")
    fn = next(
        n for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.FunctionDef) and n.name == "tool_fuel_prices"
    )
    body = ast.get_source_segment(source, fn) or ""
    assert "age_days is None or" in body, (
        "an unparseable revision date is not treated as stale, so a baseline "
        "with a broken date would be served as prices"
    )


def test_fuel_parses_the_formats_ceypetco_actually_publishes():
    from src.utils import utils

    # CEYPETCO writes "29-06-2026"; the baseline is written "2025-12-01".
    assert utils._fuel_baseline_age_days("29-06-2026") is not None
    assert utils._fuel_baseline_age_days("2025-12-01") is not None


# --- stock --------------------------------------------------------------------

def test_the_stock_endpoint_never_returns_a_predicted_price_without_a_model():
    """
    The panel may show real exchange prices. It may not imply a forecast: there
    is no per-company history endpoint on cse.lk, so nothing has been trained.
    """
    source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    fn = next(
        n for n in ast.walk(ast.parse(source))
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "get_stock_predictions"
    )
    body = ast.get_source_segment(source, fn) or ""

    start = body.find("prices_only")
    assert start != -1, "the prices-only branch is gone"
    branch = body[start:start + 1200]
    for forbidden in ("predicted_price", "expected_change", "confidence"):
        assert forbidden not in branch, (
            f"the prices-only branch emits {forbidden!r}, which reads as a forecast"
        )


def test_cse_quotes_say_whether_they_are_intraday_or_a_close():
    """
    cse.lk's tradeSummary is EMPTY outside market hours, so the fallback serves
    previousClose. A close presented as a live tick at midnight is a small lie
    that compounds.
    """
    from src.utils import utils

    source = (PROJECT_ROOT / "src" / "utils" / "utils.py").read_text(encoding="utf-8")
    assert '"as_of": "close"' in source and '"as_of": "intraday"' in source, (
        "quotes do not record which of the two they are"
    )
    assert utils.CSE_WATCHLIST, "no CSE symbols to fall back to"


def test_the_stock_model_is_not_pointed_at_yahoo_for_cse():
    """Yahoo has no CSE listing; that was the whole reason training failed."""
    source = (PROJECT_ROOT / "src" / "utils" / "utils.py").read_text(encoding="utf-8")
    assert "cse.lk" in source, "the CSE tool does not use the exchange's own API"


# --- serve_public -------------------------------------------------------------

def test_serve_public_refuses_when_auth_did_not_come_up():
    """
    The env checks in serve_public read strings. They cannot tell whether auth
    actually started, and the gap is not academic: Postgres restarted once,
    auth's connect timed out, main.py logged "continuing without it", and the
    process served every route unauthenticated while these same checks printed
    "All checks passed" -- because AUTH_ENFORCED really was 1.
    """
    source = (PROJECT_ROOT / "scripts" / "serve_public.py").read_text(encoding="utf-8")
    fn = next(
        n for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.FunctionDef) and n.name == "main"
    )
    body = ast.get_source_segment(source, fn) or ""

    assert "_AUTH_READY" in body, (
        "serve_public never checks whether the auth layer came up"
    )
    assert "REFUSING TO SERVE" in body, (
        "serve_public warns instead of refusing; a warning scrolls past"
    )
    # The check has to happen BEFORE the server starts, not after.
    assert body.index("_AUTH_READY") < body.index("uvicorn.run"), (
        "the auth check runs after uvicorn has already started serving"
    )
