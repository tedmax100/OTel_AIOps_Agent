# Day31：把第一批非自我標註接進治理平面

Day31 量到 `non-self=0`。那是 `aiops.db` 的實情，不是這個 repo 的實情：`app/eval/harness.py` 從六月起就把每一輪 fixture 的信心值插進 calibration 表、再用 ground truth 標上對錯，只是寫在它自己的 `app/eval/eval.db`。

```python
DEFAULT_STORE = _HERE / "eval.db"  # separate from prod aiops.db unless overridden
```

分開存是對的（合成事故不該默默變成營運歷史），但沒有人做過那個 override，所以唯一產出外部判斷的流程，跟唯一需要外部判斷的關卡，中間沒有橋。

## `promote_labels.py`

把 `eval.db` 裡已標註的紀錄搬進治理平面讀的那個 store。

```bash
# 從範例 repo 的根目錄跑
python3 ironman-2026/day31/promote_labels.py           # 乾跑，只印會搬什麼
python3 ironman-2026/day31/promote_labels.py --apply
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

1. **兩道校準門都開了，判斷結果沒變。** `calibration unproven` → `calibration ok`，但兩個行動一樣是 PROPOSE，因為 `requires_approval` 排在校準之前（Day31 量到的順序）。三道鎖今天開了第二道。
2. **35 筆只有 3 個 fixture。** `payment-decline-service` 15 次、`order-service-discover-before-query` 10 次、`user-service-no-incident` 10 次，兩個日子跑出來的。門檻 `governance_min_human_labeled_runs` 的單位是 run，而真正該問的是獨立事故數，這裡差了一個數量級。
3. **`eval-harness` 算「非自我標註」是因為黑名單沒排除它。** `_SELF_LABEL_SOURCES` 只排除 `remediation-verified`／`remediation-failed`。harness 用 fixture 的 truth 評分，確實不是 agent 自己說了算，但錯誤訊息裡那個 `human` 沒有一筆對得上。今天沒改，理由寫在文章裡。
4. **這是一次性複製，兩邊從今天起開始分岔。** eval harness 以後還是寫 `eval.db`，要對齊得有人記得再跑一次。

Day31 的 `probe_governance.py` 在這之後再跑，`[4]` 會變成 `non-self=35 / calibration ok`，但兩個行動的 autonomy 仍是 `propose`。

---

## 第一張校準曲線

Day31 搬進來的 35 筆讓 `compute_calibration()` 第一次有東西可算，整體過度自信是 `-0.0029`，輕鬆通過 `governance_max_overconfidence = 0.1`。這天把那個數字拆開。

## `calibration_report.py`

唯讀，不寫任何東西，不需要叢集或 LLM。

```bash
# 從範例 repo 的根目錄跑
python3 ironman-2026/day31/calibration_report.py
```

四個切面：

| # | 看什麼 |
| --- | --- |
| 1 | 關卡讀的那一個數字，跟它算完就丟掉的另外三個 |
| 2 | 那個數字背後的分箱（可靠度圖） |
| 3 | 同一批紀錄按 fixture 拆開 |
| 4 | 按評分模式拆開：`culprit` vs `inconclusive` |

## 實際輸出

```
[1] what the gate reads
  labeled=35  overconfidence=-0.0029  tolerance=0.1
  ece=0.1743  mce=1.0  brier=0.2329
  the whole store                        -> auto     calibration ok (overconfidence -0.0029, 35 runs)

[2] the reliability diagram behind that one number
  band        n    stated  actual  gap
  [0.0,0.1)  2    0.0     1.0     1.0    ->
  [0.1,0.2)  4    0.1     0.0     0.1    <-
  [0.3,0.4)  2    0.3     0.0     0.3    <-
  [0.6,0.7)  12   0.6     0.5833  0.0167
  [0.7,0.8)  6    0.7     0.8333  0.1333 ->
  [0.8,0.9)  6    0.8     0.5     0.3    <-
  [0.9,1.0)  3    0.9     1.0     0.1    ->
  (<- stated above actual = overconfident;  -> stated below actual = underconfident)

[3] the same rows, per fixture
  payment-decline-service (culprit)      n=15  conf=0.72   acc=1.0    overconf=-0.28    ece=0.28
  user-service-no-incident (inconclusive) n=10  conf=0.34   acc=0.3    overconf=+0.04    ece=0.44
  order-service-discover-before-query (inconclusive) n=10  conf=0.57   acc=0.2   overconf=+0.37  ece=0.37

[4] split by grading mode
  culprit fixtures ('blame was right')   n=15  conf=0.72   acc=1.0    overconf=-0.28    ece=0.28
  inconclusive fixtures ('it hedged')    n=20  conf=0.455  acc=0.25   overconf=+0.205   ece=0.405

  culprit fixtures only                  -> propose  calibration unproven (15 labeled run(s) < 20); autonomy withheld
  everything (what the gate does today)  -> auto     calibration ok (overconfidence -0.0029, 35 runs)
```

## 結論

1. **關卡只讀 `overconfidence`，而它是四個指標裡唯一會抵銷的。** `ECE` 0.1743 用同一個 0.1 門檻會被擋下來，但它算完就丟。
2. **`-0.0029` 是 `-0.28` 跟 `+0.205` 加起來的。** 這隻 agent 在它真的會的那題低估自己（15/15 全對而信心只給 0.72），在不會的那兩題高估自己。它不是普遍太有自信，是分不出自己會不會。
3. **`[0.8,0.9)` 那一箱只對一半，而 0.8 正好是 `governance_conf_high`。** 最不可信的信心區間就是決定放不放手的那一格。
4. **兩種評分模式寫進同一個 `correct` 欄位。** `culprit` 問「兇手指對了嗎」，`inconclusive` 問「有沒有適當保留」，而 `compute_calibration()` 的數學只假設前者。一筆信心 0.0 且正確的紀錄（正確地拒絕亂猜）被算成 gap 1.0，`MCE = 1.0` 就是這樣來的。
5. **只算 `culprit` 那 15 筆，關卡的回答是「標註不夠」；混進另外 20 筆，回答變成「校準良好、可以放手」。**

## 後續：`grading_mode`

寫完之後把第 4 點做掉了，因為 `inv_query_similar()` 撈過去事故的條件是 `c.correct = 1` — 照原本的標法，「在非事故上正確地保留」會被當成一次成功解決的過去事故餵給 agent。

產品端的改動：

| 改哪裡 | 改什麼 |
| --- | --- |
| `store.py` | calibration 表加 `grading_mode TEXT`（additive migration）；`cal_insert` / `cal_label` 可帶；`cal_count_by_source` 加 `modes` 過濾 |
| `calibration.py` | `CalibrationRecord.grading_mode`、`filter_by_mode()`、`compute_calibration(..., modes=)`、`hedging_rate()` |
| `config.py` | `governance_calibration_modes: list[str] = ["culprit"]` |
| `governance.py` / `agent.py` | 人工標註下限與校準曲線都只算 `culprit`，NULL 不算（fail-closed） |
| `eval/harness.py` | insert 與 label 都帶上 fixture 的 `expect` |
| `main.py` | plugin 上人按對錯那條路填 `culprit` |

`cal_label` 用 `COALESCE(?, grading_mode)`，所以沒有意見的標註者不會把既有的模式抹掉。

### `backfill_grading_mode.py`

欄位加上去之前寫的紀錄是 NULL，而 NULL 是 fail-closed，所以要回填。模式從 run_id 還原（`eval-<fixture>-seed<n>-<nonce>` → `fixtures.yaml[fixture].expect`），不是 eval run 的一律留 NULL。

```bash
python3 ironman-2026/day31/backfill_grading_mode.py            # 乾跑
python3 ironman-2026/day31/backfill_grading_mode.py --apply
```

```
.../aiops.db
  35 row(s) with no grading_mode
  resolvable: {'culprit': 15, 'inconclusive': 20};  left NULL: 0
  updated 35 row(s); now {'culprit': 15, 'inconclusive': 20}
```

### 改完之後

```
[4] split by grading mode
  culprit ('blame was right')            n=15  conf=0.72   acc=1.0    overconf=-0.28    ece=0.28
  inconclusive ('it hedged')             n=20  conf=0.455  acc=0.25   overconf=+0.205   ece=0.405

  culprit only (what the gate does now)  -> propose  calibration unproven (15 labeled run(s) < 20); autonomy withheld
  everything (what it did before)        -> propose  insufficient human/grader labels (15 < 20); self-produced labels cannot unlock AUTO

[5] the inconclusive rows, reported as what they actually measure
  hedged appropriately on 5/20 non-incidents (rate 0.25), mean stated confidence 0.455
```

Day31 開的那道鎖鎖回去了，理由是它不該開。`inconclusive` 那 20 筆沒有丟掉，改報一個不套校準數學的保留率。

新增 6 條測試（`test_calibration.py` 4 條、`test_learn.py` 2 條），其中 `test_mixing_modes_cancels_opposite_errors` 把這天的發現釘住：兩種模式混在一起時，一邊的低估會蓋掉另一邊的高估。

沒有把關卡改成讀 `ECE`，那是另一個獨立的決定。
