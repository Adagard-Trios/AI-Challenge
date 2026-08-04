"""
Weather Prediction — standalone inference service.

Wraps src/components/predictor.py:WeatherPredictor behind a small HTTP API so the
model can run as its own Render service.

Why this file exists and app.py does not: every model sub-project declares a
top-level package literally named `src`, so they cannot share one interpreter.
The monolith works around that with sys.path/sys.modules surgery; running each
model in its own container makes the collision disappear.

Run:  uvicorn service:app --host 0.0.0.0 --port $PORT
"""
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# The model code uses both `from src...` imports and CWD-relative paths
# (logs/, artifacts/, data_schema/). Anchor both to this directory.
SERVICE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SERVICE_ROOT))
os.chdir(SERVICE_ROOT)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("weather_service")

app = FastAPI(title="Weather Prediction Service")

_cors = [o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors,
    allow_credentials=_cors != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MODELS_DIR = SERVICE_ROOT / "artifacts" / "models"
PREDICTIONS_DIR = SERVICE_ROOT / "output" / "predictions"

_predictor = None
_load_error: Optional[str] = None


def get_predictor():
    """
    Lazily construct WeatherPredictor.

    Deliberately lazy: importing TensorFlow costs ~1 GB of RSS and many seconds.
    Doing it at module import would delay the $PORT bind past Render's
    health-check window and make cold starts look like crashes.
    """
    global _predictor, _load_error
    if _predictor is not None or _load_error is not None:
        return _predictor
    try:
        from src.components.predictor import WeatherPredictor  # noqa: E402
        _predictor = WeatherPredictor()
        logger.info("[weather] predictor loaded")
    except Exception as e:  # pragma: no cover - depends on runtime env
        _load_error = str(e)
        logger.exception("[weather] failed to load predictor")
    return _predictor


@app.get("/health")
async def health() -> Dict[str, Any]:
    """Liveness probe. Must not touch TensorFlow — keep it instant."""
    return {
        "status": "ok",
        "service": "weather-prediction",
        "models_present": len(list(MODELS_DIR.glob("lstm_*.h5"))) if MODELS_DIR.exists() else 0,
    }


@app.get("/model/status")
async def model_status() -> Dict[str, Any]:
    """Mirrors the monolith's /api/weather/model/status payload."""
    from datetime import datetime

    model_files = list(MODELS_DIR.glob("lstm_*.h5")) if MODELS_DIR.exists() else []
    prediction_files = (
        list(PREDICTIONS_DIR.glob("predictions_*.json")) if PREDICTIONS_DIR.exists() else []
    )

    latest_prediction = None
    if prediction_files:
        latest = max(prediction_files, key=lambda p: p.stat().st_mtime)
        latest_prediction = {
            "file": latest.name,
            "modified": datetime.fromtimestamp(latest.stat().st_mtime).isoformat(),
        }

    return {
        "status": "available" if model_files else "not_trained",
        "models_trained": len(model_files),
        "trained_stations": [f.stem.replace("lstm_", "").upper() for f in model_files],
        "latest_prediction": latest_prediction,
        "predictions_available": len(prediction_files),
        "load_error": _load_error,
    }


@app.get("/predict")
async def predict() -> Dict[str, Any]:
    """
    Next-day predictions for all 25 districts.

    Serves the most recent cached prediction when available, otherwise runs
    inference and caches the result — same policy as the monolith.
    """
    predictor = get_predictor()
    if predictor is None:
        return {
            "status": "unavailable",
            "message": f"Weather prediction model not loaded: {_load_error}",
            "predictions": None,
        }
    try:
        predictions = predictor.get_latest_predictions()
        if predictions is None:
            logger.info("[weather] generating new predictions")
            predictions = predictor.predict_all_districts()
            predictor.save_predictions(predictions)

        return {
            "status": "success",
            "prediction_date": predictions.get("prediction_date"),
            "generated_at": predictions.get("generated_at"),
            "districts": predictions.get("districts", {}),
            "total_districts": len(predictions.get("districts", {})),
        }
    except Exception as e:
        logger.exception("[weather] prediction failed")
        return {"status": "error", "message": str(e)}


@app.get("/predict/{district}")
async def predict_district(district: str) -> Dict[str, Any]:
    """Single-district slice of the full prediction set."""
    result = await predict()
    if result.get("status") != "success":
        return result

    districts = result.get("districts", {})
    key = next((k for k in districts if k.lower() == district.lower()), None)
    if key is None:
        return {"status": "not_found", "message": f"District '{district}' not found"}

    return {
        "status": "success",
        "prediction_date": result.get("prediction_date"),
        "prediction": districts[key],
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8081")))
