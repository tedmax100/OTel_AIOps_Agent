FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS base

WORKDIR /app

COPY pyproject.toml uv.lock* /app/
COPY shared /app/shared
COPY services/webapp /app/services/webapp

RUN uv sync --frozen --package webapp --no-dev 2>/dev/null \
    || uv sync --package webapp --no-dev

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8000

CMD ["opentelemetry-instrument", "uvicorn", "webapp.main:app", "--host", "0.0.0.0", "--port", "8000"]
