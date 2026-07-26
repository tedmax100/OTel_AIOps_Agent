# Day3 — （純概念）OTel Operator 基礎概念

對應文章：Day3（2026 鐵人賽《AIOps with OpenTelemetry》）

> 資料夾的日號沿用文章重編之前的編號。這是文章合併前的原 Day3（純概念那半）。Day3 現在把概念、CRD 實作、GitOps 收尾合成一篇。

這天是純概念日，講 Kubernetes Operator pattern（CRD／controller／reconciliation loop）跟 `OpenTelemetryCollector`／`Instrumentation` 兩種 CR 的分工，不碰真實 cluster、不涉及程式碼異動——沿用 [`../day01/`](../day01/) 的狀態即可。
