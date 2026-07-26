#!/usr/bin/env python3
"""真的跑一次 instrumentation，把「實際送出的 span」轉成 weaver live-check 的樣本。

重點是這支腳本不知道 handler 裡寫了什麼欄位名——樣本是從 InMemorySpanExporter 收到的
span 上讀出來的，不是手打的。所以後面 live-check 檢查的東西，就是程式碼真的送出的東西。

用法（從這個 repo 的根目錄跑）：

    python3 day15/run_and_extract.py before             # 印出真實 span（可讀格式）
    python3 day15/run_and_extract.py before --samples   # 印出 weaver live-check 樣本 JSON

接下去可以直接餵給兩條路徑之一：

    python3 day15/run_and_extract.py before --samples \\
      | weaver registry live-check -r day14/base-v2 --input-source stdin

    python3 day15/run_and_extract.py before --samples > /tmp/before.json
    python3 day15/mcp_probe.py day14/base-v2 "$(python3 -c '...')"   # 見 README
"""

import importlib.util
import json
import os
import sys

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

WHICH = sys.argv[1] if len(sys.argv) > 1 else "before"
AS_SAMPLES = "--samples" in sys.argv

SPAN_KIND = {
    "SpanKind.INTERNAL": "internal",
    "SpanKind.SERVER": "server",
    "SpanKind.CLIENT": "client",
    "SpanKind.PRODUCER": "producer",
    "SpanKind.CONSUMER": "consumer",
}

TYPE_OF = {str: "string", bool: "boolean", int: "int", float: "double"}

exporter = InMemorySpanExporter()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
trace.set_tracer_provider(provider)

_path = os.path.join(os.path.dirname(__file__), "samples", f"payment_handler_{WHICH}.py")
_spec = importlib.util.spec_from_file_location(f"payment_handler_{WHICH}", _path)
handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handler)

# 兩筆交易，一筆成功一筆被拒（奇數分），順便讓 retries 有值
handler.charge("1001", 2000, retries=0)
handler.charge("1002", 1999, retries=2)

provider.force_flush()
spans = exporter.get_finished_spans()


def attr_samples(attributes):
    return [
        {"name": k, "type": TYPE_OF.get(type(v), "string"), "value": v}
        for k, v in (attributes or {}).items()
    ]


if not AS_SAMPLES:
    for s in spans:
        print(f"span name={s.name} kind={SPAN_KIND.get(str(s.kind), 'internal')}")
        for k, v in (s.attributes or {}).items():
            print(f"  {k} = {v!r}  ({type(v).__name__})")
        for e in s.events:
            print(f"  [event] {e.name} {dict(e.attributes or {})}")
    sys.exit(0)

samples = []
for s in spans:
    span_sample = {
        "name": s.name,
        "kind": SPAN_KIND.get(str(s.kind), "internal"),
        "attributes": attr_samples(s.attributes),
    }
    if s.events:
        span_sample["span_events"] = [
            {"name": e.name, "attributes": attr_samples(e.attributes)} for e in s.events
        ]
    samples.append({"span": span_sample})

print(json.dumps(samples, ensure_ascii=False, indent=2))
