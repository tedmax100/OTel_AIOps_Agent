# OTel_AIOps_Agent

2026 鐵人賽《AIOps with OpenTelemetry》系列的範例程式碼。

`day01/`–`day06/` 是該天文章當下整組 demo stack 的**完整快照**（不是相對前一天的 diff）——checkout 任一個資料夾，就能重現那天文章描述的狀態；純概念日只放一份指到前一次程式碼變動的 README。從 Weaver 那幾天開始，文章的產出物是獨立的 registry／policy／腳本，所以那些資料夾只放產出物本身，不再複製整組 stack。

母 repo（文章、規劃文件、其他系列內容）：[o11y-bench](https://github.com/tedmax100/o11y-bench)。

## 資料夾日號 ≠ 文章日號

文章的第一階段從 16 篇合併成 12 篇（Day2-13）之後，**資料夾名稱刻意維持原本的編號**：`dayNN/` 存的是那個時間點的完整快照，重編會失去時間順序，合併的那幾天也會撞在一起。所以有三個資料夾對應 Day3、三個對應 Day5、兩個對應 Day7。每個資料夾的 README 開頭都標明自己是哪一篇的哪一半。

| 文章 | 資料夾 | 內容 |
|---|---|---|
| Day1 | [`day01/`](./day01/) | 起手式：未治理的示範服務（`userId`/`user_id` 命名漂移、span 命名壞味道） |
| Day2 | [`day02/`](./day02/) | （純概念）AIOps 基礎概念，無程式碼異動 |
| Day3 | [`day03/`](./day03/) | （純概念）Operator pattern，無程式碼異動 |
| Day3 | [`day04/`](./day04/) | 安裝 Operator，Collector 遷移成 `OpenTelemetryCollector` CR ＋ 宣告 `Instrumentation` CR（未接 annotation） |
| Day4 | [`day05/`](./day05/) | api-gateway 改用 annotation 驅動的注入，附 collector `OOMKilled` 排查案例 |
| Day3 | [`day06/`](./day06/) | Operator 設定轉 GitOps（`kustomization.yaml` 單一入口 ＋ reviewer checklist）；`weaver/` 目錄提前建好 |
| Day5 | [`day07/`](./day07/) | Weaver 基礎：`group` 五種 `type` 各一份可執行範例，含一份故意示範 resolver 錯誤 |
| Day5 | [`day08/`](./day08/) | 第一次對 `day06/weaver/` 的 registry 跑 `weaver registry check`，含兩種錯誤的重現 |
| Day5 | [`day09/`](./day09/) | `weaver registry infer`：從真實流量反推 schema 草稿，證實兩種拼法被當成兩個 attribute 學了進去 |
| Day6 | [`day10/`](./day10/) | 命名漂移的 Rego policy：camelCase／正規化後撞名／缺 namespace 三條規則 |
| Day7 | [`day11/`](./day11/) | `weaver check` 進 CI Gate 的完整 workflow 與三個實測陷阱 |
| Day7 | [`day12/`](./day12/) | `live-check`：固定成 JSON 檔的樣本、三級 advice、六種內建 advice type |
| Day8 | [`day13/`](./day13/) | 多 registry 分層：五份 registry（base／team／collision／division／squad）＋ 兩條 policy |
| Day9 | [`day14/`](./day14/) | breaking change：四個版本的 base registry ＋ `future/` ＋ `breaking/` ＋ `team-on-v2/`，兩條比對用 policy |
| Day10 | [`day15/`](./day15/) | MCP：`mcp_probe.py`（不需 LLM 驅動 server）、`run_and_extract.py`（從真實 span 抽樣本）、before/after 範例、`team-retry/` |
| Day11 | [`day16/`](./day16/) | 意圖 YAML（兩份正確、兩份故意寫壞）、`compile_intent.py`、生成常數與 `StrEnum` 的 template |
| Day12 | [`testability/`](./testability/) | `regress.sh`：橫跨所有 fixture 的 21 條斷言，12 條預期 exit 1，零 LLM 呼叫 |
| Day13 | [`day17/`](./day17/) | 新服務 checklist：`verify_onboarding.py`（13 項可執行檢查）、範本、`shipping-v0`／`v1` 兩個對照服務 |

後續每天寫完文章，會依同樣模式新增資料夾。

## 一次跑完所有斷言

```bash
./testability/regress.sh                                 # weaver 在 PATH 裡
WEAVER=~/.local/bin/weaver ./testability/regress.sh       # 不在的話
```

不需要 cluster、不需要 API key、不需要網路，十秒內跑完。需要 `pyyaml` 與
`opentelemetry-api`／`opentelemetry-sdk`。
