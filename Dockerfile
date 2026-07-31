# syntax=docker/dockerfile:1

FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-runtime.lock ./
RUN python -m pip wheel --wheel-dir /wheels --requirement requirements-runtime.lock

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m pip install hatchling==1.27.0 \
    && python -m pip wheel --no-build-isolation --no-deps --wheel-dir /wheels .


FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    WEB_HOST=0.0.0.0 \
    WEB_PORT=7860 \
    WEB_SECURE_COOKIES=true \
    WEB_ALLOW_REGISTRATION=false \
    JOB_AGENT_DATA_DIR=/data \
    SQLITE_PATH=/data/job_agent.db \
    PROFILE_INDEX_PATH=/data/profile_index

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core tesseract-ocr tesseract-ocr-deu \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser \
    && mkdir -p /data \
    && chown appuser:appuser /data

COPY --from=builder /wheels /wheels
RUN python -m pip install --no-index --find-links=/wheels job-application-agent \
    && rm -rf /wheels

USER 10001:10001
VOLUME ["/data"]
EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('WEB_PORT','7860')+'/api/auth/me', timeout=3)"

CMD ["python", "-m", "job_agent.main", "web", "--host", "0.0.0.0", "--port", "7860"]
