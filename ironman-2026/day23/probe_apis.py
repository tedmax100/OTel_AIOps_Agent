"""Probe the three native APIs for the quirks the query tools have to absorb.

Every claim in the day's article is one of these probes: the naive call an agent
would make, next to the one that works. Nothing here goes through the agent or
an LLM — the point is that these are properties of Prometheus / Loki / Tempo,
not of the model.

Run from `aiops-agent/service/` with the stack port-forwarded:
    uv run python ../../otel-aiops-agent/ironman-2026/day23/probe_apis.py
"""

from __future__ import annotations

import asyncio
import json

import httpx
from app.config import settings
from app.tools.query import (
    _approx_size,
    _parse_dt,
    _rfc3339,
    _summarize_series_result,
)

SERVICE = "payment-service"


async def _raw(url: str, params: dict) -> tuple[int, str]:
    """The bare HTTP call, no ToolException wrapping — we want to see what the
    API itself says, including the 400 bodies the tools turn into hints."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(url, params=params)
    return r.status_code, r.text


def head(title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


async def prometheus() -> None:
    head("Prometheus — 'what metrics does this service have?'")
    code, body = await _raw(f"{settings.prometheus_url}/api/v1/metadata", {})
    print(f"GET /api/v1/metadata           -> {code} {body[:120]}")
    code, body = await _raw(f"{settings.prometheus_url}/api/v1/targets", {})
    print(f"GET /api/v1/targets            -> {code} {body[:120]}")

    s, e = _parse_dt("now-1h"), _parse_dt("now")
    code, body = await _raw(
        f"{settings.prometheus_url}/api/v1/series",
        {
            "match[]": f'{{service_name="{SERVICE}"}}',
            "start": int(s.timestamp()),
            "end": int(e.timestamp()),
        },
    )
    names = sorted({m.get("__name__") for m in json.loads(body).get("data", [])})
    print(f"GET /api/v1/series?match[]=…   -> {code}, {len(names)} distinct metric name(s)")
    print(f"  {names[:6]}")


async def loki() -> None:
    head("Loki — the same query, two time units")
    s, e = _parse_dt("now-1h"), _parse_dt("now")
    for unit, mult in (("seconds", 1), ("nanoseconds", 1_000_000_000)):
        code, body = await _raw(
            f"{settings.loki_url}/loki/api/v1/detected_fields",
            {
                "query": f'{{service_name="{SERVICE}"}}',
                "start": int(s.timestamp()) * mult,
                "end": int(e.timestamp()) * mult,
            },
        )
        fields = [f.get("label") for f in json.loads(body).get("fields", [])]
        print(f"start/end in {unit:<12} -> {code}, {len(fields)} field(s): {sorted(fields)[:6]}")

    head("Loki — the selector key")
    for sel in (f'{{service="{SERVICE}"}}', f'{{service_name="{SERVICE}"}}'):
        code, body = await _raw(
            f"{settings.loki_url}/loki/api/v1/query_range",
            {
                "query": sel,
                "start": int(s.timestamp() * 1e9),
                "end": int(e.timestamp() * 1e9),
                "limit": 5,
            },
        )
        streams = json.loads(body).get("data", {}).get("result", []) if code < 400 else []
        print(f"{sel:<40} -> {code}, {len(streams)} stream(s)")


async def tempo() -> None:
    head("Tempo — three ways to get it wrong, all of them loud")
    s, e = _parse_dt("now-1h"), _parse_dt("now")
    sec = {"start": int(s.timestamp()), "end": int(e.timestamp())}
    ns = {"start": int(s.timestamp() * 1e9), "end": int(e.timestamp() * 1e9)}
    ok_q = f'{{resource.service.name="{SERVICE}"}}'
    probes = [
        ("start/end in nanoseconds", {"q": ok_q, **ns}),
        ("Loki's label name", {"q": f'{{service_name="{SERVICE}"}}', **sec}),
        (
            "status as a string",
            {"q": f'{{resource.service.name="{SERVICE}" && status="error"}}', **sec},
        ),
        ("the one that works", {"q": ok_q, **sec}),
    ]
    for label, params in probes:
        code, body = await _raw(f"{settings.tempo_url}/api/search", params)
        if code >= 400:
            print(f"{label:<26} -> {code} {body.strip()[:110]}")
        else:
            print(f"{label:<26} -> {code}, {len(json.loads(body).get('traces', []))} trace(s)")


async def payload() -> None:
    head("How big the answer is before anyone reads it")
    expr = (
        "sum by (service_name, http_status_code) "
        "(rate(http_server_duration_milliseconds_count[5m]))"
    )
    for window, step in (("now-6h", 60), ("now-1h", 15)):
        s, e = _parse_dt(window), _parse_dt("now")
        _, body = await _raw(
            f"{settings.prometheus_url}/api/v1/query_range",
            {"query": expr, "start": _rfc3339(s), "end": _rfc3339(e), "step": str(step)},
        )
        raw = json.loads(body)["data"]
        points = len(raw["result"][0]["values"]) if raw["result"] else 0
        summarized = _summarize_series_result(raw)
        print(
            f"{window} step={step}s: {len(raw['result'])} series x {points} points  "
            f"{_approx_size(raw):>6}B -> {_approx_size(summarized):>5}B after summarizing"
        )


async def main() -> None:
    await prometheus()
    await loki()
    await tempo()
    await payload()


if __name__ == "__main__":
    asyncio.run(main())
