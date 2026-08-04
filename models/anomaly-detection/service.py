"""
Anomaly Detection — standalone inference service.

Unlike the other three models this project ships no predictor.py, so inference is
assembled here from the pieces that do exist:
  src/utils/language_detector.py  -> detect_language()
  src/utils/vectorizer.py         -> vectorize_text()  (768-dim multilingual)
  artifacts/model_trainer/*.joblib -> trained IsolationForest / LOF / cluster models

Scoring tiers, in order of preference:
  1. "model"     - embeddings + IsolationForest.decision_function
  2. "heuristic" - severity + keyword scoring, byte-for-byte the same fallback the
                   monolith uses in /api/anomalies, so behaviour is unchanged when
                   the ML stack is unavailable

IMPORTANT: tier 1 needs models_cache/ (FastText lid.176.bin ~126 MB plus HuggingFace
BERT weights), which is NOT committed. Run `python download_models.py` in the Docker
build to enable it; without it the service still answers, on the heuristic tier.
/health reports which tier is active.

Run:  uvicorn service:app --host 0.0.0.0 --port $PORT
"""
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

SERVICE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SERVICE_ROOT))
os.chdir(SERVICE_ROOT)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("anomaly_service")

app = FastAPI(title="Anomaly Detection Service")

_cors = [o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors,
    allow_credentials=_cors != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ARTIFACTS_DIR = SERVICE_ROOT / "artifacts" / "model_trainer"
CACHE_DIR = SERVICE_ROOT / "models_cache"

# Same keyword list the monolith uses, so the fallback tier matches exactly.
ANOMALY_KEYWORDS = [
    "emergency", "crisis", "breaking", "urgent", "alert",
    "warning", "critical", "disaster", "flood", "protest",
]
SEVERITY_SCORES = {"critical": 0.9, "high": 0.75, "medium": 0.5}

_model = None
_vectorize = None
_detect_language = None
_ml_error: Optional[str] = None


class Feed(BaseModel):
    """One item to score. Extra keys are preserved in the response."""
    summary: str = ""
    severity: str = "low"

    class Config:
        extra = "allow"


class DetectRequest(BaseModel):
    feeds: List[Feed] = []
    threshold: float = 0.5
    limit: int = 20


def _ml_enabled() -> bool:
    """ML tier is opt-in — see _load_ml() for why."""
    return os.getenv("ANOMALY_ML_ENABLED", "0").strip().lower() in ("1", "true", "yes")


def _load_ml():
    """
    Lazily load the embedding stack and IsolationForest.

    Opt-in via ANOMALY_ML_ENABLED=1, and off by default on purpose. With a cold
    models_cache/, sentence-transformers silently reaches out to HuggingFace and
    the first /detect blocks for minutes downloading ~250 MB of BERT weights,
    tying up a worker and looking like a hang. Defaulting to the heuristic tier
    means a fresh deploy answers immediately; flip the flag once the cache is
    warm (the Dockerfile bakes it, and the Render disk persists it).

    ANOMALY_ALLOW_DOWNLOAD=1 permits fetching at runtime. Otherwise HuggingFace is
    forced offline so a cache miss fails fast to the heuristic tier instead of
    hanging on the network.
    """
    global _model, _vectorize, _detect_language, _ml_error
    if _model is not None or _ml_error is not None:
        return _model is not None

    if not _ml_enabled():
        _ml_error = "disabled (set ANOMALY_ML_ENABLED=1 to enable embedding-based scoring)"
        logger.info("[anomaly] ML tier disabled; using heuristic tier")
        return False

    if os.getenv("ANOMALY_ALLOW_DOWNLOAD", "0").strip().lower() not in ("1", "true", "yes"):
        # Fail fast on a cache miss rather than blocking on a large download.
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    try:
        import joblib
        from src.utils.vectorizer import vectorize_text
        from src.utils.language_detector import detect_language

        model_path = ARTIFACTS_DIR / "isolation_forest_model.joblib"
        if not model_path.exists():
            raise FileNotFoundError(f"missing {model_path}")

        _model = joblib.load(model_path)
        _vectorize = vectorize_text
        _detect_language = detect_language
        logger.info("[anomaly] ML scoring enabled")
        return True
    except Exception as e:  # pragma: no cover - depends on models_cache presence
        _ml_error = str(e)
        logger.warning("[anomaly] ML tier unavailable (%s); using heuristic tier", e)
        return False


def _heuristic_score(feed: Dict[str, Any]) -> float:
    """Severity + keyword scoring — mirrors the monolith's fallback exactly."""
    summary = str(feed.get("summary", "")).lower()
    score = SEVERITY_SCORES.get(feed.get("severity", "low"), 0.25)
    matches = sum(1 for kw in ANOMALY_KEYWORDS if kw in summary)
    if matches:
        score = min(1.0, score + matches * 0.1)
    return score


def _model_score(text: str) -> float:
    """Map IsolationForest.decision_function into a 0-1 anomaly score."""
    lang = "english"
    try:
        lang = _detect_language(text)[0]
    except Exception:
        pass
    vec = _vectorize(text, lang).reshape(1, -1)
    # decision_function: negative = more anomalous. Squash to 0-1, higher = worse.
    raw = float(_model.decision_function(vec)[0])
    return max(0.0, min(1.0, 0.5 - raw))


@app.get("/health")
async def health() -> Dict[str, Any]:
    """Liveness probe. Never triggers the ML load — keep it instant."""
    return {
        "status": "ok",
        "service": "anomaly-detection",
        "artifacts_present": len(list(ARTIFACTS_DIR.glob("*.joblib"))) if ARTIFACTS_DIR.exists() else 0,
        "models_cache_present": CACHE_DIR.exists(),
        "active_tier": "model" if _model is not None else ("heuristic" if _ml_error else "not_loaded"),
    }


@app.get("/model/status")
async def model_status() -> Dict[str, Any]:
    """Which artifacts exist and whether ML scoring can actually run."""
    artifacts = sorted(p.name for p in ARTIFACTS_DIR.glob("*.joblib")) if ARTIFACTS_DIR.exists() else []
    return {
        "status": "available" if artifacts else "not_trained",
        "artifacts": artifacts,
        "models_cache_present": CACHE_DIR.exists(),
        "ml_enabled": _ml_enabled(),
        "ml_scoring_available": _model is not None,
        "ml_error": _ml_error,
        "hint": (
            "set ANOMALY_ML_ENABLED=1 to use embedding-based scoring"
            if not _ml_enabled()
            else (None if CACHE_DIR.exists() else "run `python download_models.py` to warm models_cache/")
        ),
    }


@app.post("/detect")
async def detect(req: DetectRequest) -> Dict[str, Any]:
    """
    Score feeds for anomalousness.

    Response shape matches the monolith's /api/anomalies so it can be proxied.
    """
    feeds = [f.model_dump() for f in req.feeds]
    if not feeds:
        return {
            "anomalies": [],
            "total": 0,
            "model_status": "no_data",
            "message": "No feed data supplied.",
        }

    use_ml = _load_ml()
    anomalies = []
    for f in feeds:
        text = str(f.get("summary", ""))
        score = _heuristic_score(f)
        if use_ml and text.strip():
            try:
                score = _model_score(text)
            except Exception:
                logger.warning("[anomaly] ML scoring failed; heuristic used", exc_info=True)
        if score >= req.threshold:
            anomalies.append({**f, "anomaly_score": round(score, 3), "is_anomaly": score >= 0.7})

    anomalies.sort(key=lambda a: a["anomaly_score"], reverse=True)
    return {
        "anomalies": anomalies[: req.limit],
        "total": len(anomalies),
        "model_status": "model" if use_ml else "heuristic",
        "message": None if use_ml else f"ML tier unavailable ({_ml_error}); heuristic scoring used.",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8084")))
