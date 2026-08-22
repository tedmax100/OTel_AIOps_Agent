# Day42：AUTO 為什麼一次都沒開，跟那個答案的三次改寫

到今天為止，這套系統送出過 24 筆處置提案，`autonomy` 欄位**清一色是 `propose`**，
`AUTO` 一次都沒有觸發。治理給的理由一直是同一句：

```
calibration unproven (7 labeled run(s) < 20); autonomy withheld
```

聽起來像文書工作：多標幾筆就好了。這一天只做一件事——**把那句話後面的東西全部讀出來**，
然後那個答案被改寫了三次。

```bash
python3 ironman-2026/day42/probe_autonomy_gates.py          # 對著叢集
python3 ironman-2026/day42/probe_autonomy_gates.py --local  # 對著本機 checkout
```

唯讀：開兩個 SQLite 跟一份 JSONL 算數，不寫、不提案、不執行。完整輸出在 `gates-20260823.txt`。

## 一、第一次改寫：標註數量只是六個條件裡的第一個

```
production curve  (labels from people, on live incidents)
  FAIL  labeled runs                       want >= 20        got 7
  FAIL  human/grader labels                want >= 20        got 7
  FAIL  mean overconfidence                want <= 0.1       got 0.3929
  PASS  labeled runs at conf >= 0.8        want >= 3         got 5
  FAIL  accuracy in that band              want >= 0.7       got 0.2
  FAIL  worst bin off by                   want <= 0.25      got 0.8167 ([0.8,0.9))
```

治理只回報第一個失敗，所以那句「7 < 20」把後面五條全部藏起來了。

第五條是重點：**agent 說信心 0.8 以上的時候，五題對一題。** 那七筆攤開來看，
信心 0.2 的時候二題對一題（50%），信心 ≥0.8 的時候五題對一題（20%）——在這份樣本上，
信心跟正確率是反向的。

補標註不會打開 AUTO，只會把後面那三個失敗量得更精確。

## 二、第二次改寫：有 94 筆標註在另一個資料庫裡

`eval/harness.py` 的 `DEFAULT_STORE` 是 `app/eval/eval.db`，跟正式的 `/data/aiops.db` 分開。
所以正式那側 7 筆，eval 那側 94 筆，而 `eval-harness` **不在** `_SELF_LABEL_SOURCES` 裡，
按規則它算數的外部證據，只是治理從來沒看到它。

合併的話前兩道門立刻開。但那等於讓「烤好的固定資料上跑出來的成績」替「對活的叢集寫入」背書，
而 day40 剛量過那個背書值多少：同一題換個 scenario time，100% → 0%，程式碼一個字沒改。

所以是**分開計、都要過**。`regression_verdict()` 是第五道門，形狀跟 DQ / actuation /
runbook health 一樣（`{proven_good, note}`），`decide()` 現在五道全過才給 AUTO。
同一把尺，兩份證據：正式標註問「這隻 agent 在真實事故上準不準」，fixture 問
「它在已知答案的題目上有沒有退化」。

## 三、第三次改寫：那份 fixture 證據在美化數字

新的那道門是五道裡唯一沒有有效期限的。DQ 跟 actuation 都有 `max_age` 而且會 stale，
它沒有，於是它在讀七週的 label 池。

```
    window  labeled   overconf  band n  band acc  worst bin
        7d       32     0.4156      12    0.8333  0.7 ([0.7,0.8))
       14d       32     0.4156      12    0.8333  0.7 ([0.7,0.8))
       30d       41     0.2683      16     0.875  0.5571 ([0.7,0.8))
       60d       47     0.1936      18    0.8889  0.5 ([0.7,0.8))
       all       47     0.1936      18    0.8889  0.5 ([0.7,0.8))
```

**窗開越大，數字越好看。** 六月底那批 label 的 agent 跟現在這隻不是同一份程式碼，
它們卻在投票說它校準得很好。

`governance_fixture_max_age_days = 14`：那是現有紀錄上還撐得過 20 筆樓層的最短窗（32 筆），
同時把六月那批甩掉。時間只是代理指標，真正該用的 key 是「產生這些 label 的程式碼版本」，
而 calibration 那張表沒有這個欄位。

順帶一提，帶內正確率其實一路都是過的（0.83–0.89），擋住的是 overconfidence 跟最差 bin 偏離。

## 四、然後發現那份證據根本不在版控裡

```
aiops-agent/service/.gitignore:8:app/eval/eval.db
```

而 `Dockerfile` 是 `COPY app /app/app`。所以那個檔案被烤進 image，**只因為它剛好在我的硬碟上**。
換一台機器、CI、或任何人 clone 之後 build，image 裡沒有這個檔，這道門回
`no fixture record to read; autonomy withheld`。

fail-closed 所以不危險，但**這道門的判決是「誰 build 的 image」的函數**。

證據因此搬進 `app/eval/fixture_record.jsonl`（94 列、17KB、進版控），`eval.db` 退回成
harness 自己的工作檔。只留曲線算得到的欄位，散文拿掉，`run_id` 留著因為它帶 fixture 名字：

```json
{"confidence": 0.8, "correct": true, "grading_mode": "culprit",
 "run_id": "eval-payment-decline-service-seed1-1782834034",
 "source": "eval-harness", "ts": "2026-06-30T15:41:28Z"}
```

兩個後果是目的不是副作用：**「誰能寫解鎖 AUTO 的證據」變成「誰能 merge」**，而不是
「誰能寫叢集裡的一個檔案」；而 **image 自帶自己的成績單**，這個版本的 agent 配這個版本賺到的
label，正是這道門在問的事。

`python -m app.eval run` 跑完會 append 新 label 並印一行「去看 diff」，不會替你 commit。
`--no-record` 給那種不該替任何事背書的實驗用。

驗證方式是把工作樹複製一份、拿掉 `eval.db`、在那份上跑 gate，數字一樣。

## 沒做的

- **AUTO 還是沒開，而且短期不會開。** 這是「分開計、都要過」的直接後果，選的時候就知道。
- **兩側共用同一組門檻。** 目前是「同一把尺」，要給 fixture 側不同標準得拆成兩組。
- **`regression_verdict()` 每次提案都重讀一次紀錄**，沒有快取，跟 DQ / actuation 那種有 refresh
  機制的不一樣。檔案小所以先不管。
- **`app/eval/clock-probe.db` 還被追蹤著**，day40 探測留下的，現在沒有任何程式讀它。
- **正式那側的 7 筆標註沒有增加。** 要開 AUTO 仍然得有人在 plugin 上標，而且準確度要比現在好很多。
