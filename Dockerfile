# Production image for the PilloraQuestionBank FastAPI backend.
# Targets linux/arm64 (Oracle Cloud Ampere VM); python:3.11-slim is multi-arch.
# All runtime deps ship as manylinux wheels for both x86_64 and aarch64
# (psycopg[binary], pymupdf, Pillow, reportlab), so no apt packages (e.g.
# Poppler) and no native compilation are required on either architecture.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

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
