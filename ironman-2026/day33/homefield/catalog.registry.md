# Telemetry Schema Catalog

Generated at 2026-08-31T13:00:24+00:00 from the `demo-services-biz` Weaver registry, reconciled against the live stack. The registry says what each signal MEANS and which values are legal; the stack says what is actually there right now. Names below are the ones the code emits — where the registry's idiomatic name differs, it is shown in brackets. Nothing here says how to call a tool.

## Metrics

- `gateway_upstream_attempts_total` (registry: `app.gateway.upstream.attempts.count`) — counter, unit `{attempt}`. Downstream call attempts made by the gateway, retries included.
  - `status` (registry: `app.outcome`) — required, one of `created`, `authorized`, `declined`, `cancelled`, `error`
  - `retry` (registry: `app.retry`) — required, `boolean`
  - `upstream` (registry: `app.upstream`) — required, `string`
- `order_create_duration_seconds` (registry: `app.order.create.duration`) — histogram, unit `s`. Order creation handler duration.
  - `status` (registry: `app.outcome`) — required, one of `created`, `authorized`, `declined`, `cancelled`, `error`
- `orders_total` (registry: `app.orders.count`) — counter, unit `{order}`. Total order attempts, by terminal outcome.
  - `reason` (registry: `app.fail_reason`) — conditionally required, one of `unknown_product`, `auth`, `auth_failed`, `payment`, `payment_declined`, `user_upstream`, `payment_upstream`, `new_validator`, `new_validator_odd_cents`, `gateway`, `network`, `not_found`, `transient`, `session_store_timeout`
  - `status` (registry: `app.outcome`) — required, one of `created`, `authorized`, `declined`, `cancelled`, `error`
- `payment_charge_duration_seconds` (registry: `app.payment.charge.duration`) — histogram, unit `s`. Charge handler duration.
  - `status` (registry: `app.outcome`) — required, one of `created`, `authorized`, `declined`, `cancelled`, `error`
- `payment_charges_total` (registry: `app.payment.charges.count`) — counter, unit `{charge}`. Total payment charge attempts, by terminal outcome.
  - `reason` (registry: `app.fail_reason`) — conditionally required, one of `unknown_product`, `auth`, `auth_failed`, `payment`, `payment_declined`, `user_upstream`, `payment_upstream`, `new_validator`, `new_validator_odd_cents`, `gateway`, `network`, `not_found`, `transient`, `session_store_timeout`
  - `status` (registry: `app.outcome`) — required, one of `created`, `authorized`, `declined`, `cancelled`, `error`
- `user_auth_checks_total` (registry: `app.user.auth_checks.count`) — counter, unit `{check}`. Total auth checks performed by user-service, by outcome.
  - `reason` (registry: `app.fail_reason`) — conditionally required, one of `unknown_product`, `auth`, `auth_failed`, `payment`, `payment_declined`, `user_upstream`, `payment_upstream`, `new_validator`, `new_validator_odd_cents`, `gateway`, `network`, `not_found`, `transient`, `session_store_timeout`
  - `status` (registry: `app.outcome`) — required, one of `created`, `authorized`, `declined`, `cancelled`, `error`
- `user_authcheck_duration_seconds` (registry: `app.user.authcheck.duration`) — histogram, unit `s`. Auth-check handler duration in user-service.
  - `status` (registry: `app.outcome`) — required, one of `created`, `authorized`, `declined`, `cancelled`, `error`
- `user_lookups_total` (registry: `app.user.lookups.count`) — counter, unit `{lookup}`. Total user lookup attempts, by operation.
  - `op` (registry: `app.user.operation`) — required, one of `list`, `get`

**In the registry but NOT in Prometheus right now.** Treat these as conventions the code has not adopted yet — querying them returns an empty result, which is not evidence that the thing they describe did not happen:

- `gen_ai.client.operation.duration` — Duration of a GenAI operation (an LLM call).
- `gen_ai.client.token.usage` — Tokens used per GenAI operation, split by direction.

**In Prometheus but not in the registry** (auto-instrumentation and anything the conventions have not caught up with) — usable, but nothing here defines what its labels mean:

`http_client_duration_milliseconds_bucket`, `http_client_duration_milliseconds_count`, `http_client_duration_milliseconds_sum`, `http_server_active_requests`, `http_server_duration_milliseconds_bucket`, `http_server_duration_milliseconds_count`, `http_server_duration_milliseconds_sum`, `http_server_request_size_bytes_bucket`, `http_server_request_size_bytes_count`, `http_server_request_size_bytes_sum`, `http_server_response_size_bytes_bucket`, `http_server_response_size_bytes_count`, `http_server_response_size_bytes_sum`, `otel_sdk_log_created_total`, `otel_sdk_metric_reader_collection_duration_seconds_bucket`, `otel_sdk_metric_reader_collection_duration_seconds_count`, `otel_sdk_metric_reader_collection_duration_seconds_sum`, `otel_sdk_processor_log_processed_total`, `otel_sdk_processor_log_queue_capacity`, `otel_sdk_processor_log_queue_size`, `otel_sdk_processor_span_processed_total`, `otel_sdk_processor_span_queue_size`, `otel_sdk_span_live`, `otel_sdk_span_started_total`

## Events (business logs)

- `cache.miss` — not seen in this window. A cache lookup missed and the caller fell through to the origin store. Emitted by user-service's auth check when the session cache is off.
  - `cache` (registry: `app.cache.name`) — required, one of `user_session`
  - `user_id` (registry: `biz.user.id`) — required, `string`
- `deployment.started` — not seen in this window. A deployment of a service began. (reserved — not yet emitted)
  - `git_version` (registry: `service.version`) — recommended, `string`
- `http.request_failed` — not seen in this window. An upstream HTTP call failed or returned 5xx.
  - `reason` (registry: `app.fail_reason`) — conditionally required, one of `unknown_product`, `auth`, `auth_failed`, `payment`, `payment_declined`, `user_upstream`, `payment_upstream`, `new_validator`, `new_validator_odd_cents`, `gateway`, `network`, `not_found`, `transient`, `session_store_timeout`
  - `upstream` (registry: `app.upstream.service`) — required, `string`
  - `app.upstream.status_code` — conditionally required, `int`
- `http.request_received` — seen live. An inbound request was accepted by an edge/proxy service.
  - `method` (registry: `app.http.method`) — recommended, one of `GET`, `POST`, `PUT`, `DELETE`
  - `path` (registry: `app.http.route`) — required, `string`
- `order.cancelled` — seen live. An order attempt was rejected/cancelled.
  - `reason` (registry: `app.fail_reason`) — required, one of `unknown_product`, `auth`, `auth_failed`, `payment`, `payment_declined`, `user_upstream`, `payment_upstream`, `new_validator`, `new_validator_odd_cents`, `gateway`, `network`, `not_found`, `transient`, `session_store_timeout`
  - `app.upstream.status_code` — conditionally required, `int`
  - `product_id` (registry: `biz.product.id`) — recommended, `string`
  - `user_id` (registry: `biz.user.id`) — required, `string`
- `order.created` — seen live. An order was accepted and persisted.
  - `amount_cents` (registry: `biz.amount_cents`) — required, `int`
  - `order_id` (registry: `biz.order.id`) — required, `string`
  - `user_id` (registry: `biz.user.id`) — required, `string`
- `order.updated` — not seen in this window. An existing order changed state. (reserved — not yet emitted)
  - `order_id` (registry: `biz.order.id`) — required, `string`
- `payment.authorized` — seen live. A charge succeeded and a payment was persisted.
  - `order_id` (registry: `biz.order.id`) — required, `string`
  - `payment_id` (registry: `biz.payment.id`) — required, `string`
- `payment.declined` — seen live. A charge was declined by validation.
  - `reason` (registry: `app.fail_reason`) — recommended, one of `unknown_product`, `auth`, `auth_failed`, `payment`, `payment_declined`, `user_upstream`, `payment_upstream`, `new_validator`, `new_validator_odd_cents`, `gateway`, `network`, `not_found`, `transient`, `session_store_timeout`
  - `order_id` (registry: `biz.order.id`) — required, `string`
- `payment.gateway_error` — seen live. The (simulated) upstream payment gateway failed.
  - `order_id` (registry: `biz.order.id`) — required, `string`
- `payment.refunded` — not seen in this window. A previously authorized charge was refunded. (reserved — not yet emitted)
  - `order_id` (registry: `biz.order.id`) — recommended, `string`
  - `payment_id` (registry: `biz.payment.id`) — required, `string`
- `payment.requested` — seen live. A charge was requested from payment-service.
  - `amount_cents` (registry: `biz.amount_cents`) — required, `int`
  - `order_id` (registry: `biz.order.id`) — required, `string`
  - `user_id` (registry: `biz.user.id`) — required, `string`
- `user.auth_failed` — seen live. An auth check or user lookup failed.
  - `reason` (registry: `app.fail_reason`) — required, one of `unknown_product`, `auth`, `auth_failed`, `payment`, `payment_declined`, `user_upstream`, `payment_upstream`, `new_validator`, `new_validator_odd_cents`, `gateway`, `network`, `not_found`, `transient`, `session_store_timeout`
  - `user_id` (registry: `biz.user.id`) — required, `string`
- `user.logged_in` — seen live. An auth check passed.
  - `user_id` (registry: `biz.user.id`) — required, `string`
- `user.registered` — not seen in this window. A new user was registered. (reserved — not yet emitted)
  - `user_id` (registry: `biz.user.id`) — required, `string`

## Spans

- `span.app.order.create` — kind `server`. The order-service handling of `POST /api/orders` — create-order business operation.
  - `reason` (registry: `app.fail_reason`) — conditionally required, one of `unknown_product`, `auth`, `auth_failed`, `payment`, `payment_declined`, `user_upstream`, `payment_upstream`, `new_validator`, `new_validator_odd_cents`, `gateway`, `network`, `not_found`, `transient`, `session_store_timeout`
  - `status` (registry: `app.outcome`) — required, one of `created`, `authorized`, `declined`, `cancelled`, `error`
  - `amount_cents` (registry: `biz.amount_cents`) — recommended, `int`
  - `order_id` (registry: `biz.order.id`) — conditionally required, `string`
  - `product_id` (registry: `biz.product.id`) — required, `string`
  - `user_id` (registry: `biz.user.id`) — required, `string`
- `span.app.payment.charge` — kind `server`. The payment-service handling of `POST /charge`.
  - `reason` (registry: `app.fail_reason`) — conditionally required, one of `unknown_product`, `auth`, `auth_failed`, `payment`, `payment_declined`, `user_upstream`, `payment_upstream`, `new_validator`, `new_validator_odd_cents`, `gateway`, `network`, `not_found`, `transient`, `session_store_timeout`
  - `status` (registry: `app.outcome`) — required, one of `created`, `authorized`, `declined`, `cancelled`, `error`
  - `amount_cents` (registry: `biz.amount_cents`) — recommended, `int`
  - `order_id` (registry: `biz.order.id`) — required, `string`
  - `payment_id` (registry: `biz.payment.id`) — conditionally required, `string`
  - `user_id` (registry: `biz.user.id`) — required, `string`
- `span.app.proxy.forward` — kind `client`. An edge/proxy hop (webapp -> api-gateway -> backend). The outbound call that forwards a request to an upstream service.
  - `method` (registry: `app.http.method`) — recommended, one of `GET`, `POST`, `PUT`, `DELETE`
  - `path` (registry: `app.http.route`) — recommended, `string`
  - `upstream` (registry: `app.upstream.service`) — required, `string`
  - `app.upstream.status_code` — conditionally required, `int`
- `span.gen_ai.chat` — kind `client`. A chat-completion call from the agent to Gemini — emitted by the LangChain instrumentor for each LLM turn (RCA graph node, intent gate, findings extractor, follow-up suggester).
  - `gen_ai.operation.name` — required, one of `chat`, `execute_tool`
  - `gen_ai.provider.name` — required, one of `gcp.gen_ai`
  - `gen_ai.request.model` — required, `string`
  - `gen_ai.request.temperature` — recommended, `double`
  - `gen_ai.response.finish_reasons` — recommended, `string[]`
  - `gen_ai.response.model` — recommended, `string`
  - `gen_ai.usage.cache_read.input_tokens` — recommended, `int`
  - `gen_ai.usage.input_tokens` — recommended, `int`
  - `gen_ai.usage.output_tokens` — recommended, `int`
- `span.gen_ai.execute_tool` — kind `internal`. Execution of an RCA tool the model requested during the ReAct loop.
  - `aiops.tool.name` — recommended, one of `query_prometheus`, `query_loki_logs`, `query_tempo_traces`, `discover_metrics`, `discover_span_names`, `discover_log_fields`, `github_compare`, `github_get_file`
  - `gen_ai.operation.name` — required, one of `chat`, `execute_tool`
  - `gen_ai.tool.name` — required, `string`
