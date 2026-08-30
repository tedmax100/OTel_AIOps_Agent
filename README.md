# OTel_AIOps_Agent

2026 鐵人賽《AIOps with OpenTelemetry》系列的範例程式碼。

母 repo（文章、規劃文件、其他系列內容）：[o11y-bench](https://github.com/tedmax100/o11y-bench)。

## 這一季的東西全部在 `ironman-2026/` 底下

資料夾日號跟文章日號一致：文章 DayN 對應 [`ironman-2026/dayNN/`](./ironman-2026/)。純概念日沒有自己的資料夾（Day2、Day17–Day19、Day26），那幾天沿用前一次變動的狀態。

`ironman-2026/day03/` 跟 `ironman-2026/day04/` 存的是整組 demo stack 的**完整快照**——checkout 任一個就能重現那天文章描述的狀態。從 Weaver 那幾天開始，每天的產出物是獨立的 registry／policy／腳本，所以後面的資料夾只放那天真的用到的東西，通常是一兩個腳本加一份 `README.md`。

> 根目錄還留著 `day01/`、`day04/`–`day17/` 跟 `testability/`。那是上一輪編號的殘留，跟現在的文章沒有對應關係——不要拿它們的內容當事實來源。

### 第一階段：平台工程視角的治理

| 文章 | 資料夾 | 內容 |
|---|---|---|
| Day1 | [`day01/`](./ironman-2026/day01/) | 失敗現場：一個查得動 Prometheus 的 agent，為什麼只拿 4.5/9 |
| Day3 | [`day03/`](./ironman-2026/day03/) | OTel Operator：把「持續維護」從人身上搬到迴圈裡 |
| Day4 | [`day04/`](./ironman-2026/day04/) | 注入了不代表送達（sidecar ＋ collector `OOMKilled` 排查） |
| Day5 | [`day05/`](./ironman-2026/day05/) | Weaver 上手：schema 是團隊共識，不是觀察結果 |
| Day6 | [`day06/`](./ironman-2026/day06/) | 命名漂移：用 Rego policy 把它攔下來 |
| Day7 | [`day07/`](./ironman-2026/day07/) | 治理成為門：CI gate 與 live-check 的兩個時間點 |
| Day8 | [`day08/`](./ironman-2026/day08/) | 分層與所有權：哪一層統一、哪一層放手 |
| Day9 | [`day09/`](./ironman-2026/day09/) | breaking change 與三層驗證模型 |
| Day10 | [`day10/`](./ironman-2026/day10/) | registry 成為 agent 的工具（MCP） |
| Day11 | [`day11/`](./ironman-2026/day11/) | 機器可讀的意圖，與 codegen |
| Day12 | [`day12/`](./ironman-2026/day12/) | 不用 LLM 也能驗證治理資產：`regress.sh` 29 條斷言，零 LLM 呼叫 |
| Day13 | [`day13/`](./ironman-2026/day13/) | 讀現況：新服務上線 checklist |

### 第二階段：AIOps 核心能力管線

| 文章 | 資料夾 | 內容 |
|---|---|---|
| Day14 | [`day14/`](./ironman-2026/day14/) | 拓撲對帳：那張圖準不準 |
| Day15 | [`day15/`](./ironman-2026/day15/) | 把 registry 接進 Signal Plane |
| Day16 | [`day16/`](./ironman-2026/day16/) | 順著圖走的異常偵測，跟它走不到的地方 |

### 第三階段：讓 agent 讀懂決策級事件、給分數、給建議

| 文章 | 資料夾 | 內容 |
|---|---|---|
| Day20 | [`day20/`](./ironman-2026/day20/) | agent 開始想之前，手上有什麼 |
| Day21 | [`day21/`](./ironman-2026/day21/) | 先把量尺修好，再讓 fixture 去讀逐字稿 |
| Day22 | [`day22/`](./ironman-2026/day22/) | 工具回什麼，決定 agent 能想什麼 |
| Day23 | [`day23/`](./ironman-2026/day23/) | 下一步建議，要連「多大」一起講 |
| Day24 | [`day24/`](./ironman-2026/day24/) | 使用者到底拿到了什麼：入口、格式、帳單 |
| Day25 | [`day25/`](./ironman-2026/day25/) | agent 自己的決策，回放得了嗎 |

### Series 2：這個建議準不準、能不能治理、能不能自我校正

| 文章 | 資料夾 | 內容 |
|---|---|---|
| Day27 | [`day27/`](./ironman-2026/day27/) | 提案是一列會自己走完的狀態，而演習決定那列數不數 |
| Day28 | [`day28/`](./ironman-2026/day28/) | 五道門：信心分數要先能被查證，以及另外四道不問準不準的門 |
| Day29 | [`day29/`](./ironman-2026/day29/) | 案例記憶與閉環：第八次發生時它記得什麼 |
| Day30 | [`day30/`](./ironman-2026/day30/) | 量錯四次：時鐘、排練、一次錯的更正，跟那支查它們的探針 |
| Day31 | [`day31/`](./ironman-2026/day31/) | 空結果不是證據，而這件事不能靠勸的 |
| Day32 | [`day32/`](./ironman-2026/day32/) | 一個對的診斷，配一個沒用的處置 |
| Day33 | [`day33/`](./ironman-2026/day33/) | 回到第一天那組題目：收尾狀態的唯讀探針 |

## 一次跑完所有斷言

```bash
./ironman-2026/day12/regress.sh                                 # weaver 在 PATH 裡
WEAVER=~/.local/bin/weaver ./ironman-2026/day12/regress.sh       # 不在的話
```

29 條斷言，其中 8 條的預期離開碼是 1（測「該紅的還會不會紅」，不是「會不會通過」）。不需要 cluster、不需要 API key、不需要網路，約 40 秒跑完。需要 `pyyaml` 與 `opentelemetry-api`／`opentelemetry-sdk`。

## 最後一天的狀態

Day33 那些「現在的狀況」會過期，所以它們可以重算：

```bash
python3 ironman-2026/day33/probe_closing_state.py
```

唯讀。四段：這座環境醒著沒有、四道自治的門、動作有沒有解決事故加上涵蓋率、沒被執行的提案最後怎麼了。
