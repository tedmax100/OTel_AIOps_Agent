# Day28：五道門：信心分數要先能被查證，以及另外四道不問準不準的門

文章 Day28 用到的東西。第一道門（校準）跟另外四道（資料品質／憑證／runbook 成績單／
回歸紀錄）在這裡是同一組工具，因為它們讀的是同一份治理狀態。

| 檔案 | 內容 |
| --- | --- |
| `calibration_report.py` | 印可靠度圖（ECE／MCE／Brier 與分箱） |
| `promote_labels.py` | 把外部標註接進正式的校準表 |
| `backfill_grading_mode.py` / `fix_grading_mode.py` | 處理「兩種 correct 不是同一種對」那個欄位 |
| `probe_sufficiency.py` | 舊停止條件（問模型的信心）對新的四條確定性檢查，並排看它們哪裡不同意 |
| `gate_probe.py` / `slo_report.py` | 讀門的現值 |
| `probe_env_fit.py` | 量「這份知識屬不屬於這座環境」（孿生環境那個 1.0 對 0.0） |
| `probe_past_incidents.py` | 檢查案例召回那條路上的每一段 |
| `cluster-snapshot.db` | 文章裡那些數字當下的資料庫快照 |

同時改的是 agent 服務自己的原始碼：

| 檔案 | 改了什麼 |
| --- | --- |
| `app/store.py` | 新增 `env_fit_probes` 表 ＋ `env_fit_insert()` / `env_fit_latest()`，跟 `actuation_probes` 同一個形狀 |
| `app/signals/envfit.py` | `compute_env_fit()` 每次量完落盤（寫失敗只 warn）；`get_last_fit()` 在記憶體是空的時候回讀最新一筆，讀不到就是「沒量過」＝unproven |
| `tests/test_envfit.py` | 多三條：另一個行程讀得到、沒量過仍是 unproven、儲存讀不到不可以變成通過。autouse fixture 要一併把 `store_path` 指到 tmp |

### 為什麼要落盤

`python -m app.signals.envfit` 是**另一個行程**。照著跑會量到 1.0，而服務那個行程的
門仍然是 `env fit unproven`，因為它從來沒問過。滾一次部署，這道門的證據也一樣歸零。

```bash
cd aiops-agent/service
# 量一次（會落盤）
PROMETHEUS_URL=http://localhost:9090 LOKI_URL=http://localhost:3100 \
  TEMPO_URL=http://localhost:3200 python -m app.signals.envfit
# 服務那側現在讀得到同一筆了
```

回讀進來的舊資料不會自動變綠燈：`fit_verdict()` 的時效檢查照舊，太舊一樣算 stale。
落盤解決的是「哪個行程量的」，不是「量的時候夠不夠新」。

`actuation.py` 有同一個洞，一起補了：探測本來就有寫進 `actuation_probes`，
只有 `get_last_actuation()` 沒接上，重啟之後 readiness 一樣是「沒檢查過」。

| 檔案 | 改了什麼 |
| --- | --- |
| `app/signals/actuation.py` | `get_last_actuation(path=)` 記憶體空的時候回讀最近一筆；`actuation_verdict()` / `refresh_actuation()` 一起接 `path` |
| `tests/test_actuation.py` | 多五條（跨行程讀得到、**存進去的「被拒絕」回來還是被拒絕**、空 store 仍是 never checked、讀不到＝unproven、壞掉的 row 不算一筆）＋ autouse fixture 隔離 `store_path` |

`actuation_probes` 沒有 epoch 欄位，只有人看的 `ts`。判決只需要它算年齡，所以是
parse 回來而不是開 migration。**parse 不出來的 row 當成沒有 row**，不是當成一筆年齡
很怪的探測——後者會看起來又新又綠。

## 這一天是從哪幾天合併過來的

下面保留了合併之前每一份原始筆記，內容沒有改寫，所以裡面的日號指的是舊的編排。

- [`README.day29-calibration.md`](README.day29-calibration.md)（校準那道門）
- [`README.day30-other-gates.md`](README.day30-other-gates.md)（另外四道）
- [`README.day31.md`](README.day31.md)
- [`README.day32.md`](README.day32.md)
- [`README.day34.md`](README.day34.md)
- [`README.day35.md`](README.day35.md)
