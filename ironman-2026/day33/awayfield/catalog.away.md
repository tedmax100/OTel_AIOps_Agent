# Telemetry Schema Catalog

Generated from the live stack at 2026-08-31T08:53:56+00:00 by `day33/awayfield/make_catalog.py`. It is an inventory of what this environment contains — nothing here is an instruction about how to call a tool, and no value below was typed in by hand.

## Metrics (Prometheus)

6 application metric names are present (4 runtime/scrape metrics are omitted). For each one, the labels it actually carries and the values seen:

- `http_request_duration_seconds_bucket` — 60 series
  - `instance`: `api-gateway:8081`, `order-service:8083`, `payment-service:8084`, `user-service:8082`, `webapp:8080`
  - `job`: `api-gateway`, `order-service`, `payment-service`, `user-service`, `webapp`
  - `le`: histogram buckets, 12 boundaries
- `http_request_duration_seconds_count` — 5 series
  - `instance`: `api-gateway:8081`, `order-service:8083`, `payment-service:8084`, `user-service:8082`, `webapp:8080`
  - `job`: `api-gateway`, `order-service`, `payment-service`, `user-service`, `webapp`
- `http_request_duration_seconds_sum` — 5 series
  - `instance`: `api-gateway:8081`, `order-service:8083`, `payment-service:8084`, `user-service:8082`, `webapp:8080`
  - `job`: `api-gateway`, `order-service`, `payment-service`, `user-service`, `webapp`
- `http_requests_total` — 6 series
  - `instance`: `order-service:8083`, `payment-service:8084`, `user-service:8082`
  - `job`: `order-service`, `payment-service`, `user-service`
  - `status`: `200`, `500`
- `service_cache_refresh_lag_seconds` — 5 series
  - `instance`: `api-gateway:8081`, `order-service:8083`, `payment-service:8084`, `user-service:8082`, `webapp:8080`
  - `job`: `api-gateway`, `order-service`, `payment-service`, `user-service`, `webapp`
- `service_retry_queue_depth` — 5 series
  - `instance`: `api-gateway:8081`, `order-service:8083`, `payment-service:8084`, `user-service:8082`, `webapp:8080`
  - `job`: `api-gateway`, `order-service`, `payment-service`, `user-service`, `webapp`

## Logs (Loki)

Stream labels and their values:

- `job`: `api-gateway`, `order-service`, `payment-service`, `user-service`, `webapp`
- `level`: `error`, `info`, `warn`
- `service`: `api-gateway`, `order-service`, `payment-service`, `user-service`, `webapp`
- `service_name`: `api-gateway`, `order-service`, `payment-service`, `user-service`, `webapp`

Line bodies are JSON (25/25 sampled lines parsed). Fields inside the body, with their JSON types — these are not stream labels, so reaching them needs a parser stage:

- `duration_ms`: float
- `level`: str
- `message`: str
- `method`: str
- `path`: str
- `service`: str
- `status`: int
- `timestamp`: str
- `trace_id`: str

## Traces (Tempo)

Searchable tag names: `http.method`, `http.route`, `http.status_code`, `http.url`, `service.name`

Root services seen in a recent search: `webapp`
Root span names seen: `GET /api/cart`, `GET /api/products`, `GET /api/users`, `POST /api/orders`, `POST /api/payments`
