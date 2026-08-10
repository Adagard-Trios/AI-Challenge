# Astro CLI Dockerfile for Sri Lanka AI Challenge 2026 Airflow
# Includes all dependencies for ML pipeline execution

FROM quay.io/astronomer/astro-runtime:12.3.0

# Install system dependencies
USER root
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*
USER astro

# Copy requirements and install
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
