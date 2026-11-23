# Production image for the PilloraQuestionBank FastAPI backend.
# Targets linux/arm64 (Oracle Cloud Ampere VM); python:3.11-slim-bookworm is multi-arch (pinned: plain -slim moved to trixie, whose Tesseract is 5.5).
# Python deps ship as manylinux wheels for both x86_64 and aarch64
# (psycopg[binary], pymupdf, Pillow, reportlab, opencv-python-headless), so no
# native compilation is needed. The one apt package is Tesseract: the ingest worker
# (python -m app.worker) OCRs scanned answer tables with it. Debian bookworm ships
# 5.3.0, the version the OCR calibration in ingestion/docker pins.
# The same image runs the API and the worker (see deploy/docker-compose.prod.yml).
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends tesseract-ocr && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt ./
COPY ingestion/requirements.txt ./ingestion-requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r ingestion-requirements.txt

# The ingestion package (question_extractor, ingester, pipeline), installed
# non-editable; its dependencies are already in the layer above. Its sample
# corpus and OCR Dockerfile stay out of the image (.dockerignore).
COPY ingestion ./ingestion
RUN pip install --no-cache-dir --no-deps ./ingestion && rm -rf ingestion

# Application code and migrations.
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

# Run as an unprivileged user.
RUN useradd --create-home --uid 1000 appuser && \
    mkdir /app/logs && \
    chown appuser:appuser /app/logs
USER appuser

EXPOSE 8000

# Single worker: only 1-10 concurrent users, uptime is not a priority.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
