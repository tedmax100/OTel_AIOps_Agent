FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS base

WORKDIR /app

COPY pyproject.toml uv.lock* /app/
COPY shared /app/shared
COPY services/payment /app/services/payment

RUN uv sync --frozen --package payment-service --no-dev 2>/dev/null \
    || uv sync --package payment-service --no-dev

# Auto-instrumentation packages are declared as deps in shared/pyproject.toml
# rather than installed via `opentelemetry-bootstrap -a install` (the bootstrap
# script needs pip in the venv, which uv doesn't provide).

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8000

# `opentelemetry-instrument` wraps the entry point, sets up tracer / meter /
# logger providers from OTEL_* env vars, and applies all installed
# auto-instrumentations BEFORE the app's modules are imported. That's why
# this works without a single SDK call in our source.
CMD ["opentelemetry-instrument", "uvicorn", "payment_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
