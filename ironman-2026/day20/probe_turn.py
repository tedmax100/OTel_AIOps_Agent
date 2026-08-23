"""What the agent is handed before it is allowed to think.

`run_headless()` assembles a turn and only then invokes the graph. This probe
replaces the graph with a stub that records the state it was called with, so the
assembled turn can be inspected without spending a single LLM token — the same
trick the governance assets were tested with earlier in the series.

Run from `aiops-agent/service/` with Prometheus/Loki/Tempo port-forwarded:
    uv run python ../../otel-aiops-agent/ironman-2026/day20/probe_turn.py
"""

from __future__ import annotations

import asyncio
import sys

import app.agent as agent_mod
from app.agent import run_headless

# An alert pinned to a moment when the payment incident was actually running, so
# the injections that do live I/O read the incident rather than "now".
ALERT = {
    "labels": {
        "alertname": "PaymentDeclineRateHigh",
        "service_name": "payment-service",
        "severity": "critical",
        "git_version": "v2.5.0",
    },
    "annotations": {"summary": "payment-service declined rate above objective"},
    "startsAt": "2026-08-05T15:30:00Z",
}

captured: dict = {}


class _StubGraph:
    """Stands in for the compiled StateGraph. Records the state, answers nothing."""

    async def ainvoke(self, state: dict, config: dict | None = None) -> dict:
        captured["state"] = state
        captured["config"] = config
        return {"messages": list(state["messages"])}


async def _stub_findings(messages: list) -> object:
    from app.agent import Findings

    # High confidence so the outer hypothesis-pivot loop does not fire.
    return Findings(summary="stub", hypothesis="stub", confidence=0.9)


def _describe(msg: object) -> tuple[str, str, int]:
    role = getattr(msg, "type", None) or (msg.get("role") if isinstance(msg, dict) else "?")
    content = getattr(msg, "content", None)
    if content is None and isinstance(msg, dict):
        content = msg.get("content", "")
    text = content if isinstance(content, str) else str(content)
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    return role, first, len(text)


async def main() -> None:
    agent_mod._build_agent = lambda: asyncio.sleep(0, result=_StubGraph())
    agent_mod.extract_findings = _stub_findings

    await run_headless(ALERT, thread_id="day21-probe")

    state = captured.get("state")
    if state is None:
        print("the graph was never invoked", file=sys.stderr)
        raise SystemExit(1)

    msgs = state["messages"]
    print(f"budget: {state['budget']} tool calls")
    print(f"messages handed to the graph: {len(msgs)}\n")
    total = 0
    for i, m in enumerate(msgs):
        role, first, n = _describe(m)
        total += n
        print(f"{i}. [{role:9s}] {n:6d} chars  {first[:78]}")
    print(f"\ntotal: {total} chars before the first token of reasoning")

    if "--full" in sys.argv:
        for i, m in enumerate(msgs):
            role, _, _ = _describe(m)
            content = getattr(m, "content", None)
            if content is None and isinstance(m, dict):
                content = m.get("content", "")
            print(f"\n{'=' * 70}\n{i}. [{role}]\n{'=' * 70}\n{content}")


if __name__ == "__main__":
    asyncio.run(main())
