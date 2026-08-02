FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS base

WORKDIR /app

COPY pyproject.toml uv.lock* /app/
COPY shared /app/shared
COPY services/api-gateway /app/services/api-gateway

RUN uv sync --frozen --package api-gateway --no-dev 2>/dev/null \
    || uv sync --package api-gateway --no-dev

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8000

# No `opentelemetry-instrument` wrapper here on purpose — the OTel Operator's
# webhook injects instrumentation via PYTHONPATH + an init container instead
# (see demo-services/k8s/23-api-gateway.yaml's
# instrumentation.opentelemetry.io/inject-python annotation). See day04.md.
CMD ["uvicorn", "api_gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
