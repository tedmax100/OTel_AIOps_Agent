"""Run one eval fixture and print what each tool call got back.

The score says a fixture went from red to green; this says whether it went green
for the reason you changed. Prints every call, how its result was classified,
and any `note` / `hint` the tool attached to an empty result.

Run from `aiops-agent/service/` (needs the stack + GOOGLE_API_KEY):
    uv run python ../../otel-aiops-agent/ironman-2026/day22/show_transcript.py \
        order-service-discover-before-query
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime

from app.agent import run_headless
from app.eval.harness import DEFAULT_FIXTURES, load_fixtures
from app.eval.process import extract_calls


def _note(result: str) -> str:
    """The tool's own explanation of an empty result, if it attached one."""
    try:
        payload = json.loads(result)
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    return " ".join(str(payload[k]) for k in ("note", "hint") if k in payload)


async def main() -> None:
    fixture_id = sys.argv[1] if len(sys.argv) > 1 else "order-service-discover-before-query"
    fixture = next(f for f in load_fixtures(DEFAULT_FIXTURES) if f.id == fixture_id)
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    result = await run_headless(fixture.resolved_alert(now), thread_id=f"day23-{fixture_id}-{now}")
    calls = extract_calls(result.get("messages") or [])

    print(f"{fixture_id} @ {now}\n")
    for i, call in enumerate(calls):
        arg = next(
            (call.args[k] for k in ("expr", "logql", "traceql", "service") if k in call.args),
            "",
        )
        print(f"{i}. {call.name} [{call.kind}]  {str(arg)[:80]}")
        note = _note(call.result)
        if note:
            print(f"     tool said: {note[:200]}")
        elif call.kind == "error":
            print(f"     tool said: {call.result.strip().splitlines()[-1][:200]}")

    findings = result["findings"]
    print(f"\nservices  : {list(getattr(findings, 'services', []) or [])}")
    print(f"confidence: {getattr(findings, 'confidence', 0.0):.2f}")
    print(f"summary   : {(getattr(findings, 'summary', '') or '')[:200]}")


if __name__ == "__main__":
    asyncio.run(main())
