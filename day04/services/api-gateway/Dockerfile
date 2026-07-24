FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS base

WORKDIR /app

COPY pyproject.toml uv.lock* /app/
COPY shared /app/shared
COPY services/api-gateway /app/services/api-gateway

RUN uv sync --frozen --package api-gateway --no-dev 2>/dev/null \
    || uv sync --package api-gateway --no-dev

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8000

CMD ["opentelemetry-instrument", "uvicorn", "api_gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
