"""What the plugin will do with an answer, without opening a browser.

The chat UI is a renderer with a contract: fenced blocks become live panels, and
an alert spec becomes a card with a button. That contract lives in the system
prompt (the sender) and in two parsers (the receivers) — this script drives the
Python receiver over a real answer so you can see which blocks would render as
what, and which would come out as plain text the user has to copy by hand.

Run from `aiops-agent/service/`:
    uv run python ../../otel-aiops-agent/ironman-2026/day26/render_probe.py "幫我設一個告警"
    cat answer.txt | uv run python ../../otel-aiops-agent/ironman-2026/day26/render_probe.py -
"""

from __future__ import annotations

import asyncio
import re
import sys

import app.agent as agent_mod
from app.alerts import parse_alert_blocks

# The plugin's splitQueryBlocks, in one regex. Keep the two in step: whatever
# renders here is what renders there.
BLOCK_RE = re.compile(r"```(promql|logql|traceql|alert|json)([^\n]*)\n?([\s\S]*?)```", re.MULTILINE)

RENDERS_AS = {
    "promql": "live time-series panel",
    "logql": "live logs panel",
    "traceql": "live traces table",
    "alert": "alert proposal card (Create alert button)",
}


def report(answer: str) -> None:
    blocks = BLOCK_RE.findall(answer)
    specs = parse_alert_blocks(answer)
    print(f"answer: {len(answer)} chars, {len(blocks)} fenced block(s)\n")
    for lang, info, body in blocks:
        first = body.strip().splitlines()[0] if body.strip() else ""
        if lang == "json":
            kind = (
                "alert proposal card (accepted despite the fence tag)"
                if specs
                else "plain text — nothing renders"
            )
        else:
            kind = RENDERS_AS[lang]
        limit = re.search(r"\d+", info)
        print(f"```{lang}{info}  -> {kind}")
        if limit and lang in ("logql", "traceql"):
            print(f"     panel row limit: {limit.group(0)}")
        print(f"     {first[:96]}")
    if not blocks:
        print("no fenced blocks: the whole answer is prose, so the user sees no panel at all")


async def main() -> None:
    arg = sys.argv[1] if len(sys.argv) > 1 else "payment-service 的錯誤率"
    if arg == "-":
        report(sys.stdin.read())
        return
    answer: list[str] = []
    async for ev in agent_mod.stream_chat(arg, thread_id=f"day27-{abs(hash(arg)) % 10000}"):
        if ev["type"] == "token":
            answer.append(ev["text"])
    report("".join(answer))


if __name__ == "__main__":
    asyncio.run(main())
