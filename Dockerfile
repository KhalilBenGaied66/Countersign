# Two stages: dependencies are resolved from the lock file with uv, then copied into a
# slim image that runs as an unprivileged user. The interpreter is one the test suite
# runs on (see .github/workflows/ci.yml).
FROM python:3.13-slim AS build

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Dependencies first: this layer is rebuilt only when the lock file changes.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable


FROM python:3.13-slim

RUN useradd --create-home --uid 10001 countersign \
    && mkdir /data \
    && chown countersign /data
WORKDIR /app

COPY --from=build /app/.venv /app/.venv
# Reference data, the sample documents and their recorded model answers: enough to try
# the application without a GPU (`countersign demo`, the demo profile of
# docker-compose.yml).
COPY data ./data
COPY evals/cassettes ./evals/cassettes

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    COUNTERSIGN_DATABASE_URL=sqlite:////data/countersign.db \
    COUNTERSIGN_STORAGE_DIR=/data/documents \
    COUNTERSIGN_EXPORT_DIR=/data/export

USER countersign
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"

# A container has to listen on all its interfaces for a port to be published. The
# application refuses to do that without API keys: set COUNTERSIGN_API_KEYS, or
# COUNTERSIGN_ALLOW_OPEN=true when the port is published where only you can reach it
# (docker-compose.yml publishes it on 127.0.0.1).
CMD ["countersign", "serve", "--host", "0.0.0.0", "--port", "8000"]
