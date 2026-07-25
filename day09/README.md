# Day9 — `weaver registry infer`：從 Day1 服務的真實 OTLP 流量反推 schema 草稿

對應文章：Day9（2026 鐵人賽《AIOps with OpenTelemetry》）

不新增/修改任何 stack 檔案——沿用 [`../day01/`](../day01/) 的服務程式碼（`services/api-gateway`、`services/order`、`services/user`、`services/payment`）。今天的內容全部來自「真的把這些服務跑起來、送真實流量、用 `weaver registry infer` 接住 OTLP」，不是看程式碼腦補。

## 跑法

`weaver registry infer` 本身是一個 OTLP gRPC receiver，不是讀一份現成的檔案，所以要先把服務跑起來、指向它：

```bash
cd ../day01
uv sync --all-packages

# 1) 啟動 infer 的 OTLP 接收器（避開預設 4317，Day12 會講為什麼要避開）
weaver registry infer -o /tmp/day9-infer --grpc-port 14317 --admin-port 18080 --inactivity-timeout 90 &

# 2) 本機跑四個服務（不經過 k3d/collector，直接指向 infer）
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:14317
export OTEL_EXPORTER_OTLP_PROTOCOL=grpc
export OTEL_EXPORTER_OTLP_INSECURE=true
export OTEL_TRACES_EXPORTER=otlp OTEL_METRICS_EXPORTER=otlp OTEL_LOGS_EXPORTER=otlp

OTEL_SERVICE_NAME=user-service uv run opentelemetry-instrument uvicorn user_service.main:app --port 8003 &
OTEL_SERVICE_NAME=order-service USER_SERVICE_URL=http://localhost:8003 PAYMENT_SERVICE_URL=http://localhost:8001 \
  uv run opentelemetry-instrument uvicorn order_service.main:app --port 8004 &
OTEL_SERVICE_NAME=api-gateway USER_SERVICE_URL=http://localhost:8003 ORDER_SERVICE_URL=http://localhost:8004 \
  uv run opentelemetry-instrument uvicorn api_gateway.main:app --port 8005 &

# 3) 送跟 scripts/load.sh 同一套邏輯的混合流量（1/4 機率送 userId，其餘送 user_id）
#    直接打 api-gateway 的 /api/orders，見 scripts/load.sh 的邏輯

# 4) 停止接收，讀輸出
curl -X POST http://localhost:18080/stop
cat /tmp/day9-infer/registry.yaml
```

payment-service 這次刻意沒接（本機 8001 剛好被另一個既有的 k3d demo cluster佔用），不影響今天要看的重點——`userId`/`user_id` 這個壞味道發生在 `api-gateway`，跟 payment-service 無關。

## 抓到了什麼

`span.post__api_orders`（api-gateway 的 `POST /api/orders` span）底下，`userId` 跟 `user_id`被 `infer` 當成兩個完全獨立的 attribute 學了進去：

```yaml
- id: userId
  type: string
  brief: ''
  examples: u-5
  requirement_level: recommended
  ...
- id: user_id
  type: string
  brief: ''
  examples:
  - u-4
  - u-2
  - u-7
  - ''
  - u-12
  requirement_level: recommended
  ...
```

完整輸出（1852 行）沒有進 repo——它本來就只是一份丟棄式的草稿，不是治理成果。
