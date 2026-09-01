FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# CPU-only torch keeps the image ~4 GB smaller
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

# Pre-download the default embedding model so the first tenant ingest does not
# wait for a model download. Override with: docker compose build --build-arg EMBEDDING_MODEL=...
ARG EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
RUN python -c "import os; from sentence_transformers import SentenceTransformer; SentenceTransformer(os.environ.get('EMBEDDING_MODEL', '${EMBEDDING_MODEL}'), trust_remote_code=True)"

COPY app ./app
COPY static ./static
COPY scripts ./scripts

EXPOSE 8000
# --proxy-headers + --forwarded-allow-ips lets the app trust X-Forwarded-Proto/For
# from the TLS-terminating reverse proxy (Caddy), so request.url.scheme is https
# and Secure cookies / SSO redirect URIs are correct. Safe when nothing else can
# reach :8000 (compose binds it to 127.0.0.1).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
