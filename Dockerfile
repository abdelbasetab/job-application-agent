# syntax=docker/dockerfile:1
# Production image for the Job Application Agent multi-user web UI.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    WEB_HOST=0.0.0.0 \
    WEB_PORT=7860 \
    JOB_AGENT_DATA_DIR=/data \
    SQLITE_PATH=/data/job_agent.db \
    CHROMA_PATH=/data/chroma_db

WORKDIR /app

# Build tools for any dependency that ships only an sdist; curl for the healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# Copy only what the build needs first, so dependency layers cache well.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Run unprivileged; /data is the only writable path (SQLite + per-user dirs).
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data
USER appuser

VOLUME ["/data"]
EXPOSE 7860

# /api/auth/me is unauthenticated and cheap — a good liveness probe.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${WEB_PORT}/api/auth/me" || exit 1

CMD ["python", "-m", "job_agent.main", "web", "--host", "0.0.0.0", "--port", "7860"]
