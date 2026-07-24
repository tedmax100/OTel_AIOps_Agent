#!/usr/bin/env python3
"""
Demo-schema telemetry generator for the demo-services o11y-bench PoC.

Forks the o11y-bench o11y-stack generator but emits the **demo-services flat
schema** (the conventions the aiops-agent's schema_catalog.md actually queries),
not the upstream http_requests_total/job schema. Reuses the proven write path:
OpenMetrics text -> `promtool tsdb create-blocks-from`, Loki push API, OTLP HTTP
to Tempo, deterministic seed.

Single incident (documented in schema_catalog.md §Feature flags):
  payment-service `payment_use_new_validator` flips true + git_version
  v2.4.1 -> v2.5.0 ~3h before data-end. The new validator declines odd-cent
  amounts, so `payment.declined` (reason=new_validator_odd_cents) spikes under
  git_version="v2.5.0" across metrics, logs and traces.

Schema (flat code names, per demo-services/weaver/registry):
  metrics: payment_charges_total{service_name,git_version,git_repo,
           deployment_environment,status,reason}  (counter)
           payment_charge_duration_seconds_{bucket,sum,count}{...,git_version}
  logs:    JSON lines; Loki stream labels = service_name/git_repo/git_version/
           deployment_environment; level/event/reason/trace_id as structured
           metadata AND in the JSON body (so both `| level="ERROR"` and
           `| json | event=...` work).
  traces:  webapp -> api-gateway -> payment-service; error span status=2 on the
           payment-service span when the charge failed; resource carries
           service.name + service.version(git_version) + deployment.environment.
"""

import json
import os
import random
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta

LOKI_URL = "http://localhost:3100"
TEMPO_URL = "http://localhost:4318"  # OTLP HTTP ingest
TEMPO_QUERY_URL = "http://localhost:3200"
PROMETHEUS_DATA_DIR = "/prometheus"
_OTLP_HEALTH_BODY = b'{"resourceSpans":[]}'

HOURS_OF_HISTORY = 24
METRICS_INTERVAL = 30  # seconds between metric samples
CHARGES_PER_MIN = 8

GIT_REPO = "tedmax100/o11y-bench"
DEPLOY_ENV = "demo"
SERVICE = "payment-service"
VERSION_OLD = "v2.4.1"
VERSION_NEW = "v2.5.0"
ROUTE = "/api/payments"

# Duration histogram buckets in SECONDS (explicit — avoids the default-ms-bucket
# constant-quantile artifact noted in memory/histogram_seconds_default_buckets).
HISTOGRAM_BUCKETS = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]

# Set False if the stack's Loki rejects structured-metadata (3-tuple) pushes;
# fields still live in the JSON body so `| json | ...` keeps working.
USE_STRUCTURED_METADATA = True


def log(msg: str) -> None:
    print(f"[generate_data] {msg}", flush=True)


def rand_hex(n: int) -> str:
    return "".join(f"{random.randint(0, 255):02x}" for _ in range(n // 2 + 1))[:n]


def rand_trace_id() -> str:
    # 32 hex chars with a non-zero leading nibble, so Tempo's search API doesn't
    # trim leading zeros and return a <32-char id (which the grading grounding
    # regex `[0-9a-fA-F]{31,32}` would then reject).
    return f"{random.randint(1, 15):x}" + rand_hex(31)


def data_end_time_utc() -> datetime:
    raw = os.environ.get("O11Y_SCENARIO_TIME_ISO", "").strip()
    if not raw:
        return datetime.now(UTC).replace(microsecond=0)
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)


# -- OTLP / Loki write path (ported from upstream generator) -----------------


def create_span(
    trace_id,
    span_id,
    parent,
    service,
    op,
    start_ns,
    dur_ns,
    version,
    status_code,
    error=False,
    kind=2,
):
    attrs = [
        {"key": "service.name", "value": {"stringValue": service}},
        {"key": "service.version", "value": {"stringValue": version}},
        {"key": "deployment.environment", "value": {"stringValue": DEPLOY_ENV}},
        {"key": "http.method", "value": {"stringValue": "POST"}},
        {"key": "http.route", "value": {"stringValue": ROUTE}},
        {"key": "http.status_code", "value": {"intValue": str(status_code)}},
    ]
    span = {
        "traceId": trace_id,
        "spanId": span_id,
        "name": op,
        "kind": kind,
        "startTimeUnixNano": str(start_ns),
        "endTimeUnixNano": str(start_ns + dur_ns),
        "attributes": attrs,
        "status": {"code": 2 if error else 0},
    }
    if parent:
        span["parentSpanId"] = parent
    return span


def build_payment_trace(trace_id, ts, version, failed, dur_ms):
    """webapp -> api-gateway -> payment-service. Error originates at the
    payment-service span (status=2); upstream spans carry the 5xx code only."""
    http_status = 402 if failed else 200
    start_ns = int(ts.timestamp() * 1e9)
    spans = []
    root = rand_hex(16)
    root_dur = int(dur_ms * 1e6 * random.uniform(1.0, 1.2))
    spans.append(
        create_span(
            trace_id,
            root,
            None,
            "webapp",
            f"POST {ROUTE}",
            start_ns,
            root_dur,
            "v5.2.0",
            http_status,
            error=False,
        )
    )
    gw = rand_hex(16)
    gw_start = start_ns + int(2e6)
    gw_dur = int(root_dur * 0.9)
    spans.append(
        create_span(
            trace_id,
            gw,
            root,
            "api-gateway",
            f"route {ROUTE}",
            gw_start,
            gw_dur,
            "v4.0.0",
            http_status,
            error=False,
        )
    )
    pay = rand_hex(16)
    pay_start = gw_start + int(1e6)
    pay_dur = int(gw_dur * 0.8)
    spans.append(
        create_span(
            trace_id,
            pay,
            gw,
            SERVICE,
            f"handle POST {ROUTE}",
            pay_start,
            pay_dur,
            version,
            http_status,
            error=failed,
        )
    )
    return spans


def push_traces_batch(spans, retries=3):
    if not spans:
        return
    by_service = {}
    for s in spans:
        svc = next(a["value"]["stringValue"] for a in s["attributes"] if a["key"] == "service.name")
        # resource = service.name + service.version + deployment.environment
        ver = next(
            a["value"]["stringValue"] for a in s["attributes"] if a["key"] == "service.version"
        )
        key = (svc, ver)
        by_service.setdefault(key, []).append(s)
    resource_spans = [
        {
            "resource": {
                "attributes": [
                    {"key": "service.name", "value": {"stringValue": svc}},
                    {"key": "service.version", "value": {"stringValue": ver}},
                    {"key": "deployment.environment", "value": {"stringValue": DEPLOY_ENV}},
                ]
            },
            "scopeSpans": [{"scope": {"name": "demo-o11y"}, "spans": sp}],
        }
        for (svc, ver), sp in by_service.items()
    ]
    payload = json.dumps({"resourceSpans": resource_spans}).encode()
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                f"{TEMPO_URL}/v1/traces", data=payload, headers={"Content-Type": "application/json"}
            )
            urllib.request.urlopen(req, timeout=10)
            return
        except urllib.error.HTTPError as exc:
            if exc.code == 503 and attempt < retries - 1:
                time.sleep(0.5)
                continue
            return
        except Exception:
            return


def push_logs_batch(logs):
    if not logs:
        return
    streams = {}
    for e in logs:
        key = json.dumps(e["labels"], sort_keys=True)
        streams.setdefault(key, {"stream": e["labels"], "values": []})
        if USE_STRUCTURED_METADATA and e.get("metadata"):
            streams[key]["values"].append([str(e["ts_ns"]), e["line"], e["metadata"]])
        else:
            streams[key]["values"].append([str(e["ts_ns"]), e["line"]])
    for st in streams.values():
        st["values"].sort(key=lambda v: int(v[0]))
    try:
        req = urllib.request.Request(
            f"{LOKI_URL}/loki/api/v1/push",
            data=json.dumps({"streams": list(streams.values())}).encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as exc:
        log(f"  Loki push error: {exc}")


def build_log(ts, version, level, event, fields):
    line = {
        "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z",
        "level": level,
        "service_name": SERVICE,
        "git_version": version,
        "event": event,
        **fields,
    }
    md = {"level": level, "event": event, "service_name": SERVICE}
    if "trace_id" in fields:
        md["trace_id"] = fields["trace_id"]
    if "reason" in fields:
        md["reason"] = str(fields["reason"])
    return {
        "ts_ns": int(ts.timestamp() * 1e9),
        "labels": {
            "service_name": SERVICE,
            "git_repo": GIT_REPO,
            "git_version": version,
            "deployment_environment": DEPLOY_ENV,
        },
        "line": json.dumps(line),
        "metadata": md,
    }


def wait_for_tempo(max_attempts=30):
    for attempt in range(max_attempts):
        try:
            urllib.request.urlopen(
                urllib.request.Request(
                    f"{TEMPO_URL}/v1/traces",
                    data=_OTLP_HEALTH_BODY,
                    headers={"Content-Type": "application/json"},
                ),
                timeout=5,
            )
            return
        except Exception as exc:
            if attempt == max_attempts - 1:
                raise RuntimeError("Tempo OTLP never ready") from exc
            time.sleep(1)


def flush_tempo(max_attempts=5):
    req = urllib.request.Request(f"{TEMPO_QUERY_URL}/flush", data=b"", method="POST")
    for attempt in range(max_attempts):
        try:
            urllib.request.urlopen(req, timeout=10)
            return
        except Exception as exc:
            if attempt == max_attempts - 1:
                raise RuntimeError("Tempo flush failed") from exc
            time.sleep(1)


def wait_for_tempo_searchable(end_time, max_attempts=30):
    start_s = int((end_time - timedelta(hours=HOURS_OF_HISTORY)).timestamp())
    end_s = int(end_time.timestamp()) + 60
    import urllib.parse as up

    q = up.urlencode(
        {
            "q": f'{{ resource.service.name = "{SERVICE}" }}',
            "start": start_s,
            "end": end_s,
            "limit": 5,
        }
    )
    for attempt in range(max_attempts):
        try:
            with urllib.request.urlopen(f"{TEMPO_QUERY_URL}/api/search?{q}", timeout=10) as r:
                if json.load(r).get("traces"):
                    return
        except Exception:
            pass
        time.sleep(2)
    log("  WARN: Tempo search not confirmed searchable (continuing)")


# -- Incident model ----------------------------------------------------------


def charge_outcome(ts, amount_cents, deploy_time):
    """Returns (git_version, status, reason|None, level, event)."""
    if ts >= deploy_time:
        v = VERSION_NEW
        if amount_cents % 2 == 1:  # new validator rejects odd-cent amounts
            return v, "declined", "new_validator_odd_cents", "WARN", "payment.declined"
        if random.random() < 0.02:
            return v, "error", "gateway", "ERROR", "payment.gateway_error"
        return v, "authorized", None, "INFO", "payment.authorized"
    v = VERSION_OLD
    if random.random() < 0.02:
        return v, "declined", "payment", "WARN", "payment.declined"
    if random.random() < 0.01:
        return v, "error", "gateway", "ERROR", "payment.gateway_error"
    return v, "authorized", None, "INFO", "payment.authorized"


def metric_labels(version, status, reason):
    base = (
        f'service_name="{SERVICE}",git_repo="{GIT_REPO}",'
        f'deployment_environment="{DEPLOY_ENV}",git_version="{version}"'
    )
    out = f'{base},status="{status}"'
    if reason is not None:
        out += f',reason="{reason}"'
    return out


# -- Main generation ---------------------------------------------------------


def generate_all():
    end_time = data_end_time_utc()
    start_time = end_time - timedelta(hours=HOURS_OF_HISTORY)
    deploy_time = end_time - timedelta(hours=3)
    log(
        f"window {start_time:%Y-%m-%dT%H:%M:%SZ} .. {end_time:%Y-%m-%dT%H:%M:%SZ}; "
        f"deploy {VERSION_OLD}->{VERSION_NEW} at {deploy_time:%H:%M:%S}"
    )
    wait_for_tempo()

    charge_counters = {}  # metric_labels-string -> cumulative count
    # histogram per (version): cumulative bucket counts + sum + count
    hist = {
        VERSION_OLD: {"buckets": [0] * len(HISTOGRAM_BUCKETS), "inf": 0, "sum": 0.0, "n": 0},
        VERSION_NEW: {"buckets": [0] * len(HISTOGRAM_BUCKETS), "inf": 0, "sum": 0.0, "n": 0},
    }

    log_batch, trace_batch = [], []
    metrics_file = "/tmp/metrics.txt"
    total_charges = total_traces = total_logs = 0

    import bisect

    mf = open(metrics_file, "w", buffering=1024 * 1024)
    mf.write(
        "# TYPE payment_charges_total counter\n# TYPE payment_charge_duration_seconds histogram\n"
    )

    current = start_time
    last_minute = None
    deploy_logged = False
    while current < end_time:
        ts_epoch = current.timestamp()
        minute = int(ts_epoch) // 60

        if minute != last_minute:
            last_minute = minute
            # deployment.started log at the boundary
            if not deploy_logged and current >= deploy_time:
                deploy_logged = True
                log_batch.append(
                    build_log(
                        current,
                        VERSION_NEW,
                        "INFO",
                        "deployment.started",
                        {
                            "message": f"deployment started: {SERVICE} "
                            f"{VERSION_OLD} -> {VERSION_NEW}",
                            "version": VERSION_NEW,
                        },
                    )
                )
                total_logs += 1

            for _ in range(CHARGES_PER_MIN):
                req_ts = current + timedelta(seconds=random.uniform(0, 59))
                amount = random.randint(100, 5000)
                version, status, reason, level, event = charge_outcome(req_ts, amount, deploy_time)
                failed = status in ("declined", "error")
                dur_ms = random.uniform(10, 30) if failed else random.uniform(30, 90)
                dur_s = dur_ms / 1000.0
                trace_id = rand_trace_id()
                order_id = "o-" + rand_hex(8)

                # metric counter
                lbl = metric_labels(version, status, reason)
                charge_counters[lbl] = charge_counters.get(lbl, 0) + 1
                # histogram
                h = hist[version]
                idx = bisect.bisect_left(HISTOGRAM_BUCKETS, dur_s)
                if idx < len(HISTOGRAM_BUCKETS):
                    h["buckets"][idx] += 1
                else:
                    h["inf"] += 1
                h["sum"] += dur_s
                h["n"] += 1

                # logs: requested + outcome
                log_batch.append(
                    build_log(
                        req_ts,
                        version,
                        "INFO",
                        "payment.requested",
                        {
                            "order_id": order_id,
                            "amount_cents": amount,
                            "trace_id": trace_id,
                            "message": "charge requested",
                        },
                    )
                )
                fields = {"order_id": order_id, "amount_cents": amount, "trace_id": trace_id}
                if reason is not None:
                    fields["reason"] = reason
                fields["message"] = (
                    "charge authorized" if status == "authorized" else f"charge {status}: {reason}"
                )
                if status in ("error",):
                    fields["status"] = 502
                log_batch.append(build_log(req_ts, version, level, event, fields))
                total_logs += 2

                # trace (sample non-failed at 30%; always emit failed so they're findable)
                if failed or random.random() < 0.3:
                    trace_batch.extend(
                        build_payment_trace(trace_id, req_ts, version, failed, dur_ms)
                    )
                    total_traces += 1
                total_charges += 1

        # metric snapshot
        ts = f" {ts_epoch}\n"
        for lbl, val in charge_counters.items():
            mf.write(f"payment_charges_total{{{lbl}}} {val}{ts}")
        for version, h in hist.items():
            vlbl = (
                f'service_name="{SERVICE}",git_repo="{GIT_REPO}",'
                f'deployment_environment="{DEPLOY_ENV}",git_version="{version}"'
            )
            cum = 0
            for i, le in enumerate(HISTOGRAM_BUCKETS):
                cum += h["buckets"][i]
                mf.write(f'payment_charge_duration_seconds_bucket{{{vlbl},le="{le}"}} {cum}{ts}')
            cum += h["inf"]
            mf.write(f'payment_charge_duration_seconds_bucket{{{vlbl},le="+Inf"}} {cum}{ts}')
            mf.write(f"payment_charge_duration_seconds_sum{{{vlbl}}} {h['sum']:.3f}{ts}")
            mf.write(f"payment_charge_duration_seconds_count{{{vlbl}}} {h['n']}{ts}")

        if len(trace_batch) >= 200:
            push_traces_batch(trace_batch)
            trace_batch = []
        if len(log_batch) >= 5000:
            push_logs_batch(log_batch)
            log_batch = []
        current += timedelta(seconds=METRICS_INTERVAL)

    mf.write("# EOF\n")
    mf.close()
    if trace_batch:
        push_traces_batch(trace_batch)
    if log_batch:
        push_logs_batch(log_batch)

    log(
        f"  charges={total_charges} traces={total_traces} logs={total_logs} "
        f"series={len(charge_counters)}"
    )
    log("  flushing Tempo + waiting for searchable...")
    flush_tempo()
    wait_for_tempo_searchable(end_time)

    log("  importing metrics into Prometheus TSDB via promtool...")
    res = subprocess.run(
        [
            "promtool",
            "tsdb",
            "create-blocks-from",
            "openmetrics",
            metrics_file,
            PROMETHEUS_DATA_DIR,
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if res.returncode != 0:
        log(f"  promtool failed rc={res.returncode}: {res.stderr[:500]}")
        raise SystemExit(1)
    log("  metrics import complete")
    try:
        os.remove(metrics_file)
    except Exception:
        pass
    with open("/tmp/env_timestamp", "w") as f:
        f.write(end_time.strftime("%Y-%m-%dT%H:%M:%SZ"))


def main():
    random.seed(42)
    log("=" * 50)
    log("demo-schema telemetry generator (payment bad-deploy PoC)")
    log("=" * 50)
    t = time.time()
    generate_all()
    log(f"done in {time.time() - t:.1f}s")


if __name__ == "__main__":
    main()
