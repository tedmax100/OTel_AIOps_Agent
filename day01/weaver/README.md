# Weaver registry — demo-services telemetry conventions

A [OpenTelemetry Weaver](https://github.com/open-telemetry/weaver) semantic
convention registry that governs the telemetry emitted by the demo-services
across **all three signals**:

| Signal | Modeled in | What it covers |
|---|---|---|
| **Metrics** | `registry/model/metrics.yaml` | `orders_total`, `payment_charges_total`, the duration histograms, `user_lookups_total`, `user_auth_checks_total` + their labels |
| **Logs (events)** | `registry/model/events.yaml` | every `BizEvent` from `o11y_shared.events` + the structured `extra={...}` fields each carries |
| **Traces (spans)** | `registry/model/spans.yaml` | the business operations (order create / payment charge / proxy hop) |
| **GenAI** | `registry/model/genai.yaml` | the `aiops-agent`'s own telemetry — `gen_ai.*` LLM/tool spans + `gen_ai.client.*` token/duration metrics, plus the agent-specific `aiops.*` attributes |
| _shared_ | `registry/model/common.yaml` | the `app.*` / `biz.*` attributes + resource (`vcs.repository.url.full`, `service.version`) |

The **GenAI** rows come from the aiops-agent running under
`opentelemetry-instrument` with `opentelemetry-instrumentation-langchain` — the
observer is observed too. Verified against the live agent: the instrumentor
emits the official OpenTelemetry `gen_ai.*` names directly
(`gen_ai.provider.name`, `gen_ai.usage.input_tokens`/`output_tokens`,
`gen_ai.operation.name`, …) plus `gen_ai.usage.cache_read.input_tokens` for
Gemini context-cache hits — so there's effectively no naming delta to migrate.

This registry is **self-contained** (no dependency on the upstream
semantic-conventions model) so it validates fully offline.

## Run it

No local install needed — everything goes through the pinned `otel/weaver`
container via `../scripts/weaver.sh` (needs Docker running):

```bash
# from repo root
mise run weaver:check          # built-in + custom policies
mise run weaver:docs           # generate Markdown docs (needs templates, see below)

# or directly
bash demo-services/scripts/weaver.sh check            # built-in policies only
bash demo-services/scripts/weaver.sh check --policy   # + policies/biz_policies.rego
```

CI runs `weaver:check` on every PR (`.github/workflows/ci.yml` → **Weaver
Registry** job).

## This registry is the *target* standard, not a mirror of today's code

The attribute names here are **idiomatic and namespaced** (`app.*` for
low-cardinality request-shape attributes, `biz.*` for high-cardinality
business identifiers). The services currently emit **flat keys**. The mapping:

| Current flat key | Registry attribute | Signal |
|---|---|---|
| `event` (log attr) | event *name* (`app.event` as fallback attr) | log |
| `status` (metric label) | `app.outcome` | metric/span |
| `status` (gateway/webapp log, an HTTP int) | `app.upstream.status_code` | log ⚠️ see below |
| `reason` | `app.fail_reason` | metric/log/span |
| `op` | `app.user.operation` | metric |
| `upstream` | `app.upstream.service` | log/span |
| `upstream_status` | `app.upstream.status_code` | log |
| `path` | `app.http.route` | log |
| `method` | `app.http.method` | log |
| `user_id` / `order_id` / `product_id` / `payment_id` | `biz.user.id` / `biz.order.id` / `biz.product.id` / `biz.payment.id` | log/span |
| `amount_cents` | `biz.amount_cents` | log/span |
| `git_repo` / `git_version` (resource) | `vcs.repository.url.full` / `service.version` | resource |

Because of this gap, `weaver registry live-check` against the **running** demo
will currently report the flat keys as non-conforming — that report *is* the
migration checklist. Closing it (renaming keys in `o11y_shared` + the five
services) is deliberately left to a follow-up, since those keys are promoted to
Loki/Prometheus labels and changing them touches dashboards + grading queries.

### Findings surfaced while modeling

- **`status` means two different things.** On metrics it's a business outcome
  enum (`created`/`authorized`/…); in `api-gateway` and `webapp` logs it's an
  **HTTP status integer** (`status=resp.status_code`). The registry splits
  these into `app.outcome` (enum) and `app.upstream.status_code` (int). The
  two log sites should switch to the latter.
- **`reason` is a wide, mixed enum.** Its values span metric-label reasons
  (`auth`, `payment`) and log-only reasons (`auth_failed`, `new_validator_odd_cents`).
  Modeled as one open enum for now; worth splitting metric vs log reasons later.

## Custom policy

`policies/biz_policies.rego` enforces the rule the `o11y_shared.events`
docstring asks for in prose:

> high-cardinality `biz.*` identifiers **must not** be used as metric labels.

It fires (`weaver registry check ... -p policies`) if any `metric` group ever
`ref`s a `biz.*` attribute — guarding against label-cardinality blow-ups as
the registry grows.

## Layout

```
weaver/
  registry/
    manifest.yaml            # registry metadata (name, schema_url)
    model/
      common.yaml            # app.* / biz.* attributes + resource group
      metrics.yaml           # metric conventions
      events.yaml            # event (log) conventions
      spans.yaml             # span conventions
  policies/
    biz_policies.rego        # custom cardinality policy
  README.md
```

## Next steps (not in this PR)

1. `weaver registry generate` with Jinja templates to emit `events.py` /
   attribute constants from the registry (single source of truth). Add
   `templates/registry/markdown/` for `weaver:docs`.
2. Migrate the services to the namespaced keys so `live-check` goes green.
3. `weaver registry live-check` wired against the running demo to catch
   undeclared attributes (cardinality drift) in CI.
