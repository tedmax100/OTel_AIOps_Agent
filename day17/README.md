# Day13 — 新服務上線 checklist（第一階段收尾）

對應文章：Day13（2026 鐵人賽《AIOps with OpenTelemetry》）

不動 demo stack。這裡是第一階段（Day3–11）的收斂物：一組新服務範本、一支會自己跑的
checklist，以及兩份 shipping 服務——一份故意只照抄一半（同時當 checklist 自己的測試資料）。

環境：weaver `0.24.1`，python 需要 `pyyaml`。checklist 會呼叫 `day15/mcp_probe.py`
跟 `day16/compile_intent.py`，所以那兩天的檔案要在。

```
day17/
  verify_onboarding.py          13 項檢查，每一項都真的跑一次工具；任一項失敗 exit 1
  starter/                      範本（複製後把 <service> 換掉）
    registry/manifest.yaml      schema_url 帶版本、dependencies 路徑相對 repo 根目錄
    registry/model/telemetry.yaml  屬性池 + ref + enum members
    intent/steady-state.yaml    why / first_check 用「寫清楚：」當佔位字
    .mcp.json                   帶 --include-unreferenced true
    ci/semconv-gate.yml         五個必要元素（版本釘死／sha256／diagnostic-stdout／探針／failure 補印）
  services/shipping-v0/         照抄一半的真實樣子：9/13 未通過
  services/shipping-v1/         補完版：13/13 通過
```

## 跑法

**從這個 repo 的根目錄跑。** weaver 不在 PATH 時用 `WEAVER=` 指定：

```bash
python3 day17/verify_onboarding.py day17/services/shipping-v1     # exit 0
python3 day17/verify_onboarding.py day17/services/shipping-v0     # exit 1，9 項未通過

WEAVER=~/.local/bin/weaver python3 day17/verify_onboarding.py day17/services/shipping-v1
```

平台團隊的全服務掃描（文章裡「每季一次」那個用法）：

```bash
for d in day17/services/*/; do python3 day17/verify_onboarding.py "$d"; echo; done
```

## 十三項檢查對應的那一天

| # | 檢查 | 來自 | 為什麼 |
|---|---|---|---|
| 1 | registry 存在 | Day8 | — |
| 2 | `schema_url` 帶版本號 | Day9/10 | `diff` 的版本標籤、MCP 的 `provenance.source` |
| 3 | `registry check` 通過 | Day5 | — |
| 4 | `check --future` 通過 | Day9 | 未來會變嚴的規則，現在補比之後補便宜 |
| 5 | 命名 policy | Day6 | camelCase／缺 namespace／正規化後撞名 |
| 6 | 分層 policy | Day8 | signal group 不准 inline 定義 attribute |
| 7 | group 數 > 0 | Day5/7 | 假綠燈探針 |
| 8 | 狀態類欄位有 enum members | Day5/10 | `members` 是 LLM 唯一的值域來源 |
| 9 | 有穩定狀態意圖且編得過 | Day11 | 欄位名對得上 registry |
| 10 | 意圖的 `why`／`first_check` 有填 | Day11 | 抓「完全沒動過範本」 |
| 11 | `.mcp.json` 設定正確 | Day10 | 漏 `--include-unreferenced true` 會讓 agent 查不到繼承欄位 |
| 12 | MCP 真的答得出來 | Day10 | 設定對 ≠ 答得出來，所以真的叫起來問一次 |
| 13 | CI gate 五個必要元素齊全 | Day7 | 每一項都是踩過的坑，刪掉就安靜失效 |

自動化檢查不到的一項：**required status check 要去 branch protection 設**，它不在 repo 裡。

## `shipping-v0` 是測試資料，不是教材

第 8 項第一版寫成 `name.endswith(".status")`，於是 `shippingStatus`（沒有點）整個穿過去——
一個命名壞掉的欄位，順便躲過了值域檢查。修法是把 Day6 的正規化搬過來，先去掉分隔符再比字尾。

所以 v0 要跟這支腳本一起維護：**一份永遠只跑在健康服務上的 checklist，等於從來沒被測試過。**
新增檢查項的時候，順手在 v0 裡種一個對應的違規。
