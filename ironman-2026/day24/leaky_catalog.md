# Telemetry Schema Catalog — semantics & conventions

This file describes what the signals **mean** and the **conventions** they
follow. It deliberately does **not** list the exhaustive inventory of metrics,
span names or log fields — those drift, and they are supplied live instead:

- A **capability snapshot** is injected per question for the service(s) it's
  about (real metric names + labels, span names, log fields, read just now).
- The `discover_metrics` / `discover_span_names` / `discover_log_fields` tools
  fetch the same on demand for any service.

**Trust the live snapshot over this file for "what exists"** (exact metric /
span / field names). Use this file for "what it means" and how the stack is
wired.

## Services

| service | role | code path (in repo) | git_version |
|---------|------|---------------------|-------------|
| webapp | public edge — receives external HTTP, forwards to api-gateway | `demo-services/services/webapp/` | v5.2.0 |
| api-gateway | thin proxy router to backend services | `demo-services/services/api-gateway/` | v4.0.0 |
| user-service | user lookup + auth check | `demo-services/services/user/` | v1.3.0 |
| order-service | products / cart / orders. Calls user + payment | `demo-services/services/order/` | v3.1.2 |
| payment-service | charges. Has the `payment_use_new_validator` flag | `demo-services/services/payment/` | v2.4.1 |

**All services live in one monorepo: `tedmax100/o11y-bench`** — that is the
`repo` for `github_compare` / `github_get_file` and matches the `git_repo`
label on every signal. **Only `payment-service` currently has real git tags**
(`v2.4.1` → `v2.5.0`); `github_compare` on the other services 404s, so only run
deploy correlation for payment-service.

Dependency edges (caller → callee). The **authoritative, queryable** version of
this graph — plus criticality tier and journey membership — is the Signal Plane
topology (`app/signals/topology.yaml`), injected per-RCA as a "Signal context"
block; **trust that block over this prose** when present. This stays as the
fallback for when signal context isn't injected:

```
webapp → api-gateway
api-gateway → {user-service, order-service, payment-service}
order-service → {user-service, payment-service}
user-service (leaf)        payment-service (leaf)
```

HTTP endpoints (owning service):

| method | path | owner |
|--------|------|-------|
| GET | /api/users, /api/users/{id} | user-service |
| GET | /api/products, /api/cart | order-service |
| POST | /api/orders | order-service |
| POST | /api/payments | payment-service (proxied via api-gateway → `/charge`) |

## Cross-signal conventions

- Every signal carries `service_name`, `git_version` (deployed revision),
  `git_repo` (always `tedmax100/o11y-bench`), and `deployment_environment=demo`.
  `service_version` mirrors `git_version` (OTel semconv); prefer `git_version`
  for cross-signal joins and the GitHub tools.
- **There is no `up{}` for application services.** The OTel Collector pushes via
  remote_write (not scraped), so `up{service_name="..."}` is always empty
  regardless of health. Check liveness with a fresh sample on a counter the
  service emits, e.g. `rate(<some_total>[5m]) > 0`.
- **Loki** — the *only* indexable stream-selector labels are `service_name`,
  `git_repo`, `git_version`, `deployment_environment`. The selector key is
  `service_name` (**NOT `service`** — `{service="..."}` matches nothing).
  Everything else (`event`, `trace_id`, `detected_level`, business fields) is
  **structured metadata**: filter it *after* the selector (e.g.
  `| event="payment.declined"`), never as a `{...}` selector. Do not use
  `service` / `app` / `container` / `pod` / `job` as selectors — not indexed.
- **Log severity / finding "errors"** — these services log business events at
  **INFO**; there is **no `level` field and no ERROR-level lines** for the demo
  incidents. The severity field that exists is `detected_level` / `severity_text`
  (all `info` here). So **find incidents via the `event` field, not severity** —
  e.g. payment declines are `| event="payment.declined"`, gateway failures are
  `| event="payment.gateway_error"`. `| level="ERROR"` matches nothing.
- **Tempo** — resource/span attributes use **dotted** names
  (`resource.service.name`, `span.http.route`, `status`). Trace structure,
  root→leaf: `webapp → api-gateway → <target service> → <dep service>`.
- **Prometheus** — OTel→remote_write with `resource_to_telemetry_conversion`,
  so resource attrs become labels. Histograms are `*_bucket/_sum/_count`
  (use `histogram_quantile` over `_bucket`); counters end `_total`. Always
  aggregate (`sum by (...)`, `topk`) — don't fetch raw per-series.

## BizEvent enum & per-event fields (Loki structured metadata)

`event` is low-cardinality (safe to `sum by (event)`). The values and the extra
fields each carries are domain knowledge, not discoverable from labels alone:

```
payment.requested  payment.authorized  payment.declined  payment.refunded
payment.gateway_error   order.created  order.updated  order.cancelled
user.logged_in  user.registered  user.auth_failed
http.request_received  http.request_failed   cache.miss  deployment.started
```

| event | extra fields |
|-------|--------------|
| `payment.requested` / `payment.authorized` | `order_id`, `user_id`, `amount_cents`, `payment_id` |
| `payment.declined` | `order_id`, `reason` (`new_validator_odd_cents` …) |
| `payment.gateway_error` | `order_id` |
| `order.created` | `order_id`, `user_id`, `amount_cents` |
| `order.cancelled` | `user_id`, `reason` (`auth_failed` / `payment_declined` / `unknown_product`), `upstream_status` |
| `user.logged_in` / `user.auth_failed` | `user_id`, `reason` (`not_found` / `transient`) |
| `http.request_received` | `method`, `path` (template, e.g. `/api/users/{id}`) |
| `http.request_failed` | `upstream`, `status`, `reason` (`network`) |

## Query style (use live names from the snapshot)

```promql
# p95 latency per service (histogram → histogram_quantile over _bucket)
histogram_quantile(0.95, sum by (service_name, le) (rate(<duration>_bucket[5m])))
```
```logql
# incident events per service — services log at INFO; filter by `event`, NOT by
# level (no ERROR level exists). E.g. payment declines:
sum by (service_name) (count_over_time({deployment_environment="demo"} | event="payment.declined" [1h]))
```
```traceql
# errors originating in a service
{ resource.service.name = "<service>" && status = error }
```

### Count vs rate, and where to read git_version

- **"How many / total / volume over the last Nh"** → an **instant** query of
  `sum(count_over_time({...}[Nh]))` (Loki tool: `queryType="instant"`). It returns
  the single total. A **range** query returns one windowed count per step — do
  **not** average/last those into a total (that yields a per-step number, not the
  count). Use range only for trends/charts/raw lines. Same for Prometheus:
  `sum(increase(<counter>[Nh]))` instant for a windowed total; `rate(...)` only
  for a per-second rate or a share.
- **trace_id, level, event, business fields are structured metadata** — they need
  a `{...}` stream selector first: `{service_name="x"} | trace_id="y"`, never
  `trace_id="y"` alone (that's a LogQL parse error).
- **git_version is everywhere** — a label on every metric and log, and on a trace's
  resource as `service.version`. To get the version a failing trace ran on, read
  `resource.service.version` from the trace you already fetched; do **not** go to
  Loki to "look it up". Never cite a git_version or trace_id that isn't in a tool result.

## Feature flags & incident scenarios

**payment-service** has a `payment_use_new_validator` flag (from `flags.json`,
a ConfigMap). Flipping it `true` and bumping `git_version` `v2.4.1` → `v2.5.0`
simulates a bad deploy where odd-cents amounts get declined — `payment.declined`
spikes under `git_version="v2.5.0"` in both Loki (`sum by (git_version, event)`)
and Prometheus (declined charges by `git_version`).

Trigger:

```bash
kubectl -n demo create configmap payment-flags \
  --from-literal=flags.json='{"payment_use_new_validator": true}' \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n demo patch deployment payment-service --type=merge \
  -p '{"spec":{"template":{"metadata":{"labels":{"git_version":"v2.5.0"}}}}}'
```

Other incident scenarios (order latency, user-service cache lag) are **not yet
implemented** — don't claim to find them.

## Deploy correlation

When a spike correlates with a `git_version` boundary:

1. Repo is always `tedmax100/o11y-bench` (also the `git_repo` label).
2. Previous version = the `git_version` value just before the spike (e.g.
   `v2.4.1` if the spike is on `v2.5.0`).
3. `github_compare("tedmax100/o11y-bench", base=<old>, head=<new>)` to see the
   diff (naturally scoped to that service's path).
4. If a suspicious file shows up, `github_get_file(...)` to read the new code.
5. Cite the commit SHA(s) + a one-line summary alongside the telemetry queries.
   Only payment-service has real tags today (see Services).

## Kubernetes (infra signal — the other half of deploy correlation)

The services run as Deployments in namespace **`demo`**, labelled
`app=<service_name>` (e.g. `app=payment-service`); pods also carry `git_version`
as a label. The k8s tools resolve a service to its objects through that label.

Use k8s to separate a **platform** failure from a **code** regression — the
distinction the telemetry alone can't always make:

| Symptom from k8s | Likely cause |
|---|---|
| `OOMKilled` (last_terminated) / rising `restarts` | memory limit too low / leak — infra/config, not logic |
| `CrashLoopBackOff` (waiting_reason) | container can't start (bad config, missing env, panic on boot) |
| `ImagePullBackOff` / `ErrImagePull` | bad image tag / registry — the deploy never ran |
| `ProgressDeadlineExceeded`, `available_replicas < desired` | rollout never went healthy — new version is NOT actually serving |
| `FailedScheduling` / `Evicted` | node resource pressure, not the service's code |

Rule of thumb: if a `git_version` boundary lines up with the incident AND
`k8s_deployment_status` shows the new revision became Available with healthy
replicas, the regression is in the **code** (→ `github_compare`). If the rollout
is stuck or pods are crashing, it's **infra/config** — say so and skip the code
diff. These tools are **read-only**; they never restart, scale, or delete.
