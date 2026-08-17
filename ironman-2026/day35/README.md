# Day35：五個旗艦 SLO，跟階梯上真正的位置

回顧日。不寫新機制，只把 ARE 3.6 那五個旗艦 SLO 對著**叢集自己的 store** 算一次，看哪幾個是量測、哪幾個是 0/0、哪幾個量到的其實是我的手。

## 重現步驟

`cluster-snapshot.db` 是 2026-08-09 從 k3d `demo` namespace 裡那顆 agent pod 撈出來的 `/data/aiops.db`，已經放在這個資料夾裡，所以腳本不需要叢集也不需要 LLM：

```bash
# 從範例 repo 的根目錄跑
python3 ironman-2026/day35/slo_report.py
```

要自己重新取一份快照：

```bash
POD=$(kubectl -n demo get pod -l app=aiops-agent -o name | head -1)
kubectl -n demo cp "${POD#pod/}":/data/aiops.db ironman-2026/day35/cluster-snapshot.db
```

## 五段輸出

### [1] 同一份 schema，兩個 store，兩段不同的歷史

```
  table              dev (aiops.db)    cluster /data
  calibration                    35               15
  investigations                  0               15
  action_requests                 0               13
  executions                      0                1
  audit                           0               28
  cluster labels by source: ui=7
  cluster non-self labels: 7   (Day31 measured this as 0 on the dev store)
```

Day31-38 三天量的都是 dev store。叢集那份從頭到尾有它自己的資料：**7 筆來源 `ui` 的人工標註**，以及 15 筆 `investigations`——也就是 Day31 說「不存在」的非自我標註，跟 Day32 說「空的」那張表。

### [2] 叢集還沒看過的那個欄位

```
  cluster calibration.grading_mode present: False
  gate reads modes=('culprit',) (NULL never matches — fail-closed on unknowns)
  after migration, grading_mode present: True
  labeled rows: 7   eligible for the curve after: 0
```

`_MIGRATIONS` 是連線時自動跑的加欄位，所以新 image 上去的那一刻，那 7 筆的 `grading_mode` 會是 NULL，而 NULL 不匹配任何 mode 篩選（Day31 刻意設計成 fail-closed）。**唯一一批真人標註會在遷移完成的那一秒變成不算數。**

### 修法：`fix_grading_mode.py`

加欄位的遷移寫了，填欄位的那半沒寫。那 7 筆的模式是知道的（plugin 上按對／錯，對象是指名兇手的 RCA，就是 `culprit`），所以回填它們，其餘真的不知道的留 NULL。

```bash
# 乾跑（對複製出來的一份做，預設）
python3 ironman-2026/day35/fix_grading_mode.py

# 對某一份 store 就地套用
python3 ironman-2026/day35/fix_grading_mode.py --store /data/aiops.db --apply
```

```
[1] before   labeled=0 non-self=0 ece=None
             gate: propose  calibration unproven (0 labeled run(s) < 20)
[2] backfill grading_mode='culprit' for labeled rows from ('ui',)  -> 7 rows
[3] after    labeled=7 non-self=7 ece=0.5643 overconfidence=0.3929
             gate: propose  calibration unproven (7 labeled run(s) < 20)

  reliability diagram over the labels that now count
    band        n    stated   actual   gap
    [0.2,0.3)   2    0.2      0.5      0.3
    [0.8,0.9)   3    0.8167   0.0      0.8167
    [0.9,1.0)   2    0.95     0.5      0.45
```

兩句都是紅燈，但「7 筆，還差 13 筆」是可以靠做事解決的紅燈。而 `[0.8,0.9)` 那一格是三筆全錯，`0.8` 正是 `governance_conf_high`。

已於 2026-08-09 套用到 k3d `demo` 那顆 pod 的 `/data/aiops.db`（套用前備份在同目錄的 `aiops.db.bak-day34`）。`cluster-snapshot.db` 保留的是**回填之前**的狀態，所以上面兩支腳本都還重現得出文章裡的輸出。

### [3] 五個旗艦 SLO

```
  ARR     0 / 3 -> 0.0%          （真的 0：13 筆請求全是 propose）
  DQ-SLO  0 / 0 -> undefined     （分母結構上是空的）
  RL-SLO  n=11, max 979s         （其中 8 筆共用同一個 startsAt = 重放的告警內容）
                                  3 個不同告警：10s / 12s / 16s
  AE-SLO  0 / 1 -> 0.0%          （n=1，而那次失敗是 401）
  CE      cluster: labeled=7  ece=0.5643  overconfidence=+0.3929
          dev:     labeled=35 ece=0.1743  overconfidence=-0.0029
```

注意 `app/signals/dq.py` 的 docstring 把 data-quality 寫成「ARE flagship #2」，但書上的 flagship #2 是 Decision Quality。同一個縮寫，兩件不同的事。

### [4] SAR：L2 的門檻指標

```
  proposed=10, aborted=2, rollback_failed=1
  suggestions raised: 13   approved: 3   rejected: 0
  SAR = 23.1%
  actors: day33-live, day33-live-2, nathan-smoke-test
  10 expired without anyone opening them
```

三個核准者都是我在測試。分母裡有 10 筆是「沒有人打開過」，而 SAR 把它跟「人看過之後說不要」算成同一件事。

### [5] L3 的四個機制

```
  governance plane, runtime-evaluated    13 decisions, 全部 PROPOSE；ACTIONS_ENABLED 自 2026-06-22 為 true
  action contracts                       2 個註冊動作；dry_run abort=1, ok=2
  automatic reversal                     rollback fail=1
  calibrated confidence                  7 labeled runs vs 門檻 20
```

ARE 4.9 的 Trust Ceiling 要求這四個**同時**到位。前三個有真實證據，第四個沒有。
