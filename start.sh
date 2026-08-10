#!/bin/bash

# Sri Lanka AI Challenge 2026 Platform - Hackathon Demo Launcher
# This script starts both backend and frontend for the demo

set -e

echo "=========================================="
echo "  🇱🇰 SRI LANKA AI CHALLENGE 2026 INTELLIGENCE PLATFORM"
echo "     Hackathon Demo Startup"
echo "=========================================="
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found!"
    echo "   Please copy .env.template to .env and add your GROQ_API_KEY"
    exit 1
fi

# Load environment variables
source .env

if [ -z "$GROQ_API_KEY" ]; then
    echo "❌ Error: GROQ_API_KEY not set in .env"
    exit 1
fi

echo "✓ Environment configured"
echo ""

# Install Python dependencies
echo "📦 Installing Python dependencies..."
cd backend
uv add -r requirements.txt > /dev/null 2>&1
cd ..
echo "✓ Python dependencies installed"
echo ""

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source backend/.venv/Scripts/activate
echo "✓ Virtual environment activated"
echo ""

# Install Frontend dependencies
echo "📦 Installing Frontend dependencies..."
cd frontend
npm install > /dev/null 2>&1
echo "✓ Frontend dependencies installed"
cd ..
echo ""

# Create ML model output directory (for anomaly detection)
echo "📁 Ensuring ML directories exist..."
mkdir -p models/anomaly-detection/output
echo "✓ ML directories ready"
echo ""

# Start Backend
echo "🚀 Starting Backend API..."
cd backend
python main.py &
BACKEND_PID=$!
cd ..

# Wait for backend to start (with retry loop - graphs take time to compile)
echo "⏳ Waiting for backend to initialize (this may take 30-60 seconds)..."
MAX_RETRIES=18
RETRY_COUNT=0
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    sleep 15
    if curl -s http://localhost:8000/api/status > /dev/null 2>&1; then
        echo "✓ Backend is responding!"
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo "   Still waiting... ($((RETRY_COUNT * 15))s elapsed)"
done

# Check if backend is running
if ! curl -s http://localhost:8000/api/status > /dev/null 2>&1; then
    echo "❌ Backend failed to start after 270 seconds!"
    kill $BACKEND_PID 2>/dev/null
    exit 1
fi

echo "✓ Backend running on http://localhost:8000"
echo ""

# Start Frontend
echo "🚀 Starting Frontend..."
cd frontend
npm run dev &
FRONTEND_PID=$!
cd ..

echo ""
echo "=========================================="
echo "  ✅ SRI LANKA AI CHALLENGE 2026 PLATFORM IS RUNNING"
echo "=========================================="
echo ""
echo "🌐 Frontend: http://localhost:3000"
echo "🔧 Backend:  http://localhost:8000"
echo "📊 API Docs: http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop all services"
echo ""

# Trap Ctrl+C to stop both processes
trap "echo 'Stopping services...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT

# Wait for either process to exit
wait