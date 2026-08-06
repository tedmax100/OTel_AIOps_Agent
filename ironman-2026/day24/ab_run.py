"""Run the same alert twice — once on the prompt that contained the answer, once
on the one that doesn't — and print both transcripts side by side.

The "leaky" side is not a hypothetical: `leaky_catalog.md` and
`leaky_contracts.yaml` are byte-for-byte snapshots of what the agent was being
handed before this day's cleanup, so the A side reproduces the number Day23
reported rather than approximating it.

Costs real tokens (two full RCA runs). From `aiops-agent/service/`:
    uv run python ../../otel-aiops-agent/ironman-2026/day24/ab_run.py
    uv run python ../../otel-aiops-agent/ironman-2026/day24/ab_run.py --answers
"""

from __future__ import annotations

import asyncio
import pathlib
import re
import sys
from datetime import UTC, datetime

import app.agent as agent_mod
from app.agent import run_headless
from app.eval.process import extract_calls
from app.signals import context as context_mod
from app.signals import contract as contract_mod

HERE = pathlib.Path(__file__).parent
LEAKY_CATALOG = HERE / "leaky_catalog.md"
LEAKY_CONTRACTS = HERE / "leaky_contracts.yaml"

ANSWER_TOKENS = ["v2.5.0", "v2.4.1", "new_validator", "odd", "payment_use_new_validator"]

ALERT = {
    "labels": {
        "alertname": "PaymentDeclineRateHigh",
        "service_name": "payment-service",
        "severity": "critical",
    },
    "annotations": {"summary": "payment-service declined rate above objective"},
}


def _use_leaky(on: bool) -> None:
    """Swap the two prompt artifacts and drop every cache that holds them."""
    from app.config import settings

    if on:
        agent_mod.SCHEMA_CATALOG = LEAKY_CATALOG.read_text(encoding="utf-8")
        settings.signal_contracts_path = str(LEAKY_CONTRACTS)
    else:
        clean = pathlib.Path(agent_mod.__file__).parent / "schema_catalog.md"
        agent_mod.SCHEMA_CATALOG = clean.read_text(encoding="utf-8")
        settings.signal_contracts_path = ""
    contract_mod.get_contracts.cache_clear()
    for fn in (getattr(context_mod, "build_signal_context", None),):
        if hasattr(fn, "cache_clear"):
            fn.cache_clear()


def _leaks(text: str) -> list[str]:
    return [t for t in ANSWER_TOKENS if re.search(re.escape(t), text, re.IGNORECASE)]


async def one(label: str, leaky: bool, starts_at: str) -> dict:
    _use_leaky(leaky)
    alert = dict(ALERT, startsAt=starts_at)
    result = await run_headless(alert, thread_id=f"day24-ab-{label}-{starts_at}")
    findings = result["findings"]
    calls = extract_calls(result.get("messages") or [])

    print(f"\n{'=' * 72}\n{label}  (prompt contains the answer: {leaky})\n{'=' * 72}")
    print(f"tool calls ({len(calls)}):")
    for c in calls:
        # show the query itself when there is one, not whatever argument happens
        # to come first (stepSeconds tells you nothing about what it asked)
        arg = next(
            (
                c.args[k]
                for k in ("expr", "logql", "traceql", "query", "service", "base")
                if k in c.args
            ),
            next(iter(c.args.values()), ""),
        )
        print(f"  - {c.name:<22} [{c.kind:<5}] {str(arg)[:70]}")
    print(f"\nservices: {list(getattr(findings, 'services', []) or [])}")
    print(f"version : {getattr(findings, 'suspected_version', None)}")
    print(f"conf    : {getattr(findings, 'confidence', 0.0):.2f}")
    print(f"summary : {(getattr(findings, 'summary', '') or '')[:300]}")
    if "--answers" in sys.argv:
        print(f"\n--- answer ---\n{result.get('answer', '')}")
    return {"findings": findings, "calls": calls, "answer": result.get("answer", "")}


async def main() -> None:
    starts_at = next(
        (a for a in sys.argv[1:] if a.startswith("20")),
        datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    print(f"alert startsAt = {starts_at}")
    a = await one("A: leaky prompt", True, starts_at)
    b = await one("B: cleaned prompt", False, starts_at)

    print(f"\n{'=' * 72}\nwhat each run had to discover for itself\n{'=' * 72}")
    for label, run, leaky in (("A", a, True), ("B", b, False)):
        got = getattr(run["findings"], "suspected_version", None)
        source = "handed to it" if leaky else "found by it"
        print(f"  {label}: version {got!r} — {source}; {len(run['calls'])} tool call(s)")
    print("\n  tokens that appear in the answer but not in any tool result:")
    for label, run in (("A", a), ("B", b)):
        seen = " ".join(c.result for c in run["calls"])
        ungrounded = [t for t in _leaks(run["answer"]) if t.lower() not in seen.lower()]
        print(f"    {label}: {ungrounded or 'none'}")


if __name__ == "__main__":
    asyncio.run(main())
