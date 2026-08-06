"""What the agent decides before it does anything: is this in scope, is it a
lookup or an investigation, and which service is it about.

Two LLM calls per question (the intent gate and, when the name is not literally
in the text, the resolver) — no tools, no investigation.

Run from `aiops-agent/service/`:
    uv run python ../../otel-aiops-agent/ironman-2026/day30/chat_probe.py
    uv run python ../../otel-aiops-agent/ironman-2026/day30/chat_probe.py "自己的問題"
"""

from __future__ import annotations

import asyncio
import sys

from app.agent import classify_intent
from app.capability import resolve_services

QUESTIONS = [
    "payment-service 的拒絕率為什麼變高了",
    "order-service 的 p95 latency",
    "近10筆 payment 的錯誤 log",
    "幫我寫一個 python 快排",
    "哪個服務最近最不健康",
]


async def main() -> None:
    questions = sys.argv[1:] or QUESTIONS
    for q in questions:
        intent = await classify_intent(q)
        resolution = await resolve_services(q)
        print(
            f"{q[:26]:<28} in_scope={intent.in_scope!s:<5} "
            f"mode={getattr(intent, 'mode', None)!s:<12} "
            f"services={resolution['services']} candidates={resolution['candidates'][:2]}"
        )


if __name__ == "__main__":
    asyncio.run(main())
