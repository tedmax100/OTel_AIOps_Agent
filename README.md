# OTel_AIOps_Agent

2026 鐵人賽《AIOps with OpenTelemetry》系列的範例程式碼。

每個 `dayXX/` 資料夾是該天文章當下整組 demo stack 的**完整快照**（不是相對前一天的 diff）——checkout 任一個資料夾，就能重現那天文章描述的狀態。純概念日（不涉及程式碼異動）只放一份指到前一次程式碼變動的 README。

母 repo（文章、規劃文件、其他系列內容）：[o11y-bench](https://github.com/tedmax100/o11y-bench)。

## Day 對照表

| Day | 資料夾 | 內容 |
|---|---|---|
| Day1 | [`day01/`](./day01/) | 起手式：未治理的示範服務（`userId`/`user_id` 命名漂移、span 命名壞味道） |
| Day2 | [`day02/`](./day02/) | （純概念）AIOps 基礎概念，無程式碼異動 |
| Day3 | [`day03/`](./day03/) | （純概念）OTel Operator 基礎概念，無程式碼異動 |
| Day4 | [`day04/`](./day04/) | 安裝 OTel Operator，Collector 遷移成 `OpenTelemetryCollector` CR + 宣告 `Instrumentation` CR（未接 annotation） |
| Day5 | [`day05/`](./day05/) | api-gateway 改用 annotation 驅動的 auto-instrumentation 注入，附 collector `OOMKilled` 排查案例 |
| Day6 | [`day06/`](./day06/) | Operator 設定轉 GitOps；`weaver/` 目錄提前建好（registry + `biz_policies.rego` 自訂 policy） |
| Day7 | [`day07/`](./day07/) | （純概念）Weaver 基礎知識，無程式碼異動 |
| Day8 | [`day08/`](./day08/) | 第一次真的對 `day06/weaver/` 的 registry 跑 `weaver registry check`（含 resolver/checker 兩種錯誤的示範性重現） |

後續每天寫完文章，會依同樣模式新增 `dayXX/` 資料夾。
