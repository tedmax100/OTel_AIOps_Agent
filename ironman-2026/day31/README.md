# Day31：空結果不是證據，而這件事不能靠勸的

工具回空的時候，`query.py` 會補一句 `note` 說明為什麼空。那是**勸告**。這一天加的是
**判定**：每一筆工具結果進到對話之前，先由確定性規則決定它算不算證據，模型沒有投票權。

| 檔案 | 內容 |
| --- | --- |
| `probe_facts.py` | 對三個 store 各問一次「有的東西」跟「沒有的東西」，印出每一筆的判定、加總的 ledger，以及同一句答案在空的一輪跟真的一輪各自的下場。零 token |

同時改的是 agent 服務自己的原始碼：

| 檔案 | 改了什麼 |
| --- | --- |
| `app/facts.py` | 新增。`classify()` 把工具結果判成六種 disposition 之一，`ledger()` 產出注入用的台帳，`grounding_check()` 擋下「零證據卻講出結論」 |
| `app/agent.py` | `RcaState` 多一個 `facts`（每輪重置）；`tools_node` 判定、`agent_node` 每個 loop 注入 ledger、`rubric_trace` 多第三道檢查 |
| `tests/test_facts.py` | 25 條：每個 store 的「空」各一條、兩條驅動真的 graph |

## 跑探測

從 `aiops-agent/service/` 底下跑，stack 要 port-forward 好，而且**要有流量**——
沒有流量的時候，寫對的查詢也會回空，這支腳本會照實印出來而不是幫忙掩蓋：

```bash
kubectl -n demo port-forward svc/prometheus 9090:9090 &
kubectl -n demo port-forward svc/loki 3100:3100 &
kubectl -n demo port-forward svc/tempo 3200:3200 &
kubectl -n demo port-forward svc/webapp-nodeport 8002:8000 &
WEBAPP_URL=http://localhost:8002 ../../demo-services/scripts/load.sh 10 90

uv run python ../../otel-aiops-agent/ironman-2026/day31/probe_facts.py
```

```
Prometheus, a metric this stack never emits  [live]
  payload : {'resultType': 'vector', 'result': [], 'note': 'No such metric in Prometheus: payment_declines_total.', …
  verdict : empty        usable=False

Prometheus, a metric it does emit  [live]
  payload : {'resultType': 'vector', 'result': [{'metric': {'service_name': 'payment-service'}, 'value': 1.304}, …
  verdict : observed     usable=True

Loki, `service` instead of `service_name`  [live]
  payload : {'resultType': 'streams', 'result': [], 'note': 'Not an indexable stream label: service. …
  verdict : empty        usable=False

Loki, the selector that indexes  [live]
  payload : {'resultType': 'vector', 'result': [{'metric': {}, 'value': 372.0}]}
  verdict : observed     usable=True

Tempo, a window that is past retention  [live]
  payload : {'traces': [], 'count': 0}
  verdict : empty        usable=False

Tempo, the last hour  [live]
  payload : {'truncated': True, 'reason': 'Tempo result > 8192B; returning slim summaries.', 'traces': [{'traceID': …
  verdict : truncated    usable=True

k8s, a service that does not exist  [live]
  payload : {'service': 'billing-service', 'namespace': 'demo', 'pod_count': 0, 'pods': []}
  verdict : empty        usable=False

the catalog, which is never evidence  [live]
  payload : {'service': 'payment-service', 'metric_count': 6, 'identity_labels': […
  verdict : context      usable=False
```

八個 disposition 裡只有 `observed` 跟 `truncated` 算證據。`truncated` 算，是被這次
實測改的：一個服務、一小時的 Tempo 查詢就超過 8 KB 的 cap，也就是**這套 stack 裡最普通
的一次 trace 查詢就是 truncated**。第一版把它判成不可用，等於把一次成功的查詢說成沒查到。

## 台帳長什麼樣

這是每個 loop 注入給模型的東西，一筆一行：

```
EVIDENCE LEDGER (machine-typed from the tool payloads, not from your summary):
[f01] XX runtime/mechanism query_prometheus: no data in this window — MUST NOT be cited as evidence
[f02] ok runtime/mechanism query_prometheus: resultType=vector, result[6]
[f03] XX log/impact query_loki_logs: no data in this window — MUST NOT be cited as evidence
[f04] ok log/impact query_loki_logs: resultType=vector, result[1]
[f05] XX trace/mechanism query_tempo_traces: no data in this window — MUST NOT be cited as evidence
[f06] ok trace/mechanism query_tempo_traces: real but capped — cite what is in it, never a total or a rate from it
[f07] XX runtime/mechanism k8s_pod_status_tool: no data in this window — MUST NOT be cited as evidence
[f08] XX catalog/context discover_metrics_tool: catalog/reference lookup — orients the next query, not evidence
usable: 3/8 across 3 independent source(s) ['log', 'runtime', 'trace']. role is a hint from which store answered, not proof it tested that role.
```

`independent source(s)` 算的是 store 不是次數：兩句 PromQL 是一個來源，不是兩個。
`catalog` 自己一個 domain，所以「我列過這個服務有哪些 metric」永遠不會被算成一份佐證。

## 守門：同一句答案，兩種下場

```
every observation empty: SENT BACK
  Every observation this turn was unusable as evidence (discover_metrics_tool:context,
  k8s_pod_status_tool:empty, query_loki_logs:empty, query_prometheus:empty,
  query_tempo_traces:empty), yet your answer states a conclusion or quotes a number.
  Rewrite it: say which checks you ran, that each returned nothing usable, …

this turn's real facts: allowed

saying so plainly, on the same empty turn: allowed
```

門檻故意壓在地板：**零筆可用**才擋。這一層沒有把假設綁在每一步上，判斷不了「一筆夠不夠」，
只判斷得了「有沒有」。「夠不夠」是另一件事。

## 測試

```bash
uv run pytest tests/test_facts.py -q      # 25 passed
```

最後兩條會拿 stub 掉模型的真 graph 跑一輪，確認 ledger 真的離開節點、退回真的多買到一輪、
以及同一個 thread 的第二輪不會繼承第一輪的證據。
