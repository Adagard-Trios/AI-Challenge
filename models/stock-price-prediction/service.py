"""
Stock Price Prediction, standalone inference service.

Wraps src/components/predictor.py:StockPredictor behind a small HTTP API so the
model can run as its own Render service.

NOTE: app.py in this directory is the original Streamlit dashboard and is left
untouched. This service is the JSON API the monolith consumes; deploy app.py
separately if you also want the interactive dashboard.

KNOWN GAP: StockPredictor looks for Artifacts/<timestamp>/model_trainer/
trained_model/model.pkl, but the committed artifact lives at
artifacts/models/stock_model.pkl. Those paths do not meet, so the predictor falls
back to simulated prices. /model/status reports this explicitly rather than
pretending the numbers are real.

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
logger = logging.getLogger("stock_service")

app = FastAPI(title="Stock Price Prediction Service")

_cors = [o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors,
    allow_credentials=_cors != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MODELS_DIR = SERVICE_ROOT / "artifacts" / "models"
LEGACY_ARTIFACTS = SERVICE_ROOT / "Artifacts"
PREDICTIONS_DIR = SERVICE_ROOT / "output" / "predictions"

_predictor = None
_load_error: Optional[str] = None


def get_predictor():
    """Lazily construct StockPredictor, keeps heavy imports off the health path."""
    global _predictor, _load_error
    if _predictor is not None or _load_error is not None:
        return _predictor
    try:
        from src.components.predictor import StockPredictor  # noqa: E402
        _predictor = StockPredictor()
        logger.info("[stock] predictor loaded")
    except Exception as e:  # pragma: no cover
        _load_error = str(e)
        logger.exception("[stock] failed to load predictor")
    return _predictor


@app.get("/health")
async def health() -> Dict[str, Any]:
    """Liveness probe. Must stay instant."""
    return {
        "status": "ok",
        "service": "stock-price-prediction",
        "model_present": (MODELS_DIR / "stock_model.pkl").exists(),
    }


@app.get("/model/status")
async def model_status() -> Dict[str, Any]:
    """
    Mirrors the monolith's /api/stocks/model/status payload.

    `models_trained: 0` is the historically correct answer here: the loader globs
    for *_model.h5 under Artifacts/, and this project ships .pkl under artifacts/.
    """
    h5 = list(MODELS_DIR.glob("*_model.h5")) if MODELS_DIR.exists() else []
    pkl = list(MODELS_DIR.glob("*.pkl")) if MODELS_DIR.exists() else []
    prediction_files = (
        list(PREDICTIONS_DIR.glob("predictions_*.json")) if PREDICTIONS_DIR.exists() else []
    )
    return {
        "status": "available" if pkl else "not_trained",
        "models_trained": len(h5),
        "pkl_artifacts": [p.name for p in pkl],
        # True only when the timestamped layout the predictor expects exists.
        "predictor_artifacts_found": LEGACY_ARTIFACTS.exists(),
        "predictions_available": len(prediction_files),
        "load_error": _load_error,
    }


@app.get("/predict")
async def predict() -> Dict[str, Any]:
    """Predictions for all configured CSE tickers."""
    predictor = get_predictor()
    if predictor is None:
        return {
            "status": "unavailable",
            "message": f"Stock model not loaded: {_load_error}",
            "predictions": None,
        }
    try:
        predictions = predictor.get_latest_predictions()
        if predictions is None:
            logger.info("[stock] generating new predictions")
            predictions = predictor.predict_all_stocks()
            try:
                predictor.save_predictions(predictions)
            except Exception:
                logger.warning("[stock] could not cache predictions", exc_info=True)
        return {"status": "success", "predictions": predictions}
    except Exception as e:
        logger.exception("[stock] prediction failed")
        return {"status": "error", "message": str(e)}


@app.get("/predict/{symbol}")
async def predict_symbol(symbol: str) -> Dict[str, Any]:
    """Prediction for a single ticker."""
    predictor = get_predictor()
    if predictor is None:
        return {
            "status": "unavailable",
            "message": f"Stock model not loaded: {_load_error}",
            "prediction": None,
        }
    try:
        return {"status": "success", "symbol": symbol, "prediction": predictor.predict_stock(symbol)}
    except Exception as e:
        logger.exception("[stock] prediction failed for %s", symbol)
        return {"status": "error", "symbol": symbol, "message": str(e)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8083")))
