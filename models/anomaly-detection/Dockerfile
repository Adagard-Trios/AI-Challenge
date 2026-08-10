# Anomaly Detection inference service.
#
# Build context is THIS directory (models/anomaly-detection).
#
# MODEL CACHE: src/utils/vectorizer.py and language_detector.py need models_cache/
# (FastText lid.176.bin ~126 MB plus HuggingFace BERT weights), which is not
# committed. Baking it at build time keeps cold starts fast and the container
# offline-capable, but adds ~1.5 GB to the image and several minutes to the build.
#
# Set DOWNLOAD_MODELS=0 as a build arg to skip it — the service still runs, on the
# keyword/severity heuristic tier, and /model/status will say so.

FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8084 \
    HF_HOME=/app/models_cache

# fasttext-wheel and hdbscan compile C extensions.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-service.txt .
RUN pip install --no-cache-dir -r requirements-service.txt

COPY . .

# Pre-fetch embedding + language-ID models. Non-fatal: a failure here degrades the
# service to heuristic scoring rather than breaking the build.
ARG DOWNLOAD_MODELS=1
RUN if [ "$DOWNLOAD_MODELS" = "1" ]; then \
      python download_models.py || echo "WARN: model download failed - heuristic tier only"; \
    fi

EXPOSE 8084

CMD ["sh", "-c", "uvicorn service:app --host 0.0.0.0 --port ${PORT:-8084}"]
