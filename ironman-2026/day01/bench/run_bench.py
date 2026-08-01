"""Run the Day1 agent against the nine RCA tasks and print the scoreboard.

    ./ironman-2026/day01/scripts/up.sh          # stack first
    export GOOGLE_API_KEY=...
    uv run --project ironman-2026/day01 python -m bench.run_bench

Options:
    --tasks PATH     task file (default bench/tasks.yaml)
    --only ID        run one task (repeatable)
    --report PATH    write the full transcript + grading to JSON
    --seeds N        run each task N times and report the mean (default 1)

The report JSON is the artefact worth keeping: it holds every query the agent
issued and every check that fired, which is what makes a score arguable instead
of just disappointing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

_DAY_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_DAY_DIR))

from agent.baseline_agent import (  # noqa: E402
    MODEL,
    TOOL_CALL_BUDGET,
    investigate,
)

from bench.grade import grade, resolve_truth  # noqa: E402

VERDICT = {1.0: "PASS", 0.5: "PARTIAL", 0.0: "FAIL"}


async def run_task(task: dict, seeds: int) -> dict:
    truths = resolve_truth(task)
    runs = []
    for seed in range(seeds):
        trace = await investigate(task["question"].strip())
        score, checks = grade(task, trace.answer, trace.tool_calls, truths)
        runs.append(
            {
                "seed": seed,
                "score": score,
                "checks": [
                    {"type": c.type, "passed": c.passed, "detail": c.detail} for c in checks
                ],
                **trace.to_dict(),
            }
        )
    mean = sum(r["score"] for r in runs) / len(runs)
    return {
        "id": task["id"],
        "signal": task.get("signal", ""),
        "score": mean,
        "truth": {
            k: {"value": t.value, "label": t.label, "error": t.error} for k, t in truths.items()
        },
        "runs": runs,
    }


def format_scoreboard(results: list[dict], *, seeds: int) -> str:
    total = sum(r["score"] for r in results)
    lines = [
        f"Day1 baseline — model {MODEL}, tool budget {TOOL_CALL_BUDGET}, {seeds} seed(s)",
        "",
        f"  {'task':<36} {'signal':<8} {'score':>6}  first failing check",
        "  " + "-" * 88,
    ]
    for r in results:
        first_bad = next(
            (c for c in r["runs"][0]["checks"] if not c["passed"]),
            None,
        )
        why = f"{first_bad['type']}: {first_bad['detail']}" if first_bad else ""
        verdict = VERDICT.get(r["score"], f"{r['score']:.2f}")
        lines.append(f"  {r['id']:<36} {r['signal']:<8} {verdict:>6}  {why[:60]}")

    lines += [
        "  " + "-" * 88,
        f"  {'TOTAL':<36} {'':<8} {total:>4.1f}/{len(results)}",
        "",
    ]

    # Per-signal breakdown: which of the three signals the agent is worst at is
    # more actionable than the single number.
    by_signal: dict[str, list[float]] = {}
    for r in results:
        by_signal.setdefault(r["signal"], []).append(r["score"])
    for signal, scores in by_signal.items():
        lines.append(f"  {signal:<8} {sum(scores):.1f}/{len(scores)}")
    return "\n".join(lines)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", type=Path, default=_DAY_DIR / "bench" / "tasks.yaml")
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--report", type=Path, default=_DAY_DIR / "report.json")
    ap.add_argument("--seeds", type=int, default=1)
    args = ap.parse_args()

    tasks = yaml.safe_load(args.tasks.read_text())
    if args.only:
        tasks = [t for t in tasks if t["id"] in set(args.only)]
    if not tasks:
        print("no tasks selected", file=sys.stderr)
        return 2

    results = []
    for task in tasks:
        print(f"  … {task['id']}", file=sys.stderr, flush=True)
        results.append(await run_task(task, args.seeds))

    report = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": MODEL,
        "tool_call_budget": TOOL_CALL_BUDGET,
        "seeds": args.seeds,
        "total": sum(r["score"] for r in results),
        "max": float(len(results)),
        "results": results,
    }
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    print()
    print(format_scoreboard(results, seeds=args.seeds))
    print(f"\n  full transcript → {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
