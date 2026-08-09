"""The naive alternative to walking the graph: scan every series Prometheus has
and flag whatever moved.

This is deliberately the *reasonable* version of a flat scan — it only looks at
series that exist right now, it compares against a baseline window instead of a
hardcoded threshold, and it needs a relative move of at least `--min-rel` to
count. It still has no idea which service matters, which service calls which,
or which metric is the authoritative way to judge a service.

Usage (needs a port-forwarded Prometheus on :9090):
    uv run python flat_scan.py --baseline 30m --min-rel 0.5
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request

PROM = "http://localhost:9090"


def q(expr: str, at: float | None = None) -> list[dict]:
    params = {"query": expr}
    if at is not None:
        params["time"] = str(at)
    url = f"{PROM}/api/v1/query?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as r:
        data = json.load(r)
    if data.get("status") != "success":
        return []
    return data["data"]["result"]


# Labels every series carries; they identify the series but say nothing about it.
_BORING = {
    "__name__",
    "job",
    "deployment_environment",
    "service_namespace",
    "git_repo",
    "telemetry_auto_version",
    "telemetry_sdk_language",
    "telemetry_sdk_name",
    "telemetry_sdk_version",
    "net_host_port",
    "http_flavor",
    "http_host",
    "http_scheme",
    "http_server_name",
}


def series_key(metric: dict, family: str) -> str:
    labels = ",".join(f"{k}={v}" for k, v in sorted(metric.items()) if k not in _BORING)
    return f"{family}{{{labels}}}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", default="30m", help="how far back the baseline sample is")
    ap.add_argument("--min-rel", type=float, default=0.5, help="minimum relative change to flag")
    args = ap.parse_args()

    names = json.load(urllib.request.urlopen(f"{PROM}/api/v1/label/__name__/values", timeout=30))[
        "data"
    ]
    now = time.time()
    base_at = now - _seconds(args.baseline)

    # Cumulative families (counters and the _sum/_count sides of histograms) have
    # to go through rate() — comparing their raw value now vs an hour ago would
    # flag literally every series as "rising". _bucket is skipped: it is the same
    # information as _count/_sum, spread over le.
    cumulative = [
        n for n in names if n.endswith(("_total", "_count", "_sum")) and not n.endswith("_bucket")
    ]
    gauges = [n for n in names if n not in cumulative and not n.endswith("_bucket")]

    total_series = 0
    candidates: list[tuple[float, str, float, float]] = []

    for name in cumulative:
        expr = f"rate({name}[5m])"
        cur = {series_key(s["metric"], name): float(s["value"][1]) for s in q(expr)}
        base = {series_key(s["metric"], name): float(s["value"][1]) for s in q(expr, base_at)}
        total_series += len(cur)
        for key, v in cur.items():
            b = base.get(key, 0.0)
            rel = _rel(v, b)
            if rel >= args.min_rel:
                candidates.append((rel, key, b, v))

    for name in gauges:
        cur = {series_key(s["metric"], name): float(s["value"][1]) for s in q(name)}
        base = {series_key(s["metric"], name): float(s["value"][1]) for s in q(name, base_at)}
        total_series += len(cur)
        for key, v in cur.items():
            b = base.get(key, 0.0)
            rel = _rel(v, b)
            if rel >= args.min_rel:
                candidates.append((rel, key, b, v))

    candidates.sort(reverse=True)
    print(f"metric families: {len(names)}  series sampled: {total_series}")
    print(f"anomaly candidates (rel change >= {args.min_rel:.0%}): {len(candidates)}\n")
    for rel, key, b, v in candidates:
        print(f"  {rel:8.1%}  {key}   {b:.4g} -> {v:.4g}")


def _rel(cur: float, base: float) -> float:
    if base == 0 and cur == 0:
        return 0.0
    if base == 0:
        return float("inf")
    return abs(cur - base) / base


def _seconds(s: str) -> float:
    unit = s[-1]
    n = float(s[:-1])
    return n * {"s": 1, "m": 60, "h": 3600}[unit]


if __name__ == "__main__":
    main()
