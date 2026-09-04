"""Day34 probe: send one real chat turn to the aiops-agent, then read back the
domain metrics that turn produced (aiops.tool.calls / aiops.chat.turns split
by disposition), plus a Tempo search that shows the chat lane has no
`aiops.investigation` span while the headless lane would.

Run from the repo root with the cluster's aiops-agent / prometheus / tempo
services port-forwarded (see README.md for the exact kubectl commands):

    python ironman-2026/day34/chat_probe.py \
        --agent http://localhost:18000 \
        --prometheus http://localhost:19090 \
        --tempo http://localhost:13200 \
        --message "payment-service 現在錯誤率是不是有異常？幫我查一下"
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from urllib import parse, request


def post_chat(agent_url: str, message: str, thread_id: str) -> None:
    body = json.dumps({"message": message, "thread_id": thread_id}).encode()
    req = request.Request(
        f"{agent_url}/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=60) as resp:
        for raw in resp:
            line = raw.decode().strip()
            if line.startswith("data:"):
                evt = json.loads(line[len("data:"):].strip())
                if evt.get("type") in {"tool_start", "tool_end"}:
                    print(f"  {evt['type']:>10}  {evt.get('tool')}", file=sys.stderr)


def prom_query(prom_url: str, expr: str) -> list[dict]:
    qs = parse.urlencode({"query": expr})
    with request.urlopen(f"{prom_url}/api/v1/query?{qs}", timeout=10) as resp:
        return json.load(resp)["data"]["result"]


def tempo_search(tempo_url: str, traceql: str) -> list[dict]:
    qs = parse.urlencode({"q": traceql, "limit": 5})
    with request.urlopen(f"{tempo_url}/api/search?{qs}", timeout=10) as resp:
        return json.load(resp)["traces"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="http://localhost:18000")
    ap.add_argument("--prometheus", default="http://localhost:19090")
    ap.add_argument("--tempo", default="http://localhost:13200")
    ap.add_argument("--message", required=True)
    args = ap.parse_args()

    thread_id = f"day34-probe-{int(time.time())}"
    print(f"POST /chat  thread={thread_id}", file=sys.stderr)
    post_chat(args.agent, args.message, thread_id)

    print("\nwaiting for the metrics exporter's periodic push...", file=sys.stderr)
    time.sleep(35)

    print("\n== aiops.tool.calls by disposition (last_over_time, 6h) ==")
    for row in prom_query(
        args.prometheus,
        'sum by (aiops_tool_name, aiops_tool_disposition) (last_over_time(aiops_tool_calls_total[6h]))',
    ):
        print(f"  {row['metric']['aiops_tool_name']:<20} {row['metric']['aiops_tool_disposition']:<10} {row['value'][1]}")

    print("\n== aiops.chat.turns by in_scope (last_over_time, 6h) ==")
    for row in prom_query(
        args.prometheus,
        'sum by (aiops_intent_in_scope) (last_over_time(aiops_chat_turns_total[6h]))',
    ):
        print(f"  in_scope={row['metric']['aiops_intent_in_scope']:<6} {row['value'][1]}")

    print("\n== Tempo: traces named 'aiops.investigation' (should be empty — chat lane never opens it) ==")
    inv_traces = tempo_search(args.tempo, '{name="aiops.investigation"}')
    print(f"  matched: {len(inv_traces)}")

    print("\n== Tempo: traces rooted at 'POST /chat' (auto-instrumentation still covers this) ==")
    chat_traces = tempo_search(args.tempo, '{resource.service.name="aiops-agent" && name="POST /chat"}')
    for t in chat_traces:
        print(f"  {t['traceID']}  {t['durationMs']}ms")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
