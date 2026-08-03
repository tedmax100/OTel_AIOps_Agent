#!/usr/bin/env python3
"""不接 LLM，直接用 stdio JSON-RPC 驗證 `weaver registry mcp` 的行為。

為什麼要有這支：agent 答錯的時候，得先知道是「agent 講錯」還是「registry 教錯」。
把 MCP server 當成一個普通的 RPC 服務打一輪，就能把後者先排除掉。

用法（從 repo 根目錄跑）：

    python3 ironman-2026/day10/mcp_probe.py            # 走完整輪，用 Day9 的兩份 registry
    python3 ironman-2026/day10/mcp_probe.py <registry> # 只列 tool 清單，打自己的 registry
"""

from __future__ import annotations

import itertools
import json
import subprocess
import sys

BASE = "ironman-2026/day09/base-v2"
TEAM = "ironman-2026/day09/team-orders"


class McpProbe:
    """把 `weaver registry mcp` 當成一個 stdio JSON-RPC 服務。"""

    def __init__(self, registry: str, *extra_args: str) -> None:
        self._proc = subprocess.Popen(
            ["weaver", "registry", "mcp", "-r", registry, *extra_args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        self._ids = itertools.count(1)
        self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "mcp_probe", "version": "0"},
            },
        )
        self._notify("notifications/initialized")

    def _notify(self, method: str) -> None:
        self._proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self._proc.stdin.flush()

    def _request(self, method: str, params: dict | None = None) -> dict:
        request_id = next(self._ids)
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
        self._proc.stdin.write(json.dumps(payload) + "\n")
        self._proc.stdin.flush()
        while True:
            line = self._proc.stdout.readline()
            if not line:
                raise RuntimeError("MCP server closed the pipe")
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if message.get("id") == request_id:
                return message

    def tools(self) -> list[dict]:
        return self._request("tools/list")["result"]["tools"]

    def call(self, name: str, **arguments: object) -> dict:
        response = self._request("tools/call", {"name": name, "arguments": arguments})
        if "result" not in response:
            raise RuntimeError(f"{name}: {json.dumps(response.get('error'), ensure_ascii=False)}")
        return response["result"]

    def text(self, name: str, **arguments: object) -> str:
        result = self.call(name, **arguments)
        return "\n".join(block.get("text", "") for block in result.get("content", []))

    def close(self) -> None:
        self._proc.terminate()


def head(title: str) -> None:
    print(f"\n## {title}")


def brief(payload: str, *keys: str) -> str:
    """把 JSON 回應壓成幾個關心的欄位，輸出才讀得完。"""
    try:
        data = json.loads(payload)
    except ValueError:
        return payload.strip()
    if isinstance(data, dict) and "results" in data:
        rows = [{k: r.get(k) for k in keys if k in r} for r in data["results"]]
        return json.dumps({"total": data.get("total"), "results": rows}, ensure_ascii=False)
    if keys and isinstance(data, dict):
        return json.dumps({k: data.get(k) for k in keys if k in data}, ensure_ascii=False)
    return json.dumps(data, ensure_ascii=False)


def tool_list(registry: str) -> None:
    probe = McpProbe(registry)
    tools = probe.tools()
    print(f"## tools ({len(tools)})，registry = {registry}")
    for tool in tools:
        print(f"  - {tool['name']}")
    probe.close()


def tour() -> None:
    tool_list(BASE)

    base = McpProbe(BASE)

    head("search：AND 比對，而且 brief 也進了索引")
    for query in ["order", "訂單識別碼", "user id", "order user", "identifier"]:
        print(f"  {query!r:20} -> {brief(base.text('search', query=query), 'key', 'score')}")

    head("search 對 deprecated 的東西會標記、也會降權")
    print(" ", brief(base.text("search", query="cart"), "key", "score", "deprecated"))

    head("browse_namespace 同一份 registry，同一個屬性，沒有任何 deprecated 的痕跡")
    print(" ", brief(base.text("browse_namespace", prefix="biz")))

    head("查一個不存在的名字：isError 是 false")
    missing = base.call("get_attribute", key="biz.does.not.exist")
    print("  isError:", missing.get("isError"))
    print("  content:", "".join(b.get("text", "") for b in missing.get("content", [])))

    head("live_check 也在同一個 server 上")
    samples = [
        {
            "span": {
                "name": "order.create",
                "kind": "server",
                "attributes": [{"name": "app.outcome", "value": "gateway_error"}],
            }
        }
    ]
    print(" ", base.text("live_check", samples=samples, output="findings_only"))
    base.close()

    print("\n" + "=" * 72)
    print("分層 registry：同一個屬性，兩個入口兩種答案")
    print("=" * 72)

    team = McpProbe(TEAM)

    head("get_span 拿得到 base 的屬性（注意 type 不帶 span. 前綴）")
    span = json.loads(team.text("get_span", type="orders.create"))
    for attr in span["attributes"]:
        source = json.dumps(attr.get("provenance"), ensure_ascii=False)
        print(f"  {attr['key']:20} {attr.get('requirement_level'):16} {source}")

    head("但同樣那幾個屬性，直接查就是不存在")
    for key in ["biz.user.id", "app.outcome"]:
        print(f"  {key:20} -> {team.text('get_attribute', key=key)}")
    print(" ", brief(team.text("browse_namespace"), "total_attribute_count"))

    head("group id 照抄進 get_span 會拿到 not found")
    print("  span.orders.create ->", team.text("get_span", type="span.orders.create"))
    team.close()

    head("--include-unreferenced 之後才看得到 base，而且 provenance 變成 source")
    wide = McpProbe(TEAM, "--include-unreferenced")
    print(" ", brief(wide.text("browse_namespace"), "total_attribute_count"))
    print(" ", brief(wide.text("get_attribute", key="biz.user.id"), "key", "brief", "provenance"))
    wide.close()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        tool_list(sys.argv[1])
    else:
        tour()
