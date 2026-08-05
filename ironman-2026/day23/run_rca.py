"""Run one real headless RCA against the pinned incident and print the transcript.

Unlike `probe_turn.py` (which stubs the graph out), this spends real tokens: it
drives the actual LangGraph loop, so the output is what the agent really did —
which tools it called, in what order, with what arguments, and what it concluded.

Run from `aiops-agent/service/` with Prometheus/Loki/Tempo port-forwarded and
GOOGLE_API_KEY set in .env:
    uv run python ../../otel-aiops-agent/ironman-2026/day23/run_rca.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time

import app.agent as agent_mod
from app.agent import run_headless

# run_headless() returns only the answer/findings, so wrap the compiled graph to
# keep every message it produced — that transcript is the point of this script.
TRANSCRIPT: list = []


class _Recording:
    def __init__(self, inner: object) -> None:
        self._inner = inner

    async def ainvoke(self, state: dict, config: dict | None = None) -> dict:
        out = await self._inner.ainvoke(state, config=config)
        TRANSCRIPT.append(out.get("messages") or [])
        return out


_real_build = agent_mod._build_agent


async def _build_recording() -> object:
    return _Recording(await _real_build())


ALERT = {
    "labels": {
        "alertname": "PaymentDeclineRateHigh",
        "service_name": "payment-service",
        "severity": "critical",
    },
    "annotations": {"summary": "payment-service declined rate above objective"},
    "startsAt": "2026-08-05T15:30:00Z",
}


def _text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [c.get("text", "") for c in content if isinstance(c, dict)]
        return "".join(parts)
    return str(content or "")


def _print_transcript(messages: list) -> None:
    step = 0
    for m in messages:
        kind = getattr(m, "type", "?")
        calls = getattr(m, "tool_calls", None) or []
        if calls:
            # An AIMessage can carry reasoning text *and* tool calls; print both,
            # otherwise the transcript hides whether the model planned first.
            said = _text(getattr(m, "content", "")).strip()
            if said:
                print(f"\n[said before calling]\n{said}\n")
            for tc in calls:
                step += 1
                args = json.dumps(tc.get("args", {}), ensure_ascii=False)
                print(f"\n[{step}] CALL {tc.get('name')}")
                print(f"    {args[:400]}")
        elif kind == "tool":
            body = _text(getattr(m, "content", ""))
            head = " ".join(body.split())[:300]
            print(f"    -> {head}")
        elif kind == "ai":
            body = _text(getattr(m, "content", "")).strip()
            if body:
                print(f"\n[reasoning/answer]\n{body}\n")


async def main() -> None:
    agent_mod._build_agent = _build_recording
    started = time.monotonic()
    result = await run_headless(ALERT, thread_id=f"day23-real-{int(time.time())}")
    elapsed = time.monotonic() - started

    print("=" * 72)
    print("TOOL CALLS THE AGENT ACTUALLY MADE")
    print("=" * 72)
    for i, msgs in enumerate(TRANSCRIPT):
        if i:
            print(f"\n--- pivot {i} (fresh budget, same thread) ---")
        _print_transcript(msgs)

    print("=" * 72)
    print(f"answer:\n{result.get('answer', '')}\n")
    findings = result.get("findings")
    if findings is not None:
        print(f"findings: {findings}")
    print(f"elapsed: {elapsed:.1f}s")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
