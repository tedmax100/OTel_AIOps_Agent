#!/usr/bin/env python3
"""Drive `weaver registry mcp` over stdio JSON-RPC, without an LLM.

用法（從這個 repo 的根目錄跑）：

    python3 day15/mcp_probe.py day14/base-v2
    python3 day15/mcp_probe.py day14/base-v2 '[{"name":"search","arguments":{"query":"payment"}}]'
    python3 day15/mcp_probe.py day13/team '[...]' --include-unreferenced true

第一個參數是 registry、第二個是 tools/call 的清單（JSON）、之後的參數原封不動
傳給 weaver。initialize / notifications/initialized / tools/list 會自動先跑一輪。
"""
import json
import subprocess
import sys
import threading

REG = sys.argv[1] if len(sys.argv) > 1 else "day14/base-v2"
CALLS = json.loads(sys.argv[2]) if len(sys.argv) > 2 else []
EXTRA = sys.argv[3:]

p = subprocess.Popen(
    ["weaver", "registry", "mcp", "-r", REG] + EXTRA,
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True, bufsize=1, )

err = []
threading.Thread(target=lambda: err.extend(p.stderr.readlines()), daemon=True).start()


def send(obj):
    p.stdin.write(json.dumps(obj) + "\n")
    p.stdin.flush()


def recv():
    line = p.stdout.readline()
    if not line:
        return None
    return json.loads(line)


send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
      "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                 "clientInfo": {"name": "day15-probe", "version": "0"}}})
print("=== initialize"); print(json.dumps(recv(), ensure_ascii=False, indent=2))

send({"jsonrpc": "2.0", "method": "notifications/initialized"})

send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
print("=== tools/list"); print(json.dumps(recv(), ensure_ascii=False, indent=2))

for i, call in enumerate(CALLS, start=3):
    send({"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": call})
    print(f"=== tools/call {call['name']} {json.dumps(call.get('arguments', {}), ensure_ascii=False)}")
    print(json.dumps(recv(), ensure_ascii=False, indent=2))

p.stdin.close()
p.wait(timeout=10)
if err:
    print("=== stderr"); print("".join(err))
