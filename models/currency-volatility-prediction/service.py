"""
USD/LKR Currency Volatility — standalone inference service.

Wraps src/components/predictor.py:CurrencyPredictor behind a small HTTP API so the
model can run as its own Render service. See weather-prediction/service.py for why
this is `service.py` and not `app.py`.

KNOWN GAP: CurrencyPredictor.predict() reads artifacts/models/training_config.json,
which is NOT shipped in this repo (only gru_usd_lkr.h5 and scalers_usd_lkr.joblib
are). Live inference therefore raises FileNotFoundError until that file is produced
by a training run. This service degrades to the predictor's own
generate_fallback_prediction() instead of 500-ing, and /model/status reports the
missing file explicitly.

Run:  uvicorn service:app --host 0.0.0.0 --port $PORT
"""
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

SERVICE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SERVICE_ROOT))
os.chdir(SERVICE_ROOT)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("currency_service")

app = FastAPI(title="Currency Volatility Prediction Service")

_cors = [o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors,
    allow_credentials=_cors != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MODELS_DIR = SERVICE_ROOT / "artifacts" / "models"
DATA_DIR = SERVICE_ROOT / "artifacts" / "data"
PREDICTIONS_DIR = SERVICE_ROOT / "output" / "predictions"
TRAINING_CONFIG = MODELS_DIR / "training_config.json"

_predictor = None
_load_error: Optional[str] = None


def get_predictor():
    """Lazily construct CurrencyPredictor — keeps TensorFlow off the health path."""
    global _predictor, _load_error
    if _predictor is not None or _load_error is not None:
        return _predictor
    try:
        from src.components.predictor import CurrencyPredictor  # noqa: E402
        _predictor = CurrencyPredictor()
        logger.info("[currency] predictor loaded")
    except Exception as e:  # pragma: no cover
        _load_error = str(e)
        logger.exception("[currency] failed to load predictor")
    return _predictor


@app.get("/health")
async def health() -> Dict[str, Any]:
    """Liveness probe. Must stay instant — no TensorFlow import."""
    return {
        "status": "ok",
        "service": "currency-volatility-prediction",
        "model_present": (MODELS_DIR / "gru_usd_lkr.h5").exists(),
    }


@app.get("/model/status")
async def model_status() -> Dict[str, Any]:
    """Mirrors the monolith's /api/currency/model/status payload."""
    return {
        "status": "available" if (MODELS_DIR / "gru_usd_lkr.h5").exists() else "not_trained",
        "model_exists": (MODELS_DIR / "gru_usd_lkr.h5").exists(),
        "scalers_exist": (MODELS_DIR / "scalers_usd_lkr.joblib").exists(),
        # Surfaced because its absence is what blocks live inference.
        "training_config_exists": TRAINING_CONFIG.exists(),
        "live_inference_available": TRAINING_CONFIG.exists(),
        "load_error": _load_error,
    }


@app.get("/predict")
async def predict() -> Dict[str, Any]:
    """
    Next-day USD/LKR prediction.

    Order of preference: cached prediction -> live inference -> fallback estimate.
    """
    predictor = get_predictor()
    if predictor is None:
        return {
            "status": "unavailable",
            "message": f"Currency model not loaded: {_load_error}",
            "prediction": None,
        }

    try:
        cached = predictor.get_latest_prediction()
        if cached is not None:
            return {"status": "success", "source": "cached", "prediction": cached}
    except Exception:
        logger.warning("[currency] no cached prediction available", exc_info=True)

    try:
        prediction = predictor.generate_real_prediction()
        if prediction:
            return {"status": "success", "source": "model", "prediction": prediction}
        raise RuntimeError("generate_real_prediction() returned no result")
    except Exception as e:
        logger.warning("[currency] live inference unavailable (%s); using fallback", e)
        try:
            return {
                "status": "degraded",
                "source": "fallback",
                "reason": (
                    "training_config.json missing from artifacts/models"
                    if not TRAINING_CONFIG.exists()
                    else str(e)
                ),
                "prediction": predictor.generate_fallback_prediction(),
            }
        except Exception as inner:
            logger.exception("[currency] fallback failed")
            return {"status": "error", "message": str(inner)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8082")))
