FROM python:3.11-slim

WORKDIR /app

# No browser, and none of Chromium's ~20 shared libraries.
#
# This used to say "collection runs in the user's connector". The connector was
# merged into the backend, so that reason is gone -- but the conclusion is not,
# for two reasons that outlive it:
#
#   1. Chromium is 100-300 MB resident on top of a ~210 MB base. On a 512 MB
#      free instance that is what the agent loop tips over.
#   2. Connecting an account opens a VISIBLE browser for a human to complete
#      2FA (browser_login.py launches with headless=False), and sessions are
#      encrypted to the OS keyring of the machine that created them. A
#      container has neither a display nor that keyring, so social login cannot
#      work here however much RAM it is given.
#
# Social collection therefore belongs on the user's own machine -- see
# HOSTING.md. Browser-backed tools report themselves unavailable rather than
# crashing (utils.py guards the import via PLAYWRIGHT_AVAILABLE).
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
# --retries and --timeout are not padding. This set pulls ~40 wheels including
# several large ones (chromadb, onnxruntime, scikit-learn), and pip's default
# 15s socket timeout with 5 retries lost a whole ~18-minute build to a single
# slow response from files.pythonhosted.org:
#
#   pip._vendor.urllib3.exceptions.ReadTimeoutError: HTTPSConnectionPool(
#       host='files.pythonhosted.org', port=443): Read timed out.
#
# Losing everything already downloaded because one file was slow is a bad
# trade at this size.
RUN pip install --no-cache-dir --retries 10 --timeout 120 \
    -r requirements-service.txt

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
# Retried, and non-fatal only after retrying.
#
# This downloads ~80 MB and a single dropped stream failed the whole build:
#
#   httpx ... map_httpcore_exceptions() -> exit code 1
#
# The cache is an OPTIMISATION, not a correctness requirement -- without it
# chromadb downloads the model on first use, which costs one slow request
# rather than a broken image. Failing an otherwise-good build on a transient
# is the worse trade, so this tries three times and then continues with a
# loud warning, which is honest about what the image does and does not have.
RUN for i in 1 2 3; do \
      python -c "from chromadb.utils import embedding_functions as ef; ef.ONNXMiniLM_L6_V2()(['warm the cache'])" \
        && echo "[build] ONNX embedder cached" && break; \
      echo "[build] embedder download attempt $i failed; retrying"; sleep 5; \
    done; \
    python -c "import os,sys; sys.exit(0 if os.path.isdir(os.path.expanduser('~/.cache/chroma')) else 1)" \
      || echo "[build] WARNING: ONNX embedder NOT baked in; it will download on first use"

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