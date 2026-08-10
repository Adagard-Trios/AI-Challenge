# Stock Price Prediction inference service (JSON API).
#
# Build context is THIS directory.
#
# Serves service.py, not the Streamlit dashboard in app.py. To deploy the
# dashboard instead, add `streamlit` and `plotly` to requirements-service.txt and
# swap the CMD for:
#   streamlit run app.py --server.port ${PORT} --server.address 0.0.0.0

FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8083

COPY requirements-service.txt .
RUN pip install --no-cache-dir -r requirements-service.txt

COPY . .

EXPOSE 8083

CMD ["sh", "-c", "uvicorn service:app --host 0.0.0.0 --port ${PORT:-8083}"]
