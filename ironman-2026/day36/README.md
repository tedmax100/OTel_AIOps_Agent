# Day36：把第一批非自我標註接進治理平面

Day37 量到 `non-self=0`。那是 `aiops.db` 的實情，不是這個 repo 的實情：`app/eval/harness.py` 從六月起就把每一輪 fixture 的信心值插進 calibration 表、再用 ground truth 標上對錯，只是寫在它自己的 `app/eval/eval.db`。

```python
DEFAULT_STORE = _HERE / "eval.db"  # separate from prod aiops.db unless overridden
```

分開存是對的（合成事故不該默默變成營運歷史），但沒有人做過那個 override，所以唯一產出外部判斷的流程，跟唯一需要外部判斷的關卡，中間沒有橋。

## `promote_labels.py`

把 `eval.db` 裡已標註的紀錄搬進治理平面讀的那個 store。

```bash
# 從 o11y-bench 主 repo 的根目錄跑
python3 ironman-2026/day36/promote_labels.py           # 乾跑，只印會搬什麼
python3 ironman-2026/day36/promote_labels.py --apply
```

刻意的設計：

| 設計 | 為什麼 |
| --- | --- |
| 只搬 `correct IS NOT NULL` | 沒有標註的紀錄對治理沒有意義 |
| `source` 原封不動保留 | 那 35 列在資料庫裡永遠標著 `eval-harness`，不會被洗成看起來像正式紀錄 |
| `run_id` 已存在就跳過 | 可以重複跑，不會灌出重複紀錄（calibration 表沒有 unique 約束） |
| 預設乾跑，`--apply` 才寫 | 會改變狀態的東西不當預設行為 |

## 實際輸出

```
source .../app/eval/eval.db
  35 labeled record(s) with source='eval-harness'
  0 already present in the target, 35 to promote

before
  target     labeled=0   non-self=0   overconfidence=None
  k8s.rollout_undo   -> propose  calibration unproven (0 labeled run(s) < 20); autonomy withheld
  k8s.scale          -> propose  calibration unproven (0 labeled run(s) < 20); autonomy withheld

promoted 35 record(s)

after
  target     labeled=35  non-self=35  overconfidence=-0.0029
  k8s.rollout_undo   -> propose  calibration ok (overconfidence -0.0029, 35 runs)
  k8s.scale          -> propose  calibration ok (overconfidence -0.0029, 35 runs)
```

## 結論

1. **兩道校準門都開了，判斷結果沒變。** `calibration unproven` → `calibration ok`，但兩個行動一樣是 PROPOSE，因為 `requires_approval` 排在校準之前（Day37 量到的順序）。三道鎖今天開了第二道。
2. **35 筆只有 3 個 fixture。** `payment-decline-service` 15 次、`order-service-discover-before-query` 10 次、`user-service-no-incident` 10 次，兩個日子跑出來的。門檻 `governance_min_human_labeled_runs` 的單位是 run，而真正該問的是獨立事故數，這裡差了一個數量級。
3. **`eval-harness` 算「非自我標註」是因為黑名單沒排除它。** `_SELF_LABEL_SOURCES` 只排除 `remediation-verified`／`remediation-failed`。harness 用 fixture 的 truth 評分，確實不是 agent 自己說了算，但錯誤訊息裡那個 `human` 沒有一筆對得上。今天沒改，理由寫在文章裡。
4. **這是一次性複製，兩邊從今天起開始分岔。** eval harness 以後還是寫 `eval.db`，要對齊得有人記得再跑一次。

Day37 的 `probe_governance.py` 在這之後再跑，`[4]` 會變成 `non-self=35 / calibration ok`，但兩個行動的 autonomy 仍是 `propose`。
