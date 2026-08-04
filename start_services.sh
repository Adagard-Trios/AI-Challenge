#!/bin/bash

# start_services.sh
# Start all Sri Lanka AI Challenge 2026 Anomaly Detection services in proper order

echo "==================================================="
echo "🚀 Starting Sri Lanka AI Challenge 2026 Anomaly Detection Pipeline"
echo "==================================================="

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 1. Check for dependencies
echo "[1/3] Checking dependencies..."
if [ ! -f "models/anomaly-detection/models_cache/lid.176.bin" ]; then
    echo "⚠️  WARNING: FastText model not found in models/anomaly-detection/models_cache/"
    echo "   Please download it from: https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin"
fi

# 2. Start Vectorization API (Background)
echo "[2/3] Starting Vectorization Agent API..."
echo "   - Port: 8001"
echo "   - Log: vectorization_api.log"

# Use nohup to run in background
nohup python backend/src/api/vectorization_api.py > vectorization_api.log 2>&1 &
API_PID=$!
echo "   ✅ API started with PID: $API_PID"

# Wait for API to be ready
echo "   ⏳ Waiting for API to initialize..."
sleep 5

# 3. Start Airflow (Astro)
echo "[3/3] Starting Apache Airflow (Astro)..."
echo "   - Dashboard: http://localhost:8080"
echo "   - DAGs: models/anomaly-detection/dags"

cd models/anomaly-detection

# Check if astro is installed
if ! command -v astro &> /dev/null; then
    echo "❌ Error: 'astro' command not found. Please install Astronomer CLI."
    echo "   Skipping Airflow, but API is still running."
    echo ""
    echo "Press Ctrl+C to stop the API..."
    wait $API_PID
    exit 1
fi

# Check if it's an Astro project
if [ ! -f "Dockerfile" ]; then
    echo "⚠️  Astro project not initialized. Running 'astro dev init'..."
    astro dev init --name anomaly-detection
fi

# Start Astro
astro dev start --no-browser

# Cleanup on exit
echo ""
echo "🛑 Stopping services..."
kill $API_PID 2>/dev/null
echo "✅ Services stopped."
