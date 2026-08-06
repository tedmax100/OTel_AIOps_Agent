# Day28：agent 自己的決策，回放得了嗎

這天原本要寫成一個缺口（「`audit.record` 在執行那一側被呼叫 24 次，`agent.py` 一次都沒有」），
量完之後結論不一樣：**推理過程一直都有被 trace**，缺的是從結論走回那條 trace 的那一個欄位。

| 檔案 | 內容 |
| --- | --- |
| `replay_probe.py` | 拿一次真的調查，對三個記錄的地方（investigation row／audit log／Tempo 上 agent 自己的 trace）問六個問題，印出誰答得出來 |

同時改的是 agent 服務自己的原始碼：

| 檔案 | 改了什麼 |
| --- | --- |
| `app/audit.py` | 新增 `current_trace_id()`；每一筆 audit 進來時把 trace id 放進 `detail`（沒有 trace 就不放） |
| `app/investigations.py` | `InvestigationRecord` 多一個 `trace_id`，記錄調查時填入 |
| `tests/test_audit.py` | 三條新測試：沒有 trace 時回 `None` 而不是拋例外、有 trace 要寫進 detail、沒有 trace 照樣寫得成 |

## 驅動一次會留下 trace 的調查

關鍵是**要從被 instrument 的服務進去**。這系列前面每一支探測腳本都是在 host 上直接
呼叫 `run_headless()`，那條路徑沒有 `opentelemetry-instrument`，所以一個 span 都不會產生。

叢集裡的 agent 本來就有（Deployment 的 env 有整組 `OTEL_*`）：

```bash
kubectl -n demo port-forward svc/aiops-agent 8090:8000
curl -X POST localhost:8090/webhook/alert \
  -H 'content-type: application/json' -H 'x-webhook-secret: <secret>' \
  -d '{"alerts":[{"labels":{"alertname":"payment-decline-rate-high","service_name":"payment-service"},
       "annotations":{"summary":"..."},"startsAt":"2026-08-06T14:08:31Z"}]}'
```

要測還沒 commit 的程式碼，就在 host 上自己起一份帶 instrumentation 的：

```bash
kubectl -n demo port-forward svc/otel-collector 4318:4318
OTEL_SERVICE_NAME=aiops-agent-dev \
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf \
OTEL_TRACES_EXPORTER=otlp OTEL_METRICS_EXPORTER=none OTEL_LOGS_EXPORTER=none \
WEBHOOK_SECRET=dev-webhook-secret-1234 \
  uv run opentelemetry-instrument uvicorn app.main:app --port 8091
```

## 回放

```bash
uv run python ../../otel-aiops-agent/ironman-2026/day28/replay_probe.py
# 或指定一條 trace
uv run python ../../otel-aiops-agent/ironman-2026/day28/replay_probe.py <trace_id>
```

```
latest investigation: fp=383238a67e692abb ts=2026-08-06T14:12:07Z
  conclusion : High payment decline rate caused by a code regression in version v2.5.0…
  confidence : 0.9
  trace_id   : f1f393acce6a9cdb26d91a1565d4abe0

spans in Tempo for that trace: 36
  by instrumentation: {'fastapi': 4, 'httpx': 10, 'langchain': 22}
   4 ChatGoogleGenerativeAI.chat
   3 execute_task agent
   3 execute_task route_after_agent
   2 execute_tool query_prometheus
   2 execute_task tools

question                                 where it lives     answerable
--------------------------------------------------------------------------
what did it conclude                     investigation row  yes
how confident was it                     investigation row  yes
which tools did it call, in what order   trace              yes
what exactly did each query ask          trace              yes
what did the model see before it decided trace              yes
how many tokens did it cost              trace              yes

tokens on this investigation: 26123
audit entries for this fp: 1

the tool calls, in order (from the trace alone):
  - query_prometheus: {'expr': 'sum by (git_version, reason) (rate(payment_charges_total{status="declined"}…
  - k8s_deployment_status: {'service': 'payment-service'}
  - query_prometheus: {'expr': 'sum by (git_version, reason) (rate(payment_charges_total{status="declined"}…
  - query_tempo_traces: {'traceql': '{resource.service.name="payment-service" && status=error}', 'limit': 1}
```

`trace_id` 那一行是這天加的。加之前那格是 `None`，六個問題裡的後四個要先去 log 裡撈
`trace_id=...` 才問得出來。

audit 這一側也接上了：

```
2026-08-06T14:12:07Z proposed ok {'action': 'k8s.rollout_undo', 'autonomy': 'propose',
  'initial_status': 'proposed', 'reversible': True,
  'trace_id': 'f1f393acce6a9cdb26d91a1565d4abe0'}
```

## span 裡面有什麼

`opentelemetry-instrumentation-langchain` 產出的 span 帶的是 gen_ai 語意慣例，
一個工具呼叫的 span 長這樣（節錄）：

```
execute_tool query_prometheus
    gen_ai.operation.name      = execute_tool
    gen_ai.tool.name           = query_prometheus
    gen_ai.tool.call.arguments = {"input_str": "{'expr': 'sum by (git_version, reason) (rate(…
    gen_ai.tool.call.result    = {"output": {"resultType": "vector", "result": [{"metric": {…
    gen_ai.task.status         = success
```

模型呼叫那一種更完整，`gen_ai.system_instructions`、`gen_ai.input.messages`、
`gen_ai.usage.input_tokens`／`output_tokens`、以及 LangGraph 的
`langgraph_node`／`langgraph_step` 都在。

## 測試

```bash
uv run pytest tests/test_audit.py tests/test_investigations.py -q
```
