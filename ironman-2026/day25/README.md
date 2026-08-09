# Day25：agent 自己的決策，回放得了嗎

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
uv run python ../../otel-aiops-agent/ironman-2026/day25/replay_probe.py
# 或指定一條 trace
uv run python ../../otel-aiops-agent/ironman-2026/day25/replay_probe.py <trace_id>
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

---

## 整條鏈跑一次

從「一個新服務要上線」到「這隻 agent 這次考幾分」，六個階段一次跑完。

| 檔案 | 內容 |
| --- | --- |
| `e2e.sh` | 六個階段依序跑，每段印關鍵輸出，最後一張 ok/FAIL 清單 |
| `report.py` | 用 agent 自己的 HTTP API 讀回調查結論與提案（含 footprint） |

## 為什麼是這個順序

1. **治理**：新服務跑一次上線檢查（Day12 的 `verify_onboarding.py`）
2. **意圖**：宣告的穩定狀態編成 alert rule（Day11 的 `compile_intent.py`）
3. **Signal Plane**：服務自己的宣告編譯成拓撲與契約，並確認沒有洩題（Day22 的 `leakcheck.py`）
4. **調查**：一個告警進去，診斷 ＋ 信心分數 ＋ 下一步建議出來
5. **評測**：同一隻 agent 對著固定資料被打分

**階段 1-4 跑在活的 k3d 叢集上，階段 5 會啟動預先建好的 stack image。** 那個 image 自己
要用 9090/3100/3200，跟前面幾段需要的 port-forward 衝突，所以順序是固定的，而且階段 5
會先把 port-forward 關掉。

## 跑

```bash
# 前置：k3d demo stack 起來、Prometheus/Loki/Tempo port-forward、agent 跑在 8091
AGENT_DIR=/path/to/o11y-bench/aiops-agent/service \
AGENT_URL=http://localhost:8091 \
WEBHOOK_SECRET=dev-webhook-secret-1234 \
  ./ironman-2026/day25/e2e.sh
```

agent 要從被 instrument 的入口進去，才會有 trace（Day25）：

```bash
cd o11y-bench/aiops-agent/service
kubectl -n demo port-forward svc/otel-collector 4318:4318 &
OTEL_SERVICE_NAME=aiops-agent-dev OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf OTEL_TRACES_EXPORTER=otlp \
OTEL_METRICS_EXPORTER=none OTEL_LOGS_EXPORTER=none \
WEBHOOK_SECRET=dev-webhook-secret-1234 \
  uv run opentelemetry-instrument uvicorn app.main:app --port 8091
```

## 一次完整的輸出

```
── 1. governance: shipping-v1 onboarding checklist ──
13/13 通過

── 2. intent: steady state -> alert rules ──
  - alert: checkout-success-rate
    expr: sum(rate(orders_attempts_total{app_outcome=~"authorized"}[30m])) / sum(rate(orders_attempts_total[30m]))
  - alert: checkout-latency
    expr: histogram_quantile(0.99, sum by (le) (rate(orders_duration_bucket[30m]))) > 2

── 3. signal plane: compile + leak check ──
compiled 5 fragments → topology.yaml (5 nodes, 6 edges, journeys=['checkout']) + contracts.yaml (5 contracts)
runbook payment-bad-deploy matched alertname 'PaymentDeclineRateHigh' only after normalization
  (trigger says 'payment-decline-rate-high') — align the alert rule or the runbook trigger
no answer tokens in anything handed to the model.

── 4. investigation: alert -> diagnosis ──
{"accepted":["383238a67e692abb"],"skipped":[]}
conclusion : Code regression in payment-service v2.5.0 introduced a spike in decline rate due to
             the new_validator reason.
confidence : 0.7
trace_id   : abb6fac796db47d684ed5238a5e37b36
next step  : k8s.rollout_undo -> propose

── 4b. next step: the proposal and its footprint ──
action    : k8s.rollout_undo (proposed)
footprint : 2 pod(s), revision 25->24, policy_ok=True
policy    : within policy (affected 2 pod(s), ns demo)

── 5. evaluation: scored against fixed data ──
  payment-decline-service        100% (1/1)    100%     100%   0.90    0
  user-service-no-incident         0% (0/1)    100%    n/a   0.10    0
  order-service-discover-before-query     0% (0/1)      0%    n/a   0.60    0
  failed process checks:
    x user-service-no-incident seed0 — discover_before_retry: query_prometheus came back empty,
      retried query_prometheus without discovering

── end to end ──
  ok   1. governance   ok   2. intent   ok   3. signal plane
  ok   4. investigation   ok   4b. next step   ok   5. evaluation

6 ok, 0 failed
```

## 第一次跑是 3 ok / 3 failed

三個失敗各修了一個東西，都不在「主要功能」上：

| 失敗 | 真正的原因 | 處理 |
| --- | --- | --- |
| 4、4b 兩段 SyntaxError | 我把 JSON 解析寫成 bash 函式裡的 `python3 -c` 字串，跳脫字元疊了三層 | 拆成 `report.py` |
| 3 段報「2 leaks」 | `leakcheck.py` 掃到 runbook 自動診斷的**查詢結果**，那裡面本來就有 `v2.5.0`，因為事故是真的 | 掃描只判「人寫的」區塊，量出來的標成 `read` |
| 評測 log 一堆 `capability snapshot failed` | 那個服務在固定資料集裡沒有 inventory，`capability_for_services()` 正常回 `None`，訊息卻寫成 failed | 分開 None 與例外，改成 info |

第二個修正值得記一筆：**一個在環境正常運作時會變紅的檢查，等於教所有人忽略它。**

## 兩個環境不能同時存在

階段 5 的 stack image 沒有 Kubernetes API，所以 k8s 工具會退化成 unavailable，
`order-service` / `user-service` 那兩個 fixture 在上面的表現跟在活叢集上不一樣
（活叢集 2/2 對、固定資料 0/2）。**fixture 是跟著它被寫出來的環境長的**，換一份資料
就要重新確認它量的還是不是同一件事。
