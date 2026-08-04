"""
Gateway to the standalone model inference services.

Each ML model can run either:
  * in-process   - imported directly by main.py via sys.path/importlib surgery
                   (the original behaviour; still the default locally), or
  * out-of-process - as its own Render service, reached over HTTP.

Which one is used is decided per-model by an env var. When the URL is unset the
caller falls back to the in-process path, so local development needs no config and
existing behaviour is preserved exactly.

    WEATHER_SERVICE_URL   e.g. https://slac2026-weather.onrender.com
    CURRENCY_SERVICE_URL
    STOCK_SERVICE_URL
    ANOMALY_SERVICE_URL

Running the models out-of-process also removes the reason for main.py's sys.path
and sys.modules juggling: the four model projects each define a top-level package
named `src`, which cannot coexist in one interpreter but is a non-issue once each
lives in its own container.
"""
import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("model_gateway")

_ENV_KEYS = {
    "weather": "WEATHER_SERVICE_URL",
    "currency": "CURRENCY_SERVICE_URL",
    "stock": "STOCK_SERVICE_URL",
    "anomaly": "ANOMALY_SERVICE_URL",
}

# Model services do lazy TensorFlow/Torch loading, so the first request after a
# cold start is slow. Generous timeout, but still bounded.
DEFAULT_TIMEOUT = float(os.getenv("MODEL_SERVICE_TIMEOUT", "60"))


def service_url(model: str) -> Optional[str]:
    """Configured base URL for a model service, or None to use in-process mode."""
    raw = os.getenv(_ENV_KEYS.get(model, ""), "").strip()
    return raw.rstrip("/") or None


def is_remote(model: str) -> bool:
    """True when this model should be reached over HTTP rather than imported."""
    return service_url(model) is not None


async def call(
    model: str,
    path: str,
    method: str = "GET",
    json_body: Optional[Dict[str, Any]] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Optional[Dict[str, Any]]:
    """
    Call a model service endpoint.

    Returns the decoded JSON body, or None if the model is not configured for
    remote mode or the call failed. None is the signal to fall back to the
    in-process path — the gateway never raises into a request handler.
    """
    base = service_url(model)
    if base is None:
        return None

    url = f"{base}/{path.lstrip('/')}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(method, url, json=json_body)
            resp.raise_for_status()
            return resp.json()
    except httpx.TimeoutException:
        logger.warning("[gateway] %s timed out after %ss: %s", model, timeout, url)
    except httpx.HTTPStatusError as e:
        logger.warning("[gateway] %s returned %s: %s", model, e.response.status_code, url)
    except Exception as e:
        logger.warning("[gateway] %s call failed (%s): %s", model, e, url)
    return None


def call_sync(
    model: str,
    path: str,
    method: str = "GET",
    json_body: Optional[Dict[str, Any]] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Optional[Dict[str, Any]]:
    """
    Blocking twin of call(), for handlers FastAPI runs in its threadpool.

    Used by sync endpoints (e.g. /api/anomalies) that also perform blocking SQLite
    reads — turning those async purely to reach the gateway would move that
    blocking work onto the event loop.
    """
    base = service_url(model)
    if base is None:
        return None

    url = f"{base}/{path.lstrip('/')}"
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.request(method, url, json=json_body)
            resp.raise_for_status()
            return resp.json()
    except httpx.TimeoutException:
        logger.warning("[gateway] %s timed out after %ss: %s", model, timeout, url)
    except httpx.HTTPStatusError as e:
        logger.warning("[gateway] %s returned %s: %s", model, e.response.status_code, url)
    except Exception as e:
        logger.warning("[gateway] %s call failed (%s): %s", model, e, url)
    return None


async def health_all() -> Dict[str, Any]:
    """Health snapshot of every configured model service, for /api/models/health."""
    out: Dict[str, Any] = {}
    for model in _ENV_KEYS:
        url = service_url(model)
        if url is None:
            out[model] = {"mode": "in-process", "url": None}
            continue
        body = await call(model, "/health", timeout=10)
        out[model] = {
            "mode": "remote",
            "url": url,
            "reachable": body is not None,
            "detail": body,
        }
    return out
