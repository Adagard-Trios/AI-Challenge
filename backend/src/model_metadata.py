"""
src/model_metadata.py
How stale is a model?

Every prediction card served numbers with no indication of when the model behind
them last saw data. The stock model's training set ends 2025-09-19 and it is
being asked to predict Colombo Stock Exchange prices in August 2026 -- a ten
month gap, presented with the same confidence as a live quote.

A prediction from a model trained on a stale window is not wrong, exactly. It is
unfalsifiable: the reader has no way to weigh it. Saying "trained to
2025-09-19" costs nothing and restores that judgement.

Retraining is deliberately not solved here. The point of this module is that the
gap becomes visible, so the decision to retrain is an informed one.

The cutoff comes from a `training_metadata.json` sidecar written next to a
model's artifacts. Write one at the end of training:

    {
      "training_cutoff": "2025-09-19",     # last observation in the training set
      "trained_at": "2025-09-21T10:00:00", # optional, when training ran
      "rows": 4387,                        # optional
      "notes": "CSE daily closes, 10 symbols"
    }

A model with no sidecar reports cutoff None and staleness "unknown", which the
UI renders as a warning. Unknown provenance is a problem to surface, not a
detail to default away -- the same rule as scrape_status.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("model_metadata")

SIDECAR_NAME = "training_metadata.json"

# A daily-updating market model is stale far sooner than a weather climatology.
# These are the thresholds at which the UI starts warning, in days.
STALENESS_THRESHOLDS = {
    "stock": 30,
    "currency": 30,
    "weather": 90,
    "anomaly": 180,
}
DEFAULT_THRESHOLD_DAYS = 90

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Where each model's artifacts live, relative to the repo root.
ARTIFACT_DIRS = {
    "stock": "models/stock-price-prediction/artifacts/models",
    "currency": "models/currency-volatility-prediction/artifacts/models",
    "weather": "models/weather-prediction/artifacts/models",
    "anomaly": "models/anomaly-detection/artifacts/model_trainer",
}


def _parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[: len(fmt) + 2], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def sidecar_path(model: str) -> Optional[Path]:
    rel = ARTIFACT_DIRS.get(model)
    return (REPO_ROOT / rel / SIDECAR_NAME) if rel else None


def read_training_metadata(model: str) -> Dict[str, Any]:
    """Raw sidecar contents, or {} when absent or unreadable."""
    path = sidecar_path(model)
    if not path or not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        # Unreadable is not the same as absent, and the caller should be able to
        # tell -- a corrupt sidecar is a deployment problem, not a missing one.
        logger.warning("[model_metadata] %s sidecar unreadable: %s", model, exc)
        return {"error": str(exc)}


def staleness(model: str, *, today: Optional[date] = None) -> Dict[str, Any]:
    """
    Describe how far the model's training window is behind today.

    Returns:
        training_cutoff  last observation the model was trained on, or None
        age_days         days since that cutoff, or None
        staleness        fresh | stale | unknown
        threshold_days   the age at which this model is considered stale
        message          one line fit to render
    """
    today = today or date.today()
    meta = read_training_metadata(model)
    threshold = STALENESS_THRESHOLDS.get(model, DEFAULT_THRESHOLD_DAYS)

    cutoff = _parse_date(meta.get("training_cutoff"))
    if cutoff is None:
        return {
            "training_cutoff": None,
            "age_days": None,
            "staleness": "unknown",
            "threshold_days": threshold,
            "message": (
                "Training date unknown -- no training_metadata.json beside this "
                "model's artifacts. Treat its output as unverified."
            ),
            **({"sidecar_error": meta["error"]} if "error" in meta else {}),
        }

    age = (today - cutoff).days
    stale = age > threshold

    if stale:
        months = age / 30.44
        gap = f"{months:.0f} months" if months >= 1.5 else f"{age} days"
        message = (
            f"Model trained to {cutoff.isoformat()} -- {gap} out of date. "
            "Predictions do not reflect anything since then."
        )
    else:
        message = f"Model trained to {cutoff.isoformat()}."

    return {
        "training_cutoff": cutoff.isoformat(),
        "age_days": age,
        "staleness": "stale" if stale else "fresh",
        "threshold_days": threshold,
        "message": message,
        **{k: meta[k] for k in ("trained_at", "rows", "notes") if k in meta},
    }


def annotate(payload: Dict[str, Any], model: str) -> Dict[str, Any]:
    """Attach staleness to a model-status response."""
    if isinstance(payload, dict):
        payload["training"] = staleness(model)
    return payload
