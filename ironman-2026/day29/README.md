# Day29：整條鏈跑一次

從「一個新服務要上線」到「這隻 agent 這次考幾分」，六個階段一次跑完。

| 檔案 | 內容 |
| --- | --- |
| `e2e.sh` | 六個階段依序跑，每段印關鍵輸出，最後一張 ok/FAIL 清單 |
| `report.py` | 用 agent 自己的 HTTP API 讀回調查結論與提案（含 footprint） |

## 為什麼是這個順序

1. **治理**：新服務跑一次上線檢查（Day13 的 `verify_onboarding.py`）
2. **意圖**：宣告的穩定狀態編成 alert rule（Day11 的 `compile_intent.py`）
3. **Signal Plane**：服務自己的宣告編譯成拓撲與契約，並確認沒有洩題（Day24 的 `leakcheck.py`）
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
  ./ironman-2026/day29/e2e.sh
```

agent 要從被 instrument 的入口進去，才會有 trace（Day28）：

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
