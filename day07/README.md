# Day7 — （純概念）Weaver 基礎知識

對應文章：Day7（2026 鐵人賽《AIOps with OpenTelemetry》）

這天是純概念日，講「為什麼 telemetry 需要 schema」、Weaver 內部的 crate 分工（`weaver_semconv`/`weaver_resolver`/`weaver_checker`/`weaver_forge`/`weaver_live_check`/`weaver_mcp`）跟一張完整 CLI 速查表，不跑任何指令、不涉及程式碼異動——沿用 [`../day06/`](../day06/) 的狀態即可。

`../day06/weaver/` 底下其實已經有一份完整的 demo-services registry（`registry/model/*.yaml` + `policies/biz_policies.rego`），是提前建好的——Day8 才會第一次真的對它跑 `weaver registry check`。
