"""Run one chat turn and print the event stream the plugin actually consumes.

The prose is what the user reads; these events are what the UI is built out of —
status phases, tool calls, the structured verdict, follow-up chips. Printing
them side by side is the quickest way to see which of them a given question
produces (a lookup produces no findings at all).

Run from `aiops-agent/service/`:
    uv run python ../../otel-aiops-agent/ironman-2026/day24/chat_turn.py "…" [--answer]
"""

from __future__ import annotations

import asyncio
import sys

import app.agent as agent_mod
from app.investigations import list_investigations

DEFAULT = "payment-service 的拒絕率為什麼變高了"


async def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    question = args[0] if args else DEFAULT
    thread_id = args[1] if len(args) > 1 else "day26-chat-turn"

    answer: list[str] = []
    async for ev in agent_mod.stream_chat(question, thread_id=thread_id):
        kind = ev["type"]
        if kind == "token":
            answer.append(ev["text"])
        elif kind == "tool_start":
            print(f"tool_start {ev['tool']} {str(ev.get('input'))[:88]}")
        elif kind == "findings":
            print(
                f"findings   confidence={ev['confidence']} services={ev['services']} "
                f"version={ev['suspected_version']}"
            )
            print(f"           {ev['summary'][:100]}")
        elif kind == "suggestions":
            print(f"suggestions {ev['items']}")
        elif kind == "clarify":
            print(f"clarify    {ev['prompt']} {ev['options']}")

    if "--answer" in sys.argv:
        print("\n--- answer ---\n" + "".join(answer))

    rows = [r for r in list_investigations(limit=20) if r["fp"] == thread_id]
    if rows:
        r = rows[0]
        print(
            f"\nstored row: fp={r['fp']} source={r.get('source')} "
            f"confidence={r.get('confidence')} trace_id={r.get('trace_id')}"
        )
    else:
        print("\nstored row: none (a lookup turn does not produce one)")


if __name__ == "__main__":
    asyncio.run(main())
