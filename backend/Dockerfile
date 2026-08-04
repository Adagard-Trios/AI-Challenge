FROM python:3.11-slim

WORKDIR /app

# Install system dependencies including Playwright requirements
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    gnupg \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright and browsers
RUN pip install playwright && \
    playwright install chromium --with-deps

# Copy application code
COPY . .
WORKDIR /app/backend

# Render injects $PORT at runtime and routes to it; this is only the local default.
EXPOSE 8000
ENV PORT=8000


# Set execution permissions for scripts
RUN chmod +x scripts/start_backend.sh

# Run API server (and ML training) via startup script
CMD ["/bin/bash", "scripts/start_backend.sh"]