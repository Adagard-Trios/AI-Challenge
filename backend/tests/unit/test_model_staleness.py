"""
Predictions must carry the date their model last saw data.

The stock model was trained on a window ending 2025-09-19 and is being asked to
predict Colombo Stock Exchange prices in August 2026 -- a ten month gap,
rendered with exactly the same confidence as a live quote. That is not quite
"wrong": it is unfalsifiable. Without the cutoff, a reader has no way to weigh
the number, and no way to know the model has never seen anything that happened
since.

Retraining is separate work. This is about making the gap visible so that
decision can be made deliberately.
"""

import ast
import json
import sys
from datetime import date
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

REPO_ROOT = PROJECT_ROOT.parent
CARDS = REPO_ROOT / "frontend" / "app" / "components" / "dashboard"


# --- the helper ------------------------------------------------------------

def test_a_model_within_its_threshold_is_fresh(monkeypatch):
    from src import model_metadata

    monkeypatch.setattr(
        model_metadata, "read_training_metadata",
        lambda m: {"training_cutoff": "2026-08-01"},
    )
    out = model_metadata.staleness("stock", today=date(2026, 8, 5))

    assert out["staleness"] == "fresh"
    assert out["age_days"] == 4
    assert "2026-08-01" in out["message"]


def test_a_model_past_its_threshold_is_stale(monkeypatch):
    """The real case: 320 days against a 30-day threshold for a market model."""
    from src import model_metadata

    monkeypatch.setattr(
        model_metadata, "read_training_metadata",
        lambda m: {"training_cutoff": "2025-09-19"},
    )
    out = model_metadata.staleness("stock", today=date(2026, 8, 5))

    assert out["staleness"] == "stale"
    assert out["age_days"] == 320
    assert "11 months out of date" in out["message"]


def test_thresholds_differ_by_what_the_model_predicts(monkeypatch):
    """
    A daily market model goes stale far sooner than a weather climatology.
    Ninety days is nothing for the latter and a disaster for the former.
    """
    from src import model_metadata

    monkeypatch.setattr(
        model_metadata, "read_training_metadata",
        lambda m: {"training_cutoff": "2026-05-01"},
    )
    today = date(2026, 8, 5)  # 96 days later

    assert model_metadata.staleness("stock", today=today)["staleness"] == "stale"
    assert model_metadata.staleness("anomaly", today=today)["staleness"] == "fresh"


def test_a_model_with_no_sidecar_reports_unknown_not_fresh():
    """
    THE important default. Unknown provenance must look suspicious, never
    authoritative -- the same rule as scrape_status. Defaulting to "fresh"
    would hide exactly the models nobody has checked.
    """
    from src import model_metadata

    out = model_metadata.staleness("currency")

    assert out["staleness"] == "unknown"
    assert out["training_cutoff"] is None
    assert "unknown" in out["message"].lower()


def test_a_corrupt_sidecar_is_distinguishable_from_a_missing_one(tmp_path, monkeypatch):
    from src import model_metadata

    bad = tmp_path / "training_metadata.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(model_metadata, "sidecar_path", lambda m: bad)

    out = model_metadata.staleness("stock")

    assert out["staleness"] == "unknown"
    assert "sidecar_error" in out, (
        "a corrupt sidecar is a deployment problem, not an absent one"
    )


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2025-09-19", date(2025, 9, 19)),
        ("2025/09/19", date(2025, 9, 19)),
        ("2025-09-19T10:00:00", date(2025, 9, 19)),
        ("not a date", None),
        (None, None),
        ("", None),
    ],
)
def test_date_parsing_is_forgiving_but_not_credulous(value, expected):
    from src.model_metadata import _parse_date

    assert _parse_date(value) == expected


def test_annotate_attaches_training_to_a_remote_payload():
    from src import model_metadata

    out = model_metadata.annotate({"status": "success"}, "stock")

    assert out["status"] == "success"
    assert out["training"]["staleness"] in ("fresh", "stale", "unknown")


# --- the real artifact -----------------------------------------------------

def test_the_stock_sidecar_matches_its_training_data():
    """
    The cutoff must be derived from the data, not asserted. stock_prices.csv
    is in the repo, so this is checkable.
    """
    import csv

    sidecar = (
        REPO_ROOT / "models" / "stock-price-prediction" / "artifacts" / "models"
        / "training_metadata.json"
    )
    csv_path = (
        REPO_ROOT / "models" / "stock-price-prediction" / "experiments"
        / "stock_prices.csv"
    )
    if not (sidecar.exists() and csv_path.exists()):
        pytest.skip("stock model artifacts not present")

    meta = json.loads(sidecar.read_text(encoding="utf-8"))

    with csv_path.open(encoding="utf-8") as fh:
        dates = sorted(r["Date"] for r in csv.DictReader(fh) if r.get("Date"))

    assert meta["training_cutoff"] == dates[-1], (
        f"sidecar says {meta['training_cutoff']}, data ends {dates[-1]}"
    )


def test_the_stock_model_is_currently_flagged_stale():
    """
    Not a hypothetical. If this ever fails, someone has retrained -- delete it.
    """
    from src import model_metadata

    out = model_metadata.staleness("stock")
    assert out["staleness"] == "stale", (
        "the stock model was trained to 2025-09-19; if that changed, update "
        "this test"
    )


# --- wiring ----------------------------------------------------------------

@pytest.mark.parametrize(
    "endpoint",
    ["get_stock_predictions", "get_currency_prediction", "get_weather_predictions"],
)
def test_prediction_endpoints_report_training(endpoint):
    """
    Staleness rides along with the predictions the card already fetches, so no
    second request is needed to know whether to trust them.
    """
    tree = ast.parse((PROJECT_ROOT / "main.py").read_text(encoding="utf-8"))

    fn = next(
        (n for n in ast.walk(tree)
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
         and n.name == endpoint),
        None,
    )
    assert fn is not None, f"{endpoint} is gone"

    mentions = any(
        isinstance(node, ast.Attribute)
        and node.attr in ("staleness", "annotate")
        for node in ast.walk(fn)
    )
    assert mentions, f"{endpoint} does not report its model's training cutoff"


@pytest.mark.skipif(not CARDS.exists(), reason="frontend not present")
@pytest.mark.parametrize(
    "card",
    ["StockPredictions.tsx", "CurrencyPrediction.tsx", "WeatherPredictions.tsx"],
)
def test_prediction_cards_render_staleness(card):
    src = (CARDS / card).read_text(encoding="utf-8")
    assert "ModelStaleness" in src, (
        f"{card} shows predictions without saying how old the model is"
    )


@pytest.mark.skipif(not CARDS.exists(), reason="frontend not present")
def test_fresh_models_render_nothing():
    """A warning that always shows is a warning nobody reads."""
    src = (CARDS / "ModelStaleness.tsx").read_text(encoding="utf-8")
    assert 'state === "fresh"' in src and "return null" in src


# --- the invented currency forecast ---------------------------------------

def test_currency_fallback_does_not_invent_a_forecast():
    """
    REGRESSION. With no model loaded, the endpoint drew a number from
    np.random.normal() around a hardcoded 298.0 and returned it as
    {"status": "success"} with a direction and a volatility class -- shaped
    exactly like real model output. The rate has since moved to ~335, so even
    the anchor was 12% wrong.
    """
    src = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    code = "\n".join(
        line for line in src.splitlines() if not line.strip().startswith("#")
    )

    assert "np.random.normal" not in code, (
        "a random number is being returned as a currency prediction"
    )
    assert "current_rate = 298.0" not in code
