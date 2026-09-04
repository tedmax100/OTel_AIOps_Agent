# Day33：回到第一天那組題目

這一天不改 agent 的任何一行。`probe_closing_state.py` 是一支唯讀探針，把那篇文章引用的每一個「現在的狀況」在一次執行裡重算出來——因為 Day33 是整個系列唯一會過期的一篇，它描述的是一個還在動的系統。**探針跟文章不一致的時候，比較舊的是文章。**

| 檔案 | 內容 |
| --- | --- |
| `probe_closing_state.py` | 五段：這座環境醒著沒有、四道自治的門、動作有沒有解決事故加上它涵蓋了幾成、沒被執行的提案最後怎麼了、覆寫率跟派發率（ARE 第11章）。零 token |
| `closing-20260830.txt` | 2026-08-30 的實際輸出，是文章正文大部分數字的來源；覆寫率那段是收尾後才補的，見下 |

## 覆寫率（Override Rate）是後來補的第五段

讀 [ARE 第11章](https://tedmax100.github.io/agentic-reliability-engineering-zh-tw/ch11.html)
才發現覆寫率跟建議接受率這兩個信任指標，`service/app/` 裡從來沒算過。資料早就在
`action_requests` 跟 `audit` 兩張表裡，補的是 `app/store.py` 裡一支新函式
`override_rate()`，邏輯上跟既有的 `proposal_disposition()` 是同一類：唯讀、直接查
SQLite、回傳一個可以印也可以斷言的 dict。

這支函式唯一不平凡的地方是分母。`action_requests.status == 'aborted'` 的那些一開始
看起來像「人類駁回」，但查 `audit` 才發現全部 `actor == 'system'`：拆開三種
phase，6 筆是冪等擋下的重複提案、3 筆是 `blast_radius.py` 的 dry-run、1 筆是斷路器
跳開，沒有一筆是人類在核准畫面上按了拒絕。把這些算進「人類駁回」會讓 OR 從誠實的
0% 膨脹成看起來健康的 31%——這正是 `override_rate()` 的 docstring 想擋下來的事。

```bash
python3 ironman-2026/day33/probe_closing_state.py
# 或
python3 -c "from app import store; print(store.override_rate())"
```

真實輸出（跟文章裡引用的一致）：

```json
{
  "total": 32, "dispatched": 19, "dispatch_rate": 0.594,
  "rejected": 0, "override_rate": 0.0,
  "system_aborts_excluded_from_denominator": 10,
  "note": "zero rejections — either a very well-calibrated agent, or nobody has said no yet; below the reporting floor this can't tell the two apart"
}
```

## 為什麼第一段是「這座環境醒著沒有」

因為一座閒置的叢集、一個一小時的 trace 保存期、跟一隻真的壞掉的 agent，在報表上會寫出同一句話：這一步沒有拿到東西。這系列後段我把第一種讀成第三種讀了好幾天。所以那一段放在最前面，而且在它安靜的時候，探針不會再往下多解釋任何一個數字。

判準是 Prometheus 上有多少條 series 正在被寫。少於 100 條就是「只剩自動儀器化跟 SDK 自己的」，那時候底下每一個數字量的都是環境，不是這套系統。

## 為什麼比率旁邊要印涵蓋率

那條「動作有沒有真的解決事故」的比率，分母原本是**被標記過的那些**，不是**真的跑過的那些**。九次動作碰過叢集、三筆有裁決，而報表印的是那三筆算出來的漂亮數字——另外六次不是低分，是不在任何一個畫面上。`coverage` 那三個數字（ran / graded / ungraded）就是為了讓「還沒有人判」跟「判過而且不好」長得不一樣。

## 跑

從 repo 根目錄跑。預設打進叢集裡的 pod（讀 `/data/aiops.db`）：

```bash
python3 ironman-2026/day33/probe_closing_state.py
```

改成對本機的 checkout 跑：

```bash
python3 ironman-2026/day33/probe_closing_state.py --local
```

`--local` 會在 `aiops-agent/service/` 底下執行，所以那個目錄要有裝好的環境跟一份 store。

全程唯讀：它開幾個 SQLite 檔、問 Prometheus 一次 count。不寫入、不提案、不執行任何動作。
