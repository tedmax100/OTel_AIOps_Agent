# Day29：案例記憶與閉環：第八次發生時它記得什麼

文章 Day29 用到的東西。前半是「同一個事故」怎麼被認出來、誰有資格寫下結論；後半是
把整條迴圈跑到會寫進案例記憶的那一半。

| 檔案 | 內容 |
| --- | --- |
| `probe_case_memory.py` | 讀三把 key（`run_id` / `fp` / `case_key`）跟召回的實際內容 |
| `seed_case.py` | 造一筆可重現的案例（`--clear` 收回） |
| `seed_intervention.py` | 造一筆人的介入（拒絕／更正），看它變成案例上的什麼 |
| `probe_intervention_memory.py` | 讀人介入之後系統記下了什麼 |
| `close_the_loop.py` | 驅動腳本（跟 Day27 同一支，這裡跑的是 `--no-drill` 那一半） |
| `verify_incident.py` | 那條驗證查詢的探針 |
| `probe_seed_variance.py` | 量同一題重跑的擺盪 |

`ab-*.txt` 是當時「有沒有案例記憶」的 A/B 逐字輸出，`eval-*` / `passes-*` / `verify-*`
是那幾輪的原始輸出。

> 文章末尾那段後記（召回其實一直回空字串，直到有人把 `root_cause` 填進去）是後來補測
> 出來的，用的是 `app/agent.py` 的 `_past_incident_context()`，不需要這裡的腳本。

## 這一天是從哪幾天合併過來的

下面保留了合併之前每一份原始筆記，內容沒有改寫，所以裡面的日號指的是舊的編排。

- [`README.day31-case-memory.md`](README.day31-case-memory.md)（案例記憶那半）
- [`README.day32-close-loop.md`](README.day32-close-loop.md)（閉環那半）
- [`README.day38.md`](README.day38.md)
- [`README.day39.md`](README.day39.md)
