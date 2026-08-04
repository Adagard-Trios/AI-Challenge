#!/bin/bash
set -e

echo "🚀 Starting Sri Lanka AI Challenge 2026 Backend..."

# 1. Run ML Training Pipeline (if models missing)
# We trust the script to handle logic. For Hackathon, we force run it to ensure fresh state if possible,
# or we can check if output dir is empty.
echo "🧠 Checking ML Models..."
# Create output dir if not exists
mkdir -p ../models/anomaly-detection/output

# Run training (standalone script)
# This will use data from 'datasets/' if available.
# If datasets are empty, it might fail/skip, so we allow failure without stopping container.
# On memory-capped hosts (Render) skip it entirely: training here delays the
# $PORT bind past the platform's health-check window and can OOM the instance.
case "$(printf '%s' "${DISABLE_AUTO_TRAIN:-}" | tr '[:upper:]' '[:lower:]')" in
  1|true|yes)
    echo "⏭️  Skipping ML training (DISABLE_AUTO_TRAIN set)"
    ;;
  *)
    python scripts/train_ml_models.py || echo "⚠️ ML Training warning (continuing anyway)..."
    ;;
esac

# 2. Start Request Server
# Render injects $PORT and routes to it; bind 0.0.0.0 or the health check fails.
echo "⚡ Starting FastAPI Server on port $PORT..."
uvicorn main:app --host 0.0.0.0 --port $PORT
