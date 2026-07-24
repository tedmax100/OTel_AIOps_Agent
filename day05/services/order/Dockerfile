FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS base

WORKDIR /app

COPY pyproject.toml uv.lock* /app/
COPY shared /app/shared
COPY services/order /app/services/order

RUN uv sync --frozen --package order-service --no-dev 2>/dev/null \
    || uv sync --package order-service --no-dev

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8000

CMD ["opentelemetry-instrument", "uvicorn", "order_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
