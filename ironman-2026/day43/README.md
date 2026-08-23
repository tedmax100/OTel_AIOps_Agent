# Day43：那個 0.2 不是模型的錯，是我們自己標壞的

Day42 把 AUTO 的六個條件全部讀出來之後，最刺眼的是這一條：

```
  FAIL  accuracy in that band                want >= 0.7       got 0.2
```

信心 0.8 以上的 run，五題對一題。當時我寫的結論是「信心跟正確率反向」，
然後很自然地想到下一步是**去改模型**——降信心、換 prompt、加事故劇本讓它多見世面。

今天本來要做的不是這個。今天要做的是把「人該做的事」擺出入口：
提案沒人核准、run 沒人標註、事故沒人寫根因，這三件事同時卡住三個目標，
而它們的共同點是**沒有地方可以按**。做完入口之後，我順手打開那 0.2 背後的列，
然後那個結論就不成立了。

## 一、先做入口：Todo 與 Cases

後端補了兩塊：

- `GET /cases` / `GET /cases/{key}`：案例記憶在這之前是黑箱，
  只能 `kubectl exec` 進去開 SQLite。刻意**不是**把 `case_query_similar`
  的條件放寬——那條查詢回答的是「下一次該告訴模型什麼」，所以它藏起來的
  正是人最需要看的：沒人標註的、過期的、被標成誤報的。兩條查詢，兩個問題。
- `GET /todo`：一次回四段——待標註的 run、待決的提案（含**過期沒人理**的計數）、
  沒有根因的事故，以及 AUTO 還差多少。最後那段直接呼叫治理自己的那幾支函式，
  不重寫一份判斷，所以它報什麼就是下一個高信心提案會被告知什麼。

Grafana plugin 加了兩頁對應。Autonomy 那塊我堅持畫成「現值 vs 門檻」的表，
而不是一顆紅燈：

```
  Labeled runs                      8      >= 20
  Labeled by a human or grader      8      >= 20
  Runs in the decision band         6      >= 3      ← 唯一綠的
  Accuracy in that band             0.2    >= 0.7
  Mean overconfidence               0.3929 <= 0.1
  Worst bin gap                     0.8167 <= 0.25
```

一個沒人看得到的標準，就是一個沒人會去追的標準。

做完之後我發現一個洞：Todo 上寫著「沒有根因的事故：1」，
但畫面上**沒有任何地方可以填根因**。後端只有讀跟 forget，根因只能從
investigation 的標註路徑間接寫進去。所以又補了 `POST /cases/{key}/root-cause`。
這支端點的 `source` 寫死成 `human`，不從 request body 拿——
讓呼叫端自己宣告來源，正是自我背書混進來的路徑。

## 二、然後打開那六列

入口做完，我用新的 probe 把決策區的列印出來（`probe_label_pool.py`，唯讀）：

```
  run_id=2e5b4954f3a93971  rows=1
    2026-06-22T15:47:45Z  conf=0.95  correct  payment-service ... v2.5.0 validator
  run_id=1539e7b9b01d65bb  rows=4
    2026-06-22T15:59:04Z  conf=0.95  WRONG    payment-service v2.5.0 ... new validation rule
      note: 根因是 DB 連線問題，不是 validator regression
    2026-06-22T15:59:28Z  conf=0.85  WRONG    ... database connection pool exhaustion
    2026-06-22T16:00:18Z  conf=0.8   WRONG    ... database connection pool exhaustion
    2026-06-22T16:03:05Z  conf=0.8   WRONG    ... database connection issues
  run_id=2b0a13c99c8f670a-...  rows=1
    2026-08-22T15:42:16Z  conf=0.9   correct  order-service ... session store
```

六列，三個 run id。中間那個 id 一個人扛了四列——那是 Day38 以前的痕跡，
那時候 `run_id` 就是 fingerprint，同一個告警的每一次再調查共用一個 id。

而那四列是一條連續的鏈，時間戳貼在一起：

1. agent 說「v2.5.0 的 new_validator 誤擋付款」，信心 0.95 → **被標錯**，
   更正註記寫「根因是 DB 連線問題」
2. 之後三次，agent 照著這句更正改口說「DB 連線池耗盡 → gateway timeout」
   → 三次都**被標錯**

問題是：**同一個結論 `new_validator` 在 15:47 那筆 0.95 是被標對的。**
同一個事故被人標成兩種互斥的答案，而依 schema catalog（v2.4.1 → v2.5.0 / new_validator），
第一種才是真的。

所以那 0.2 的組成是：一次不正確的人工更正，加上 agent 三次順從，再被逐次記為錯誤。
決策區六列裡有四列來自這一次失誤——一個錯誤被計了四次。
而八月只有一筆標註，信心 0.9，**答對**。

「信心跟正確率反向」這個結論的證據基礎，比我以為的薄非常多。

## 三、對值班的人為何危險

這件事最難受的地方不是數字錯了，是**錯的方向**。

如果曲線把 agent 說得比實際差，AUTO 打不開，最壞情況是大家繼續手動——不好，但安全。
真正的問題在對稱的另一邊：**同一套機制也可以把它說得比實際好，而且更容易發生。**

我在補標註之前先看了一眼待標註的池子，裡面有八筆信心 0.95 的 run，
內容幾乎一模一樣，全是 8/16 那天的排練（`v2.5.1-drill-*`），
而且全都答對了同一個植入的故障。這八筆一次標完，決策區的準確率會漂亮地跳上去，
六個條件裡有幾條會直接翻綠。

那不是六份證據，那是**一份證據重播六次**。

`executions.drill` 早就為了同樣的理由存在（day41：排練跟事故不能混在同一個成功率裡），
但校準曲線這一層還在把兩者平均。也就是說：這套系統一邊很嚴謹地拒絕讓
fixture 成績替真實寫入背書，一邊卻允許八次排練替自主權背書。

值班的人看到的會是：某天早上 AUTO 亮了，理由是「校準已證實」，
而那個證實來自一個被重播八次的演習。

## 四、兩個修法

**修一：校準也要分排練與真實。**
`calibration` 加 `drill` 欄位（additive migration），`webhook` 從 alert labels
認出排練並寫進去——那是最後一個還知道「這是演習」的地方，之後任何人看那筆 run 都分不出來。
`production_records()` 濾掉排練，治理的曲線與**人工標註樓地板都改用它**：
曲線跟樓地板必須算在同一批列上，否則樓地板不是樓地板。

歷史列預設 0，等於所有舊排練都偽裝成真實事故，所以寫了一支 backfill
（`scripts/backfill_calibration_drill.py`，預設 dry-run）。它從當時寫下來的東西回推：
investigation 存的 alert labels，加上 `suspected_version` 裡的 `-drill`。
但 Day38 以前一個 id 蓋住整條鏈，所以那批只有在「同 id 的每一筆 investigation
都說是排練」時才標記，否則列為 `ambiguous` 放著不動——
在這裡用猜的，等於自己製造門要讀的證據。結果：12 筆標成排練，6 筆 ambiguous 不動。

**修二：撤回那四筆標註。**
它們判的是一個後來被推翻的前提。`retract_calibration_labels.py` 只把 `correct`
設回 NULL，**保留列、信心值、summary，以及那句錯誤的更正註記**——
這個誤判本身仍然要讀得到。那四次 run 回到「沒人判過」的狀態，
也就是實際上為真的狀態。

順帶修掉一個一直沒人發現的東西：`cal_load()` 的欄位清單漏了
`error_dimension` 跟 `correction_note`，而 record 模型有宣告這兩欄。
所以任何走 `load_records()` 的讀者，看到的都是「一筆錯誤判決，沒有任何理由」。
今天要稽核「這個判決本身是不是錯的」，缺的正是這一欄。

## 五、撤回之後，數字會變醜

這是重點，所以講清楚：撤回四筆之後，labeled 從 8 掉到 4，
決策區從 6 列掉到 2 列——**低於門檻 3**。治理的那句話會從
「準確率不足」變成「決策區沒有足夠證據」。

看起來像退步。實際上是從「量到一個錯的數字」變成「誠實說沒有足夠證據」。
一個 n=6 而且四列來自同一次失誤的準確率，本來就不該被當成對這隻 agent 的評價。

要把數字做回來，路徑很清楚：**八月有 15 筆非排練的高信心 run 還沒標**。
Todo 頁現在每一列都有 Correct / Wrong，標完就地消失、上面的表當場跳動，
不用在兩個頁面之間跳。Wrong 的 Modal 裡我把今天的教訓寫進說明文字：

> 這段更正會被注入再調查，一個本身是錯的更正會把 agent 帶往錯的方向，
> 之後每一次順從它的 run 都會被記為錯誤。

那句話不是文案，那是 6 月那條鏈的墓誌銘。

## 今天的成果

| | |
|---|---|
| 後端 | `/cases`、`/cases/{key}`、`/cases/{key}/root-cause`、`/todo` |
| 治理 | `autonomy_status()`：五道門的現值與距離，重用同一批判斷函式 |
| 校準 | `calibration.drill` + `production_records()`，排練不再替自主權背書 |
| Plugin | Todo 與 Cases 兩頁；Todo 可直接標註，Cases 可寫根因 |
| 維運腳本 | `backfill_calibration_drill.py`、`retract_calibration_labels.py`（皆 dry-run 預設） |
| 修掉 | `cal_load()` 漏讀 `error_dimension` / `correction_note` |

```bash
python3 ironman-2026/day43/probe_label_pool.py          # 對著叢集
python3 ironman-2026/day43/probe_label_pool.py --local  # 對著本機 checkout
```

完整輸出在 `pool-20260823.txt`。

明天：把那 15 筆標完，第一次看到一個**只由這隻 agent、在真實事故上**產生的校準曲線。
