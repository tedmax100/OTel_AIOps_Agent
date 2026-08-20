# Day40：把時鐘當成變數，然後承認尺量不到東西

Day39 收在一個**論證**，不是結果。

同一個 container 裡跑三個 pass，五題全部 spread 0%——temperature 0 該有的樣子，模型被排除了。
而真正被觀察到的擺盪（`order-service-auth-degradation` 對照組，前一個實驗 3/3、下一個實驗 0/3，
中間程式碼一個字都沒改）發生在**不同 invocation 之間**，每次 invocation 都用 `scenario_time = now`
重開一顆 container。generator 有 `random.seed(42)`，所以兩次 boot 的資料結構完全一樣，
差別只有整條時間軸平移——而那些絕對時間戳在告警裡、在釘住的時鐘裡、在 agent 算的每一個視窗裡。

論證聽起來很順，所以更該去跑一次。這一天只做一件事：**固定 image、fixture、store、程式碼，
只動 scenario time**，看跑出多少 spread。

```bash
python3 ironman-2026/day40/probe_clock_sensitivity.py --only order-service-auth-degradation
```

四個時鐘刻意不是相鄰的四分鐘：不同小時、不同分鐘、其中一個跨過 UTC 午夜。每個時鐘一次完整
boot 加一個 pass。完整輸出在 `clock-20260820.txt`。

## 一、第一次跑，四次 boot 全部失敗——而失敗的是尺

```console
=== scenario time 2026-08-19T04:11:00Z ===
booting demo-services-o11y-stack:latest…
  stack did not produce queryable incident data in time
```

四次都一樣。但 container 是活的，日誌寫著 `=== Environment Ready ===`，generator 也印了
`charges=11520 orders=8640 traces=6476 logs=41041`，`/api/v1/label/__name__/values` 也真的
列得出 `user_auth_checks_total`。資料在裡面，只是問不到。

`stack.wait_ready()` 用的是 instant query，而 instant query 只看得到 Prometheus **5 分鐘
lookback** 以內的樣本。烤好的資料結束在 scenario time，所以拿牆上時鐘去問，除非 scenario time
剛好就是現在，否則回來的永遠是 `"result":[]`。

**這個檢查只有在「scenario time ≈ now」的時候才會過——而那正是這個實驗要變動的變數。**

以前不會踩到，是因為以前每一次 `--stack` 都沒有帶 `--scenario-time`，預設就是 now。一個只在
變數不變時才成立的前置檢查，會在你第一次真的去動那個變數的當天，回報一句長得像環境壞掉的話。

修法是把 scenario time 一路帶進 readiness 查詢。同一顆 container，修完前後：

```
now  : False
clock: True
```

## 二、四個時鐘，判決 spread 0pp

```
  order-service-auth-degradation      0/1   0/1   0/1   0/1   mean 0.0%  spread 0.0pp
```

四次全錯。這句話**不能**讀成「時鐘沒有影響」——四個 0 之間量不出任何差別，這題四次都貼在地板上。

底下的分項確實在動：

| 時鐘 | 指對服務 | confidence | 掛掉的 process check |
| --- | --- | --- | --- |
| 04:11 | ❌ | 0.80 | 查詢只發了一次就收工 |
| 12:37 | ❌ | 0.70 | （沒觸發） |
| 21:53 | ✅ | 0.70 | `query_loki_logs` 空手而回，沒 discover 就重試 |
| 00:29 | ✅ | 0.80 | `query_prometheus` 空手而回，沒 discover 就重試 |

所以時鐘會改變 agent 走的路、改變它最後指的服務、改變它在哪一步撞牆——**但改不動最終判決，
因為判決在這題上沒有離開過地板**。

Day39 那個 3/3→0/3 沒有被單獨的時鐘複製出來。誠實的說法是：這次實驗**沒有證實**那個論證，
也沒有推翻它——它只證明了在一個四次都答錯的 fixture 上，這個實驗設計問不出問題。

## 三、整個 suite 跑一次，那個擺盪自己又出現了

```
aiops-agent eval — 5 fixture(s), 5 run(s), overall correct 40%

  payment-decline-service              100% (1/1)   conf 0.80
  user-service-no-incident             100% (1/1)   conf 0.60
  order-service-discover-before-query    0% (0/1)   conf 0.65
  payment-latency-false-alarm            0% (0/1)   conf 0.60
  order-service-auth-degradation         0% (0/1)   conf 0.70

  regression vs baseline:
    ▼ order-service-discover-before-query: 100% → 0%
```

總分跟 Day39 一樣是 40%，但**組成整個換了一輪**，而程式碼只動了上面那個 readiness 查詢：

- `user-service-no-incident` 從 0%（三次 `OutputParserException`）變成 100%
- `order-service-discover-before-query` 從 100% 掉到 0%，而且掛在同一種毛病上：
  `query_tempo_traces` 回空手，然後**沒有 discover 就直接重試 `query_prometheus`**

第二列就是 Day39 追的那個擺盪，換一題再演一次：一條沒有被碰過的程式碼路徑，兩次 invocation
之間 100% → 0%。這次連時鐘都不是刻意動的（照舊 `now`），所以它跟第二節那四個 0 合在一起看，
指向的其實是同一句話：**這幾題的成績目前主要由「空結果之後 agent 怎麼辦」決定，而不是由抽樣決定。**

三次不同的 fixture、三次不同的資料源（Prometheus / Loki / Tempo），同一個失敗形狀：
查詢回空、不去 discover 標籤、換個參數再猜一次。那是 Day26 就寫下來的老問題。

## 這條線到此為止

Day38 開始追雜訊，追出三層：seed 沒有到達模型（它只設 thread id 跟 record id，模型是
temperature 0）、pass 不是抽樣單位（一個 container 內 spread 0%）、時鐘是變數但在地板上量不到。

**再往下修抽樣設計，是在打磨一把量不到東西的尺。** 擋在量測前面的已經不是抽樣，是 agent 在
第二個劇本上答不對——而它答不對的原因，第三節那三行寫得很清楚。

## 沒做的

- **時鐘敏感度沒有結論。** 要有結論，得挑一題目前不在地板上的（`payment-decline-service`
  是 100%，但它是開書考），或是等 `order-service-auth-degradation` 先能答對。
- **`--repeat` 跟 `-n` 的成本效益已經量過，但預設值沒改。**
- **readiness 這個 bug 沒有回歸測試。** 修的是 `stack.py`，而它需要一顆真的 container 才驗得到。
- **probe 沒有斷言、沒進 CI**，跟 day39 的探測腳本一樣。
