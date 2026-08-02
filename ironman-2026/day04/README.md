# Day4 — 注入了不代表送達

對應文章：**Day4**（《賢者大叔的觀測結界》第四天）。

這個資料夾是 Day4 做完之後、整組 demo stack 的**完整快照**。架構說明見 [STACK-README.md](./STACK-README.md)。

## 這一天改了什麼

| 路徑 | 變動 |
|---|---|
| `services/api-gateway/Dockerfile` | 拿掉 `opentelemetry-instrument` 包裝指令，`CMD` 變回單純的 `uvicorn` |
| `k8s/23-api-gateway.yaml` | Pod template 加上 `instrumentation.opentelemetry.io/inject-python` annotation |

只換了 `api-gateway` 一個服務，另外四個仍然是 Dockerfile 裡的 `opentelemetry-instrument`。這是刻意的。

## 驗證注入真的發生了

```bash
./ironman-2026/day04/scripts/up.sh

# 應該會看到 Init:0/1 —— 那個 init container 是 webhook 塞進去的
kubectl -n demo get pods -l app=api-gateway

# webhook 塞了什麼：init container、PYTHONPATH、被接長的 OTEL_RESOURCE_ATTRIBUTES
kubectl -n demo get pod -l app=api-gateway -o yaml | less
```

三件值得自己看一次的事：

1. **init container** 只做 `cp`，把 auto-instrumentation 套件複製到共用的 `emptyDir`。
2. **`PYTHONPATH`** 被設好，靠 `sitecustomize` 機制在直譯器啟動時自動掛上 SDK，所以 `CMD` 不用包指令。
3. **`OTEL_SERVICE_NAME` 跟 `OTEL_EXPORTER_OTLP_ENDPOINT` 沒有被覆蓋**（webhook 補齊沒有的、不動已存在的），但 `OTEL_RESOURCE_ATTRIBUTES` 被接上了一段 `k8s.*` 屬性。

## 重現「注入了不代表送達」

文章後半段那個實驗。重點是**先量基準，再只動一個變因**，否則數字沒有意義。

### 1. 給足記憶體，在負載下量基準

```bash
# 開幾個負載，湊到 ~300 rps
for i in 1 2 3 4 5; do ./ironman-2026/day04/scripts/load.sh 40 900 & done

kubectl -n demo set resources deployment otel-collector \
  --limits=memory=512Mi --requests=memory=128Mi

# 等它穩定，記下記憶體用量
kubectl -n demo top pod -l app=otel-collector
```

### 2. 讀 collector 自己的計數器，間隔 60 秒取差值

```bash
POD=$(kubectl -n demo get pod -l app=otel-collector --no-headers | awk '{print $1}' | head -1)
kubectl -n demo port-forward pod/$POD 18888:8888 &

curl -s localhost:18888/metrics | grep -E "^otelcol_(receiver_accepted_spans|exporter_sent_spans|exporter_send_failed_spans)"
# 等 60 秒再讀一次，兩次相減
```

### 3. 只把 limit 壓低，負載不要動

```bash
kubectl -n demo set resources deployment otel-collector \
  --limits=memory=64Mi --requests=memory=32Mi

kubectl -n demo describe pod -l app=otel-collector | grep -E "Reason:|Exit Code:|Restart Count:"
```

### 4. 量使用者視角的損失

```bash
kubectl -n demo port-forward svc/tempo 13200:3200 &
NOW=$(date +%s)
curl -s "localhost:13200/api/search?q=%7B%7D&start=$((NOW-10))&end=$NOW&limit=5000" \
  | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('traces') or []))"
```

### 5. 確認 app 完全沒察覺

```bash
kubectl -n demo logs -l app=api-gateway --tail=300 | grep -icE "failed to export|export.*error|connection refused"
kubectl -n demo get pods -l 'app in (api-gateway,order-service,payment-service,user-service,webapp)'
curl -o /dev/null -w "HTTP %{http_code} %{time_total}s\n" http://localhost:8002/api/users
```

### 6. 收工，把 limit 拿掉

```bash
kubectl -n demo patch deployment otel-collector --type=json \
  -p='[{"op":"replace","path":"/spec/template/spec/containers/0/resources","value":{}}]'
pkill -f load.sh
```

## 我實際跑出來的數字

在 ~300 rps 下，供對照用：

| | 健康（limit 512Mi） | 壓垮（limit 64Mi） |
|---|---|---|
| 記憶體 | 81Mi | 撐不到 20 秒 |
| 60 秒收到 spans | 146,956 | 端點連不上（容器沒活著） |
| 60 秒送出 spans | 149,024 | 同上 |
| 送出失敗 | 0 | 同上 |
| Tempo 每 10 秒 trace 數 | 1602 / 1599 / 1596 / 1608 | 1322 → 1022 → **0** |
| app 端 exporter 錯誤 | 0 | **0** |
| 五個服務重啟次數 | 0 | **0** |
| webapp 回應 | HTTP 200 | **HTTP 200，10-23ms** |

三個值得記住的點：

- **死因不是 `OOMKilled` 這個字串。** `kubectl describe` 給的是 `Reason: Error` 加 `Exit Code: 137`（128+9，被 SIGKILL）。排查腳本去 grep `OOMKilled` 會抓不到。
- **資料是滑下去的，不是斷崖。** collector 在 crashloop，每一輪活著的幾秒還是送得出東西，所以 dashboard 看起來像「有點少」而不是「壞了」。
- **要診斷它的資料，跟它一起消失。** crashloop 期間 `:8888/metrics` 連不上，而這套 stack 的 Prometheus 從來沒有在抓 `otelcol_*`，所以事後回頭查「什麼時候開始掉的」查不到。Operator 生的 `otel-collector-monitoring` Service（`8888`）就是為了接這件事，只是還沒有人接。

## 對照實驗：加上 `memory_limiter`

同樣的 64Mi、同樣的負載，差別只有 collector config 多一個 processor。

```yaml
processors:
  memory_limiter:
    check_interval: 1s
    limit_percentage: 75
    spike_limit_percentage: 15
  batch:
    timeout: 5s

service:
  pipelines:
    traces:
      processors: [memory_limiter, batch]    # 必須放在第一個
```

```bash
kubectl -n demo create cm otel-collector-config \
  --from-file=config.yaml=<改好的 config> --dry-run=client -o yaml | kubectl apply -f -
kubectl -n demo rollout restart deploy otel-collector

kubectl -n demo logs -l app=otel-collector | grep -i memorylimiter
curl -s localhost:18888/metrics | grep -E "^otelcol_receiver_(accepted|refused)_spans"
```

實跑結果：

| 同樣 64Mi、同樣負載 | 沒有 `memory_limiter` | 有 `memory_limiter` |
|---|---|---|
| collector | `exit 137`、重啟 3 次、CrashLoopBackOff | Running，重啟 0 次 |
| 掉了多少資料 | 查不到（metrics 端點也死了） | `refused_spans` = 26,225 |
| Tempo 每 10 秒 trace | 1322 → 1022 → 0 | 19 → 671 → 960 |
| app 端 log | 0 筆 | 3 筆 export 錯誤 |
| collector 自己的 log | 無（被 SIGKILL） | `Memory usage is above soft limit. Refusing data.` |

**兩邊都掉資料，差別是第二種掉得有聲音。**

## 今天刻意沒做的事

- 沒有把其他四個服務也換成 annotation 注入。
- **沒有把 collector 的自我遙測接進 Prometheus。** 洞指出來了，補上要另外決定告警門檻，是另一個題目。
- OOM 只驗證了「共用一份 collector 的 Deployment」這一種拓撲，sidecar 跟 daemonset 沒測。
