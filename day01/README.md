# Day1 — 起手式：一個沒有治理的示範服務

對應文章：Day1（2026 鐵人賽《AIOps with OpenTelemetry》）

這個資料夾是這個系列 Day1 當下整組 demo stack 的完整快照，不是後續變動的 diff。完整跑法／架構說明見 [STACK-README.md](./STACK-README.md)。

## 這天種進程式碼的東西

- `order-service` 的 `CreateOrderRequest` 用 `Field(alias="userId")` + `populate_by_name=True` 同時接受 `userId`／`user_id`。
- `api-gateway` 是 thin proxy，不經過 order-service 的轉換層，會把呼叫端原始用的 key（`userId` 或 `user_id`）原封不動寫進自己的 log／span attribute。
- `scripts/load.sh` 有 1/4 機率送 `userId`，其餘送 `user_id`——模擬「前端／後端各自正確」的命名分歧第一次真正碰撞。
- `api-gateway` 的 span name 沿用 FastAPI auto-instrumentation 預設值（`GET /api/orders/{order_id}`），沒有語意化的業務 span。

此時還沒有 OTel Operator，`k8s/13-otel-collector.yaml` 是手寫的 Collector Deployment。
