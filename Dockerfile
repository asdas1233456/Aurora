FROM node:20-bookworm-slim AS frontend-builder

WORKDIR /build/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app ./app
COPY docs ./docs
COPY README.md README_INTERNAL.md .env.example start.sh start.ps1 ./
COPY frontend/package.json ./frontend/package.json
COPY --from=frontend-builder /build/frontend/dist ./frontend/dist

RUN mkdir -p /app/data /app/db /app/logs /app/quarantine

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/ready').getcode() == 200 else 1)"

CMD ["python", "-m", "uvicorn", "app.bootstrap.http_app:app", "--host", "0.0.0.0", "--port", "8000"]
