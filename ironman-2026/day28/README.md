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

## 這一天是從哪幾天合併過來的

下面保留了合併之前每一份原始筆記，內容沒有改寫，所以裡面的日號指的是舊的編排。

- [`README.day29-calibration.md`](README.day29-calibration.md)（校準那道門）
- [`README.day30-other-gates.md`](README.day30-other-gates.md)（另外四道）
- [`README.day31.md`](README.day31.md)
- [`README.day32.md`](README.day32.md)
- [`README.day34.md`](README.day34.md)
- [`README.day35.md`](README.day35.md)
