FROM python:3.11-slim

WORKDIR /app

# No browser, and none of Chromium's ~20 shared libraries.
#
# Social collection runs in the user's connector on their own machine, so the
# server never drives a browser. That removes roughly 300 MB from the image and,
# more importantly, removes Chromium's 100-300 MB resident footprint from a
# 512 MB instance -- which is what the agent loop used to tip over.
#
# curl is kept solely for the container health check.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install the SLIM runtime set, not requirements.txt.
#
# requirements.txt is the local-dev set and pulls TensorFlow + PyTorch + the
# training stack (3.12 GB installed) so the models can run in-process. In
# deployment they run as their own services and the backend calls them over
# HTTP, so none of that is needed — and installing it is what OOM-kills a
# 512 MB instance. See the header of requirements-service.txt.
COPY backend/requirements-service.txt .
RUN pip install --no-cache-dir -r requirements-service.txt

# Bake the ONNX sentence embedder into the image.
#
# chromadb downloads all-MiniLM-L6-v2 (~80 MB) to ~/.cache/chroma on first use.
# Render's free tier has no persistent disk, so that download would repeat on
# every cold start -- adding ~30 s to the first request after a spin-down, and
# failing outright if the instance has no egress at that moment.
#
# Anomaly detection depends on this embedder (src/embeddings.py), so fetching
# it at build time is the difference between ML inference that works on the
# first request and ML inference that works eventually.
RUN python -c "from chromadb.utils import embedding_functions as ef; ef.ONNXMiniLM_L6_V2()(['warm the cache'])"

# NOTE: `playwright install chromium` was here. Removed with the browser itself;
# see the apt block above. If a future server-side scraper needs a browser, put
# it in its own service rather than back into this one.

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