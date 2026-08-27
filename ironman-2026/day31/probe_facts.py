"""Ask the three stores for things that are not there, then read the verdict.

Three sections, none of which call an LLM:

  1. what "nothing" looks like coming out of Prometheus / Loki / Tempo / k8s,
     and what `app/facts.py` types each one as
  2. the ledger those verdicts add up to, which is the block the model is handed
  3. the guard: the same answer, judged against an empty turn and a real one

Section 1 talks to the live stack, so port-forward first and have some traffic
running — every payload printed is one that just came back, and a store with no
recent data answers empty for the right query too, which the output will show
rather than hide.

Run from `aiops-agent/service/`:
    uv run python ../../otel-aiops-agent/ironman-2026/day31/probe_facts.py
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from app.facts import classify, grounding_check, ledger
from app.tools.k8s import get_pod_status
from app.tools.query import _query_loki_logs, _query_prometheus, _query_tempo_traces

RULE = "=" * 72

# Queries that are syntactically fine and answer nothing, next to one that does.
# The wrong ones are not inventions: each is a real mistake out of an eval
# transcript (a metric that is never emitted, Loki's selector key, a retention
# window that has already closed).
PROBES: list[tuple[str, str, object]] = [
    (
        "Prometheus, a metric this stack never emits",
        "query_prometheus",
        lambda: _query_prometheus("sum(rate(payment_declines_total[5m]))", queryType="instant"),
    ),
    (
        "Prometheus, a metric it does emit",
        "query_prometheus",
        lambda: _query_prometheus(
            "sum by (service_name) (rate(http_server_duration_milliseconds_count[5m]))",
            queryType="instant",
        ),
    ),
    (
        "Loki, `service` instead of `service_name`",
        "query_loki_logs",
        lambda: _query_loki_logs('{service="payment-service"}', start="now-1h"),
    ),
    (
        "Loki, the selector that indexes",
        "query_loki_logs",
        lambda: _query_loki_logs(
            'sum(count_over_time({service_name="payment-service"}[1h]))', start="now-1h"
        ),
    ),
    (
        "Tempo, a window that is past retention",
        "query_tempo_traces",
        lambda: _query_tempo_traces(
            '{ resource.service.name="payment-service" }', start="now-24h", end="now-23h"
        ),
    ),
    (
        "Tempo, the last hour",
        "query_tempo_traces",
        lambda: _query_tempo_traces('{ resource.service.name="payment-service" }', start="now-1h"),
    ),
    (
        "k8s, a service that does not exist",
        "k8s_pod_status_tool",
        lambda: get_pod_status("billing-service"),
    ),
    (
        "the catalog, which is never evidence",
        "discover_metrics_tool",
        None,  # filled in below; import is local so the probe still runs without it
    ),
]


async def _run(call: Callable[[], Awaitable[Any]]) -> tuple[Any, str]:
    """Return (payload, provenance). A tool that raises is a payload too — that
    is what the model sees, and the classifier has to read it the same way."""
    try:
        return await call(), "live"
    except Exception as e:
        return f"{type(e).__name__}: {e}", "live (raised)"


async def section_one() -> list:
    from app.tools.discovery import discover_metrics

    PROBES[-1] = (PROBES[-1][0], PROBES[-1][1], lambda: discover_metrics("payment-service"))

    print(RULE)
    print("1. what 'nothing' looks like, and what it gets typed as")
    print(RULE)
    facts = []
    for i, (label, tool, call) in enumerate(PROBES, start=1):
        payload, how = await _run(call)
        fact = classify(tool, payload, i)
        facts.append(fact)
        shown = str(payload).replace("\n", " ")
        print(f"\n{label}  [{how}]")
        print(f"  payload : {shown[:150]}{'…' if len(shown) > 150 else ''}")
        print(f"  verdict : {fact.disposition:<12} usable={fact.usable}")
    return facts


def section_two(facts: list) -> None:
    print("\n" + RULE)
    print("2. the ledger the model is handed")
    print(RULE)
    print(ledger(facts))


def section_three(facts: list) -> None:
    print("\n" + RULE)
    print("3. the same answer, against two different turns")
    print(RULE)
    answer = "payment-service 的拒絕率是 55%，根因是 v2.5.0 的新 validator。"  # noqa: RUF001
    empty = [f for f in facts if not f.usable]
    for name, pool in (("every observation empty", empty), ("this turn's real facts", facts)):
        ok, prompt = grounding_check(answer, pool)
        print(f"\n{name}: {'allowed' if ok else 'SENT BACK'}")
        if not ok:
            print("  " + prompt.replace("\n", "\n  "))
    honest = "I ran four checks and every one came back empty. I have no evidence either way."
    ok, _ = grounding_check(honest, empty)
    print(f"\nsaying so plainly, on the same empty turn: {'allowed' if ok else 'SENT BACK'}")


async def main() -> None:
    facts = await section_one()
    section_two(facts)
    section_three(facts)


if __name__ == "__main__":
    asyncio.run(main())
