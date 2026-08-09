"""Can you replay how the agent reached a conclusion?

Takes one finished investigation and asks six questions of the three places that
record anything: the investigation row, the audit log, and the agent's own trace
in Tempo. Prints which store can answer which question.

The agent is auto-instrumented, so a run driven through the in-cluster service
produces a real trace. A run driven from a host script (which is how every probe
in this series works) produces none — that difference is itself part of the
answer, so the script says which kind it is looking at.

Run from `aiops-agent/service/`:
    uv run python ../../otel-aiops-agent/ironman-2026/day25/replay_probe.py
    uv run python ../../otel-aiops-agent/ironman-2026/day25/replay_probe.py <trace_id>
"""

from __future__ import annotations

import asyncio
import collections
import json
import sys

import httpx
from app import audit, investigations
from app.config import settings

QUESTIONS = [
    "what did it conclude",
    "how confident was it",
    "which tools did it call, in what order",
    "what exactly did each query ask",
    "what did the model see before it decided",
    "how many tokens did it cost",
]


async def _trace(trace_id: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(f"{settings.tempo_url}/api/traces/{trace_id}")
    if r.status_code >= 400:
        return []
    spans = []
    for batch in r.json().get("batches", []):
        for scope_spans in batch.get("scopeSpans", []):
            scope = scope_spans.get("scope", {}).get("name", "")
            for span in scope_spans.get("spans", []):
                attrs = {
                    a["key"]: next(iter(a["value"].values())) for a in span.get("attributes", [])
                }
                spans.append({"scope": scope, "name": span["name"], "attrs": attrs})
    return spans


def _latest_investigation() -> dict | None:
    rows = investigations.list_investigations(limit=1)
    return rows[0] if rows else None


def main() -> None:
    trace_id = next((a for a in sys.argv[1:] if len(a) >= 24), None)
    record = None
    if trace_id is None:
        record = _latest_investigation()
        if record is None:
            print("no investigations recorded yet — drive one through /webhook/alert first")
            return
        trace_id = record.get("trace_id")
        print(f"latest investigation: fp={record['fp']} ts={record['ts']}")
        print(f"  conclusion : {(record.get('summary') or '')[:90]}")
        print(f"  confidence : {record.get('confidence')}")
        print(f"  trace_id   : {trace_id}")
        if trace_id is None:
            print("  (no trace: this run was not driven through the instrumented service)")

    spans = asyncio.run(_trace(trace_id)) if trace_id else []
    print(f"\nspans in Tempo for that trace: {len(spans)}")
    if spans:
        by_scope = collections.Counter(s["scope"].split(".")[-1] for s in spans)
        print(f"  by instrumentation: {dict(by_scope)}")
        for name, n in collections.Counter(s["name"] for s in spans).most_common(8):
            print(f"  {n:>2} {name}")

    tools = [s for s in spans if s["attrs"].get("gen_ai.operation.name") == "execute_tool"]
    chats = [s for s in spans if s["attrs"].get("gen_ai.operation.name") == "chat"]
    tokens = sum(int(s["attrs"].get("gen_ai.usage.input_tokens", 0) or 0) for s in chats)
    tokens += sum(int(s["attrs"].get("gen_ai.usage.output_tokens", 0) or 0) for s in chats)

    audit_rows = audit.history(fp=record["fp"], limit=50) if record else []

    answers = {
        "what did it conclude": ("investigation row", bool(record and record.get("summary"))),
        "how confident was it": ("investigation row", bool(record and record.get("confidence"))),
        "which tools did it call, in what order": ("trace", bool(tools)),
        "what exactly did each query ask": (
            "trace",
            any("gen_ai.tool.call.arguments" in s["attrs"] for s in tools),
        ),
        "what did the model see before it decided": (
            "trace",
            any("gen_ai.input.messages" in s["attrs"] for s in chats),
        ),
        "how many tokens did it cost": ("trace", tokens > 0),
    }
    print(f"\n{'question':<40} {'where it lives':<18} answerable")
    print("-" * 74)
    for q in QUESTIONS:
        where, ok = answers[q]
        print(f"{q:<40} {where:<18} {'yes' if ok else 'no'}")
    if tokens:
        print(f"\ntokens on this investigation: {tokens}")
    print(f"audit entries for this fp: {len(audit_rows)}")

    if tools:
        print("\nthe tool calls, in order (from the trace alone):")
        for s in tools:
            args = s["attrs"].get("gen_ai.tool.call.arguments", "")
            try:
                args = json.loads(args).get("input_str", args)
            except Exception:
                pass
            print(f"  - {s['attrs'].get('gen_ai.tool.name')}: {str(args)[:88]}")


if __name__ == "__main__":
    main()
