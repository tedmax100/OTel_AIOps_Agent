"""Print one investigation's trace the way the Trace Explorer draws it.

`/traces/{id}` turns Tempo's OTLP-JSON into a node tree: gen_ai spans become
`llm` / `tool` nodes carrying the prompt, the tool arguments, the token usage and
a computed cost; everything else becomes `http` / `business`. This is the same
payload the plugin renders, printed as an indented tree so it can go in a README.

Run from `aiops-agent/service/` against a running agent (default :8091):
    uv run python ../../otel-aiops-agent/ironman-2026/day24/trace_tree.py <trace_id>
    uv run python ../../otel-aiops-agent/ironman-2026/day24/trace_tree.py   # latest investigation
"""

from __future__ import annotations

import json
import sys
import urllib.request

BASE = "http://localhost:8091"
# Plumbing spans: the httpx client spans for every datasource call. They are real
# and sometimes useful, but they bury the reasoning under noise in a printout.
NOISE = ("GET", "POST /chat http", "http send", "http receive")


def _get(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=20) as resp:
        return json.load(resp)


def _latest_trace_id() -> str | None:
    for row in _get("/investigations?limit=20").get("investigations", []):
        if row.get("trace_id"):
            return row["trace_id"]
    return None


def walk(node: dict, depth: int = 0, *, show_all: bool) -> None:
    label = node["label"]
    if not show_all and any(label.startswith(n) or n in label for n in NOISE):
        return
    cost = f" ${node['cost']}" if node.get("cost") else ""
    tokens = (
        f" in={node['input_tokens']} out={node['output_tokens']}"
        if node.get("input_tokens")
        else ""
    )
    indent = "  " * depth
    line = f"{indent}[{node['kind']:<8}] {node['label'][:58]:<58}"
    print(f"{line} {node['duration_ms']:>7.0f}ms{tokens}{cost}")
    for child in node.get("children") or []:
        walk(child, depth + 1, show_all=show_all)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    trace_id = args[0] if args else _latest_trace_id()
    if not trace_id:
        print(
            "no investigation with a trace_id yet — ask a question through the "
            "instrumented service first"
        )
        return 1
    tree = _get(f"/traces/{trace_id}")
    r = tree["rollup"]
    print(f"trace {trace_id}")
    print(
        f"  {r['span_count']} spans, {r['llm_calls']} LLM call(s), {r['tool_calls']} tool call(s), "
        f"{r['total_tokens']} tokens, ${r['cost']}"
    )
    print(f"  models: {r['models']}")
    if r.get("cost_basis"):
        print(f"  cost basis: {r['cost_basis']}")
    print()
    for root in tree["roots"]:
        walk(root, show_all="--all" in sys.argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
