# Weather Prediction inference service.
#
# Build context is THIS directory (models/weather-prediction), not the repo root.
# That isolation is the point: every model declares a top-level `src` package, and
# one-container-per-model is what stops them colliding.
#
# Replaces the previous Dockerfile, which was non-functional: Python 3.10 against
# `requires-python >=3.11`, a requirements.txt with no TensorFlow (despite loading
# .h5 models), and `CMD python3 app.py` against a 0-byte app.py.

FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8081

# Layer-cache the dependency install ahead of the source copy.
COPY requirements-service.txt .
RUN pip install --no-cache-dir -r requirements-service.txt

COPY . .

EXPOSE 8081

# Render injects $PORT; the default above covers local runs.
CMD ["sh", "-c", "uvicorn service:app --host 0.0.0.0 --port ${PORT:-8081}"]
