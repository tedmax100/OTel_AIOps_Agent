# Day4 — 安裝 OTel Operator，拆解真實的 CRD 實作

對應文章：Day4（2026 鐵人賽《AIOps with OpenTelemetry》）

這個資料夾是這個系列 Day4 當下整組 demo stack 的完整快照，不是後續變動的 diff。完整跑法／架構說明見 [STACK-README.md](./STACK-README.md)。

## 這天的變動（相對 [`../day01/`](../day01/)）

- `k8s/13-otel-collector.yaml`：手寫的 Collector `Deployment`/`Service`/`ConfigMap` 換成 `OpenTelemetryCollector` CR（`spec.config` 原封不動搬過去），CR 故意命名為 `otel` 而不是 `otel-collector`，讓 Operator 生成的 Service 名稱剛好對上其他服務寫死的 `OTEL_EXPORTER_OTLP_ENDPOINT`。
- `k8s/16-instrumentation.yaml`：新增 `Instrumentation` CR（宣告 Python auto-instrumentation 設定），**但故意還沒有任何 Pod annotation 接上它**——五個服務仍靠 Dockerfile 裡的 `opentelemetry-instrument` 手動注入。

## 前置需求

需要先裝好 OTel Operator（Helm chart，`admissionWebhooks.autoGenerateCert.enabled=true`），細節見文章。
