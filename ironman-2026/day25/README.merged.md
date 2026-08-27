# Day27：用 Day1 的量尺，量今天的 agent

Day1 那九題還在，評分器也還在。這一天把今天這隻 agent 放到同一組題目前面，
用同一支 grader 打分。

| 檔案 | 內容 |
| --- | --- |
| `rerun_bench.py` | 跑 Day1 的 `bench/tasks.yaml`，可選 `--which today` / `--which baseline`，以及 `--no-governance`（把 schema catalog 跟 signal context 拿掉） |

## 為了讓比較成立，兩件事必須固定

**同一份資料。** 那九題是對著 Day1 的產生器 stack 寫的（`http_requests_total{job=…}`），
不是 demo-services 叢集。所以兩隻 agent 都跑在同一個容器上：

```bash
docker run -d --name day27-stack -p 9090:9090 -p 3100:3100 -p 3200:3200 -p 8080:8080 \
  o11y-bench-o11y-stack:latest
```

**同一支評分器。** `bench/grade.py` 從 `day01/` 直接 import，一個字沒改。真值在打分
當下現算，所以兩隻 agent 都是跟自己跑的那一刻的資料比。

## 跑

```bash
# 今天這隻
AGENT_DIR=/path/to/o11y-bench/aiops-agent/service \
  python3 ironman-2026/day25/rerun_bench.py --which today --report /tmp/today.json

# 今天這隻，但把治理資產拿掉
AGENT_DIR=… python3 ironman-2026/day25/rerun_bench.py --which today --no-governance

# Day1 那隻
uv run --project ironman-2026/day01 python ironman-2026/day25/rerun_bench.py --which baseline
```

## 結果（同一小時、同一座 stack、每題一次）

```
  baseline (Day1 那隻)        5.5/9    metrics 1.5  logs 1.0  traces 3.0
  today                       3.5/9    metrics 1.0  logs 1.0  traces 1.5
  today (no governance)       2.5/9    metrics 0.5  logs 1.0  traces 1.0
```

今天這隻在這座 stack 上比 Day1 那隻差，原因在報告裡看得很清楚：它帶著
**另一座環境**的 schema catalog 跟 signal context，於是自信地查了不存在的東西。

```
promql-highest-backend-error-ratio  FAIL
  answer: I couldn't find a metric named `http_server_requests_total`…
traceql-error-chain-orders          PARTIAL
  call: query_tempo_traces {'traceql': '{http.request.method="POST" …}'}
        -> 400 unknown identifier: http
```

把治理資產拿掉之後更差（2.5/9），所以結論不是「治理沒用」，是
**治理是環境的函數**：對的環境上它是資產，錯的環境上它是負債，而完全沒有比帶錯的還糟。

單一種子，LLM 有變異（Day1 當時記錄的是 4.5/9，同一隻今天跑是 5.5/9），這些數字要當
訊號看，不要當測量值。
