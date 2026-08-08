# Day38：過去事故庫為什麼沒有活過來

Day36 灌了 35 筆標註（`correct=1` 有 20 筆），過去事故庫仍是 0 筆。原因是 `_past_incident_context()` 撈的是一個 JOIN，而那兩張表在唯一會產出標註的那條路上只有一半有人寫。

```sql
SELECT i.payload FROM investigations i
JOIN calibration c ON c.run_id = i.fp
WHERE ... AND c.correct = 1
```

| 誰在跑 | 寫 `calibration` | 寫 `investigations` |
| --- | --- | --- |
| `webhook.handle_alert`（正式告警） | ✅ `record_run(run_id=fp)` | ✅ `record_investigation(fp, ...)` |
| `eval/harness.py`（唯一在產標註的） | ✅ | ❌ 它直接叫 `run_headless`，繞過 webhook |

還有一個更陰的：harness 的兩個 id 差兩個字元，`thread_id` 是 `eval-<fx>-s0-<nonce>`，`run_id` 是 `eval-<fx>-seed0-<nonce>`。補 `record_investigation(thread_id, ...)` 會讓 JOIN 安靜地回零筆。

## 產品端改動

| 改哪裡 | 改什麼 |
| --- | --- |
| `eval/harness.py` | 也寫 `investigations`，fp 用 `run_id`（不是 `thread_id`），`source="eval"` |
| `store.py` | `inv_query_similar` 加 `AND c.grading_mode = 'culprit'`；`CULPRIT`／`INCONCLUSIVE` 常數移到 schema 的擁有者這裡，`calibration.py` 再匯出 |

第二項是 Day37 那個欄位的用途之一：`inconclusive` 上的 `correct=1` 意思是「它正確地誰都沒怪」，把它當成一次成功解決的過去事故餵進 prompt，跟這段 context 的目的正好相反。NULL 也排除（要進 prompt 的東西，來源不明就不進）。

## `probe_past_incidents.py`

暫存 SQLite ＋真模組，無叢集無 LLM。

```bash
# 從 o11y-bench 主 repo 的根目錄跑
python3 ironman-2026/day38/probe_past_incidents.py
```

```
[1] the real store
    calibration labeled rows: 35
    investigations rows:      0
    retrievable precedent:    0

[2] a graded run with no investigation row (what the harness writes today)
    retrieved: []

[3] the same run, both tables, same id
    retrieved: ['both']

[4] rows that must never come back as precedent
    +hedged-non-incident    (correct=1 but it blamed nobody)
     retrieved: ['both']  -> excluded
    +wrong-run              (graded wrong)
     retrieved: ['both']  -> excluded
    +unlabeled              (no verdict yet)
     retrieved: ['both']  -> excluded
    +unknown-mode           (correct=1, but nobody said what that means)
     retrieved: ['both']  -> excluded
```

`[4]` 那四列都寫進兩張表、id 都對得上，差別只在標註內容。`hedged-non-incident` 在 Day37 改之前是撈得出來的。

## 測試

`tests/test_store.py` 新增 3 條，把上面的排除規則釘住（hedged non-incident、unknown mode、只有 calibration 沒有 investigation）。既有的 `_seed_investigation` helper 補上 `grading_mode` 參數，預設 `culprit`。

## 沒做的

- **A/B 沒跑**（同一組 fixture 注入 vs 不注入過去事故）。管線接上了，但要真的跑一輪 harness 才有資料，需要整套 stack 加 LLM。用合成資料做的話量到的是「編得好不好」，不是機制有沒有用。
- 六月那 35 筆的調查內容當時就沒寫，回填不了，只能從下一輪開始。
- `thread_id` / `run_id` 兩套命名沒有統一。
- 這條端到端的路沒有進 CI，探測是手動跑的。
