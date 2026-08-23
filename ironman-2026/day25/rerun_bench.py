"""Re-run Day1's nine questions against today's agent, and grade them with Day1's grader.

The opening number of this series (4.5/9) came from a bench that is still here:
nine natural-language RCA questions, ground truth computed at grading time by
running a query against the live stack, four mechanical checks per task, no LLM
judge. Thirty days later the only honest way to say whether any of it helped is
to put today's agent in front of the same nine questions and the same grader.

Two things had to be arranged for that comparison to mean anything:

- **The same data schema.** The questions are written against the Day1 generator
  stack (`http_requests_total{job=…}`), not the demo-services cluster. So this
  runs against that stack image, and both agents see the same container.
- **The same grader.** `bench/grade.py` is imported from `day01/`, untouched.
  Ground truth is recomputed live for each run, so the two agents are graded
  against the data as it is at their own run time.

Usage (from the OTel_AIOps_Agent repo root), with the Day1 stack on
localhost:9090/3100/3200 and GOOGLE_API_KEY set:

    docker run -d --name day27-stack -p 9090:9090 -p 3100:3100 -p 3200:3200 \
        -p 8080:8080 o11y-bench-o11y-stack:latest

    AGENT_DIR=../o11y-bench/aiops-agent/service \
      python3 ironman-2026/day25/rerun_bench.py --which today
    AGENT_DIR=… python3 ironman-2026/day25/rerun_bench.py --which baseline
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_HERE = Path(__file__).resolve().parent
_DAY01 = _HERE.parent / "day01"
sys.path.insert(0, str(_DAY01))

from bench.grade import grade, resolve_truth  # noqa: E402

VERDICT = {1.0: "PASS", 0.5: "PARTIAL", 0.0: "FAIL"}


@dataclass
class Call:
    """Day1's ToolCall shape, which is all the grader needs."""

    name: str
    args: dict[str, Any]
    output: str
    ok: bool


# ---- the two agents under test ---------------------------------------------


async def run_baseline(question: str) -> tuple[str, list[Call]]:
    """Day1's agent, unchanged: hardcoded schema, 4 tool calls, no discovery."""
    from agent.baseline_agent import investigate

    trace = await investigate(question)
    return trace.answer, [Call(c.name, c.args, c.output, c.ok) for c in trace.tool_calls]


# A schema catalog that claims nothing about any particular stack. Swapping the
# real one for this is how we separate "the agent's machinery" from "the
# environment knowledge it was handed" — which turned out to be the whole story.
_NEUTRAL_CATALOG = """# Telemetry Schema Catalog

No environment-specific inventory is provided. Discover metric names, log fields
and span names with the discover_* tools before querying, and read label values
off the results rather than assuming them.
"""


async def run_today(question: str, tag: str, *, governance: bool = True) -> tuple[str, list[Call]]:
    """Today's agent, through the same chat entry point the plugin uses.

    The answer is streamed; the tool calls are read back off the graph's
    checkpointed state afterwards, so the grader sees the full tool output and
    not a truncated preview."""
    import app.agent as agent_mod
    from app.eval.process import extract_calls

    if not governance:
        agent_mod.SCHEMA_CATALOG = _NEUTRAL_CATALOG
        agent_mod._inject_signal_context = lambda *a, **k: None

    thread_id = f"day27-{tag}"
    answer: list[str] = []
    async for event in agent_mod.stream_chat(question, thread_id=thread_id):
        if event.get("type") == "token":
            answer.append(event["text"])

    graph = await agent_mod._build_agent()
    state = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    calls = [
        Call(c.name, c.args, c.result, c.kind != "error")
        for c in extract_calls(state.values.get("messages", []))
    ]
    return "".join(answer), calls


# ---- the bench -------------------------------------------------------------


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", choices=["today", "baseline"], default="today")
    ap.add_argument(
        "--no-governance",
        action="store_true",
        help="strip the schema catalog and signal context (they describe a different stack)",
    )
    ap.add_argument("--tasks", type=Path, default=_DAY01 / "bench" / "tasks.yaml")
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--report", type=Path, default=None)
    args = ap.parse_args()

    if args.which == "today":
        agent_dir = os.environ.get("AGENT_DIR")
        if not agent_dir:
            print("set AGENT_DIR to the aiops-agent service directory", file=sys.stderr)
            return 2
        sys.path.insert(0, str(Path(agent_dir).resolve()))

    tasks = yaml.safe_load(args.tasks.read_text())
    if args.only:
        tasks = [t for t in tasks if t["id"] in args.only]

    results = []
    for i, task in enumerate(tasks):
        truths = resolve_truth(task)
        question = task["question"].strip()
        if args.which == "baseline":
            answer, calls = await run_baseline(question)
        else:
            answer, calls = await run_today(
                question, f"{task['id']}-{i}", governance=not args.no_governance
            )
        score, checks = grade(task, answer, calls, truths)
        first_bad = next((c for c in checks if not c.passed), None)
        print(
            f"  {task['id']:<36} {task.get('signal', ''):<8} "
            f"{VERDICT.get(score, f'{score:.2f}'):>7}  "
            f"{(f'{first_bad.type}: {first_bad.detail}' if first_bad else '')[:64]}"
        )
        results.append(
            {
                "id": task["id"],
                "signal": task.get("signal", ""),
                "score": score,
                "answer": answer,
                "tool_calls": [c.__dict__ for c in calls],
                "checks": [
                    {"type": c.type, "passed": c.passed, "detail": c.detail} for c in checks
                ],
            }
        )

    total = sum(r["score"] for r in results)
    label = args.which + (" (no governance)" if args.no_governance else "")
    print(f"\n  {label}: {total:.1f}/{len(results)}")
    by_signal: dict[str, list[float]] = {}
    for r in results:
        by_signal.setdefault(r["signal"], []).append(r["score"])
    for signal, scores in sorted(by_signal.items()):
        print(f"    {signal:<8} {sum(scores):.1f}/{len(scores)}")

    if args.report:
        args.report.write_text(json.dumps(results, indent=2, ensure_ascii=False))
        print(f"\n  report written to {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
