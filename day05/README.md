# Day5 — annotation 做 auto-instrumentation

對應文章：Day5（2026 鐵人賽《AIOps with OpenTelemetry》）

這個資料夾是這個系列 Day5 當下整組 demo stack 的完整快照，不是後續變動的 diff。完整跑法／架構說明見 [STACK-README.md](./STACK-README.md)。

## 這天的變動（相對 [`../day04/`](../day04/)）

- `services/api-gateway/Dockerfile`：拿掉 `opentelemetry-instrument` wrapper。
- `k8s/23-api-gateway.yaml`：加上 `instrumentation.opentelemetry.io/inject-python: "demo/python-instrumentation"` annotation，改由 Operator 的 admission webhook 在 Pod 建立時注入 auto-instrumentation（PYTHONPATH + init container）。
- 其餘 4 個服務刻意維持 Dockerfile-baked 的手動注入方式，作為對照組。

文章另外還收錄兩段延伸（沒有對應可執行程式碼，屬於文字案例）：公司多語言環境（Java/PHP-FPM）的 sidecar 注入設計、把 collector resource limit 調低重現 `OOMKilled` 的排查案例。

## 前置需求

同 Day4（需要先裝好 OTel Operator）。
