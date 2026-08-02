# demo-services

Real Python microservices emitting structured telemetry with the
`git_repo` / `git_version` / `event` schema designed in
[../doc/aiops-agent-design-v2.md](../doc/aiops-agent-design-v2.md).

Runs on **k3d** so we can use [xk6-disruptor](https://github.com/grafana/xk6-disruptor)
for chaos injection. A `docker-compose.yaml` is kept as a no-Kubernetes
fallback (see [Alternative: docker compose](#alternative-docker-compose) below).

## Phase 1 status

What's here right now:

- `shared/` — `o11y_shared` lib: OTel bootstrap (traces/metrics/logs),
  JSON logger with the demo schema, `BizEvent` enum, feature flag reader.
- `services/payment/` — one real FastAPI service (`payment-service`),
  in-memory, fully instrumented. Single endpoint: `POST /charge`.
- `k8s/` — manifests for payment + OTel Collector + Prometheus + Loki +
  Tempo + Grafana under namespace `demo`.
- `disruptor/` — sample xk6-disruptor scenario (`payment-latency.js`).

Not here yet (Phase 2+):

- The other 4 services (webapp, api-gateway, user, order)
- Inter-service traffic + load generator
- More incident scenarios

## Layout

```
demo-services/
  pyproject.toml              # uv workspace root
  shared/                     # o11y_shared library
  services/payment/           # payment-service (FastAPI + OTel)
  k8s/                        # cluster.yaml + manifests
    cluster.yaml              # k3d cluster definition
    00-namespace.yaml
    10-prometheus.yaml
    11-loki.yaml
    12-tempo.yaml
    13-otel-collector.yaml
    14-grafana.yaml
    20-payment-service.yaml
  scripts/                    # up.sh / down.sh / build.sh
  disruptor/                  # xk6-disruptor scripts
  flags.json                  # runtime feature flag (docker-compose path only)
  docker-compose.yaml         # fallback for non-k8s use
```

## Quick start (k3d)

Prereqs: `docker`, `k3d`, `kubectl`, `uv`.

```bash
cd demo-services
./scripts/up.sh
```

This will:
1. Create a k3d cluster named `demo-services` with host ports
   `3001→Grafana`, `8001→payment`, `14318→otel-collector` (4318 is often
   taken by an unrelated host-side collector).
2. Build the `demo-services/payment:dev` image and `k3d image import` it.
3. Apply all manifests under `k8s/`.
4. Wait for every pod in namespace `demo` to be ready.

Send a request:

```bash
curl -X POST http://localhost:8001/charge \
  -H 'content-type: application/json' \
  -d '{"order_id":"o-1","user_id":"u-1","amount_cents":1000}'
```

Open Grafana at <http://localhost:3001>.

Tear down:

```bash
./scripts/down.sh
```

## Telemetry standard (repo + version on every signal)

Every service stamps the same identity onto **all three signals** (traces,
metrics, logs) so the AIOps agent can pivot between them and correlate a spike
to a code change. The standard is four resource attributes:

| attribute | example | purpose |
|-----------|---------|---------|
| `service.name` | `payment-service` | OTel semconv service identity (→ Loki/Prom `service_name`) |
| `service.version` | `v2.4.1` | **OTel semconv** version — for standard tooling that keys on `service.version` |
| `git_version` | `v2.4.1` | same value as `service.version`; the **join key** for cross-signal + GitHub correlation |
| `git_repo` | `tedmax100/o11y-bench` | `owner/repo` (the monorepo) for the agent's `github_compare` / `github_get_file` tools |

`git_version` is a valid GitHub ref (tag), so the agent can read it off any
signal and immediately `github_compare` the suspect deploy. `git_repo` saves it
maintaining a service→repo table.

### Single source of truth

The version literal lives in **exactly one place per service**: the pod-template
`git_version` label. Everything else is derived, so a version bump is a one-line
change (and the bad-deploy demo below relies on this):

```
spec.template.metadata.labels.git_version          ← the only literal
        │  Downward API (fieldRef)
        ▼
   env GIT_VERSION                                  ← read by the stdout JSON logger too
        │  k8s $(VAR) interpolation
        ▼
   OTEL_RESOURCE_ATTRIBUTES                         ← service.version=$(GIT_VERSION),
   = ...,git_version=$(GIT_VERSION),...                 git_version=$(GIT_VERSION), git_repo=$(GIT_REPO)
```

`GIT_REPO` is the only other literal (it never changes on deploy). See any
manifest, e.g. [k8s/20-payment-service.yaml](k8s/20-payment-service.yaml).

### Where each attribute lands

| signal | mechanism | result |
|--------|-----------|--------|
| **Metrics** (Prometheus) | `resource_to_telemetry_conversion: true` promotes all resource attrs → labels | `git_version`, `service_version`, `git_repo` labels on every series |
| **Traces** (Tempo) | resource attrs are queryable | `resource.git_version`, `resource.service.version`, `resource.git_repo` |
| **Logs — OTLP** (Loki) | `11-loki.yaml` promotes a fixed list to stream labels | `git_version` / `git_repo` indexed; `service.version` flows as a non-indexed resource attr (kept out of the index to avoid cardinality dup with `git_version`) |
| **Logs — stdout JSON** | `o11y_shared` logger reads `GIT_REPO` / `GIT_VERSION` env | `git_repo` / `git_version` fields on each line |

### Bumping a version

Patch the pod-template label only — the rollout carries it everywhere:

```bash
kubectl -n demo patch deployment <svc> --type=merge \
  -p '{"spec":{"template":{"metadata":{"labels":{"git_version":"vX.Y.Z"}}}}}'
```

> **docker-compose caveat:** Compose has no Downward API / `$(VAR)`
> interpolation, so `docker-compose.yaml` spells `OTEL_RESOURCE_ATTRIBUTES`
> out and you must keep `service.version` / `git_version` in sync with
> `GIT_VERSION` by hand there.

## Smoke verification (the schema is the point)

In Grafana → Explore → **Loki**:

```logql
{service_name="payment-service"} | json
```

Each line must contain `git_repo`, `git_version`, `event` fields. If they're
missing, the OTel pipeline is wrong somewhere. (Note: Loki promotes resource
attributes with the OTel naming, so `service.name` becomes `service_name`.)

Group by event and version — the aggregation the AIOps agent will rely on:

```logql
sum by (event, git_version) (
  count_over_time({service_name="payment-service"} [5m])
)
```

In Grafana → Explore → **Prometheus**:

```promql
sum by (git_version) (rate(payment_charges_total[5m]))
```

The result must have `git_version="v2.4.1"` as a label. That proves the
resource attr made it through OTel Collector → Prometheus remote write. The
same series should now also carry `service_version="v2.4.1"` (the semconv
mirror) — confirm with:

```promql
sum by (service_version) (rate(payment_charges_total[5m]))
```

## Triggering the "bad deploy" demo

Two changes — flip the flag, bump `git_version`:

```bash
kubectl -n demo create configmap payment-flags \
  --from-literal=flags.json='{"payment_use_new_validator": true}' \
  --dry-run=client -o yaml | kubectl apply -f -

# Bump the version by patching the pod-template git_version label — the single
# source of truth. This triggers a rollout; the new pods carry the label, the
# GIT_VERSION env is derived from it via the Downward API, and every signal
# (logs / metrics / traces) plus disruptor pod-selection follow automatically.
kubectl -n demo patch deployment payment-service --type=merge \
  -p '{"spec":{"template":{"metadata":{"labels":{"git_version":"v2.5.0"}}}}}'
```

Now odd-cents amounts get declined. Run an LogQL query grouping by
`(event, git_version)` and you'll see `payment.declined` appear under
`v2.5.0` while staying near zero on `v2.4.1`.

## Chaos: xk6-disruptor

See [disruptor/README.md](disruptor/README.md) for install + a sample
scenario that injects 500ms latency on `payment-service` for 60s. The
disruptor targets pods by label (`app=payment-service`), so any service
following the label convention can be hit by the same scripts.

## Scaling notes — workers=1 is deliberate

Each pod runs `opentelemetry-instrument uvicorn ...` with **uvicorn's
default of 1 worker**. Do not bump `--workers N`. Scale via Kubernetes
replicas (or HPA) instead.

Why: `opentelemetry-instrument` initialises the OTel SDK in the master
process — including the `BatchSpanProcessor`, `PeriodicExportingMetric
Reader`, and `BatchLogRecordProcessor` background threads. When uvicorn
forks worker processes, **POSIX fork only copies the calling thread**, so
those export threads die in every child. The provider objects still exist,
so calls to `tracer.start_as_current_span(...)` succeed, but spans pile up
in the batch queue and never reach the collector. After a few minutes the
queue is full and new spans get silently dropped.

Symptoms if someone ignores this:

- Span count in Grafana flatlines an unpredictable time after pod startup
- Log/metric exports stop with no error in pod logs
- `otelcol_receiver_accepted_spans` on the collector stops increasing
  while the app keeps serving requests normally

If you genuinely need multi-worker-per-pod (you probably don't on k3d),
the only safe pattern is `gunicorn -k uvicorn.workers.UvicornWorker -w N`
with `--preload` **disabled** so each worker re-runs SDK init in its own
process. That defeats most of the value of `opentelemetry-instrument` —
keep workers=1 and let k8s do the scaling.

## Phase 2 plan

- [ ] Replicate the template to the other 4 services
- [ ] Inter-service httpx calls with trace propagation
- [ ] Simple load generator (Python script or `oha` job)
- [ ] Wire `aiops-agent/` to point at this cluster's Grafana

## Alternative: docker compose

For a quick test without a Kubernetes cluster, the original
`docker-compose.yaml` is still here:

```bash
docker compose up --build
# ports: Grafana 3001, payment 8001, OTLP 4318
```

xk6-disruptor does **not** work in this mode (it requires Kubernetes).
