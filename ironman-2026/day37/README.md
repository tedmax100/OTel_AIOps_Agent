# Day37：第一張校準曲線

Day36 搬進來的 35 筆讓 `compute_calibration()` 第一次有東西可算，整體過度自信是 `-0.0029`，輕鬆通過 `governance_max_overconfidence = 0.1`。這天把那個數字拆開。

## `calibration_report.py`

唯讀，不寫任何東西，不需要叢集或 LLM。

```bash
# 從 o11y-bench 主 repo 的根目錄跑
python3 ironman-2026/day37/calibration_report.py
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
python3 ironman-2026/day37/backfill_grading_mode.py            # 乾跑
python3 ironman-2026/day37/backfill_grading_mode.py --apply
```

```
/home/nathan/Project/o11y-bench/aiops.db
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

Day36 開的那道鎖鎖回去了，理由是它不該開。`inconclusive` 那 20 筆沒有丟掉，改報一個不套校準數學的保留率。

新增 6 條測試（`test_calibration.py` 4 條、`test_learn.py` 2 條），其中 `test_mixing_modes_cancels_opposite_errors` 把這天的發現釘住：兩種模式混在一起時，一邊的低估會蓋掉另一邊的高估。

沒有把關卡改成讀 `ECE`，那是另一個獨立的決定。
