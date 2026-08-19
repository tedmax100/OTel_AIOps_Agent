# Day39：人介入之後，這套系統記得什麼

Day38 讓 agent 記得自己查過的事故。**人做的事一件都沒留下來**：

| 人做了什麼 | 系統記了什麼 | 下一次執行知道嗎 |
| --- | --- | --- |
| 在 plugin 上標「這個診斷是錯的」 | `calibration` 一列 `correct=0` | ❌ |
| 駁回一個提案 | `action_requests.status='rejected'` | ❌ |
| （執行器自己）跑完一份 runbook | `runbook_feedback` 一列 | ❌ |

第三列不是人做的，但它跟前兩列同一個病：**資料一直在寫，沒有人讀**。`runbook_feedback`
從執行器寫好那天就在收，讀它的只有一支報表 endpoint，所以一份連續三次驗證失敗的 runbook，
下一次照樣以權威的語氣被貼進 prompt。

這一天把這三條接回去，外加一件 Day38 沒有、而這三條接上之後才變成問題的事：**遺忘**。

## 一、人的否證

`case_memory.confirm_from_label()` 原本的註解寫著「a wrong run teaches nothing at this
layer: knowing the answer was wrong is not knowing the answer」。這句話對 `root_cause`
那個欄位是對的，對整個案例是錯的。「有人看過這件事，說 payment 那個版本不是元凶」是這套系統
產出的**最貴的一筆證據**，丟掉它等於允許下一次執行毫無阻力地走回同一個錯誤答案。

所以它進去了，但進的是死路那半，不是知識那半——一個被推翻的假設，跟一條問不出東西的查詢，
本來就是同一種東西。

```
[1] a human says "wrong", and the case keeps it
    root_cause after a wrong verdict: None
    ruled out [hypothesis] payment v2.5.0 new_validator rejects odd cents
              evidence: latency was flat on v2.5.0 — 0.041s vs 0.059s
              disproved_by: human
```

誰有資格否證，用的是跟根因那半一模一樣的**允許清單**形狀：

```
[2] who may disprove — and what an unfamiliar source gets
    ui                     culprit        -> recorded  (a person, on a run that blamed someone)
    eval-harness           culprit        -> recorded  (the grader)
    remediation-verified   culprit        -> ignored   (the run grading its own fix)
    some-new-bot           culprit        -> ignored   (a source nobody has heard of)
    ui                     inconclusive   -> ignored   (a person, on a run that blamed nobody)
```

最後一列是這節唯一需要想一下的：一個判錯的 `inconclusive` 意思是「它該怪人的時候沒有怪」，
桌上根本沒有假設可以推翻，而**那時候人寫的更正說明就是答案**——把它記在「已排除」底下，
比什麼都不記還糟。

更正說明存成 evidence，不升格成 `cases.root_cause`。那是一個自由文字框，可能是答案、
可能是提示、也可能是「見 thread」，而 `root_cause` 是下一次執行會當成定論來讀的欄位。

## 二、駁回的理由

`reject(request_id, actor)` 以前只有這兩個參數。人為什麼不准這次 rollout，這個資訊在系統裡
不存在，所以下一次提一模一樣的提案是必然的——那不是模型固執，是紀錄只允許這樣。

```
[3] a declined action, and the proposal that is not made again
    status=rejected  decision_note='we roll forward here, never back'
    next run's gate: ESCALATE — a person declined this on 2026-08-19: we roll forward here, never back
    same action, another target  bound: False
    another action, same target  bound: False
```

判 ESCALATE 而不是 PROPOSE：ESCALATE 的語意本來就是「交回給人，連動作都不要預填」。
在 PROPOSE 只會讓人再打一次同樣的拒絕，而第二次拒絕比第一次少了資訊，它講的是我們的固執。

後兩列是邊界。綁的是 `(action, target)` 這一對，不是 action：「不要重啟 payment」不是在講
重啟別的東西。

**一個沒有預期到的接縫。** 提案是在調查**進行中**產生的，而 `investigations` 那一列是在
調查**結束時**才寫。所以靠 `run_id` 反查事故的話，一次跑到一半掛掉的執行、或是人按得夠快的
情況，理由就無處可歸。改成在提案產生的當下就把 `case_key` 釘在 `action_requests` 上，
`run_id` 反查降級成舊資料的 fallback。這個是寫測試之前先用 TestClient 打真的 API 才發現的，
單元測試全綠。

## 三、runbook 的成績單

同一個判準只有一份（`store._rb_verdict`），報表跟關卡共用。一個頁面說這份 runbook 沒事、
治理平面卻當它停用，比兩邊都錯還糟。

```
[5] a runbook's own record, read twice
    never executed         insufficient_data  proven_good=False gate=propose  0 recorded execution(s) — too few to rate
    one failure, one run   insufficient_data  proven_good=False gate=propose  1 recorded execution(s) — too few to rate
    three clean            healthy            proven_good=True  gate=propose  3/3 verified clean
    failing verification   needs_review       proven_good=False gate=propose  verify_failed 75% (3/4) — the symptom survived the fix
    its undo did not work  suspended          proven_good=False gate=escalate rollback_failed x1 — this runbook's undo did not work
```

`rollback_failed` 不看比率是刻意的：那裡重要的不是幾成，是逃生門被試過而且沒有用。一個可逆的
動作之所以被允許，前提就是它撤得掉。反過來，一次失敗除以一次執行等於 100%，那是謠言不是量測，
這條規則本來只寫在 day36 的報表裡，現在寫進程式，順帶修正了舊的健康報表（以前 1/2 會印 50%）。

**要誠實講一件事：`gate` 那一欄從頭到尾沒有出現 AUTO，而那不是這道門的功勞。**
shipped registry 裡每一個動作都是 `requires_approval=True`，而且乾淨的 store 上 human-label
下限本來就沒過。所以今天真正改變結果的只有 `suspended` 那一列，`needs_review` 那條降級路徑
在目前的設定下是量不到的。

## 四、遺忘

前三條接上之後才長出來的債。以前只有 agent 自己的死路會累積，現在人的否決也會，而
「不要在營業時間 rollout」這種話永遠不會過期。

```
[6] nothing here is true forever
    recalled now:                       1
    recalled past the age cutoff:       0
    a person retracts it:               {'cases': 1, 'dead_ends': 1}
    recalled after the retraction:      0
    occurrences kept:                   1
```

- 死路 30 天、案例 90 天。舊的 `expires_ts` 只蓋到寫入當下就知道會短命的那種（超出保留期的
  trace），**人寫的那些一個 TTL 都沒有**。
- 召回區塊印出日期，因為那條年齡線是一刀切，不是「線以內都還成立」的保證。
- `POST /cases/{key}/forget` 讓人當場撤回。年齡線只處理慢慢飄移；環境是禮拜二重建的、
  政策是禮拜二改的，得有人能在禮拜二講這句話。撤回清掉根因與死路，`occurrences` 留著——
  事故發生過這件事不在爭議範圍。

下一次執行實際看到的東西：

```
[4] what the next run is handed
    ## Past cases for this service (reference — current evidence wins)

    ### Already ruled out here — do not spend budget re-checking
    - [action] k8s.rollout_undo on demo/payment-service (not during business hours) — ruled out by a person [2026-08-19]
    - [hypothesis] payment v2.5.0 new_validator rejects odd cents (latency was flat on that version) — ruled out by a person [2026-08-19]
```

`_past_incident_context()` 這裡也修了一個安靜的 bug：死路原本是用**召回到的案例**的 key 去撈的，
也就是說要先有一個確認過根因的案例，死路才召回得到。而人的否證正好發生在「還沒有人答對」
的時候，所以這條路一天都不會通。

## 五、第二個事故劇本

前面四節做完，還是量不出效果——Day38 量到 3 seeds 之下雜訊底線 ±67pp。而擋在量測前面的
不只是 seeds，還有環境：這座 demo 只有一個響亮的事故，`reason=new_validator_odd_cents`
就長在 Prometheus 的 label 上，於是 payment-service 的任何告警都會被歸到它頭上。
Day38 那題對照題六次全錯，原因在這裡，不在召回。

所以加第二個劇本，形狀刻意跟第一個相反：

| 劇本 | 壞的東西 | 告警在哪 | 原因在哪 |
| --- | --- | --- | --- |
| `bad-validator` | payment 拒絕奇數分 | payment-service | payment-service |
| `session-cache` | user-service 的 auth check 掉進慢的 session store | **order-service** | **user-service** |

第一個劇本的原因、症狀、答案全在同一個服務裡，答案還寫在 label 上，所以 agent 可以**答對，
但從來沒有往告警指名的服務外面看過一眼**。第二個沒有捷徑：order-service 的訂單在 auth 那步
失敗，它自己的指標裡沒有任何東西講得出為什麼。

治理先行：新的詞彙先進 Weaver registry 才准被程式碼發出來。`app.fail_reason` 多一個
`session_store_timeout`、新增 `app.cache.name`、`user_auth_checks_total` 從「不帶任何
attribute」變成帶 outcome/reason（以前「auth 在失敗」這句話光看指標講不出來）、新增
`app.user.authcheck.duration`，並把一直掛著 `reserved — not yet emitted` 的
`event.cache.miss` 真的接上。`weaver registry check` 綠燈。

旗標改成**每個請求讀一次**，從 ConfigMap 掛進去，所以不用重啟。第一個劇本要重啟 payment，
那會讓 pod rollout 跟故障落在同一分鐘，延遲圖表就有兩種解釋。

### 實測（活的 k3d 叢集，2026-08-19，完整輸出在 `verify-20260819.txt`）

```
[1] the symptom, on the service that alerted
  orders_total by outcome, 15m
      status=created                                               207.842
      reason=auth status=cancelled                                  22.498
      reason=payment status=cancelled                                2.143
  order-service p95
      (no labels)                                                    0.483

[3] the cause, one hop upstream
  user_auth_checks_total by outcome, 15m
      status=authorized                                            230.345
      reason=session_store_timeout status=error                     18.041
  user-service authcheck p95
      (no labels)                                                    0.483

[4] the same story in logs
  user-service events
      event=cache.miss                                              78.000
      event=user.logged_in                                          70.000
      event=user.auth_failed                                         7.000
```

auth check 的 p95 從大約 1ms 變成 **0.483s**，order-service 的 p95 跟著變成 **0.483s**，
大約 9% 的訂單掛在 auth 那步。25 筆訂單從 0.39 秒變成 7.6 秒，關掉之後回到 0.44 秒。

### 順手撞到一個會騙人的數字

第一次跑 `verify_incident.py` 的時候，第 3 段是這樣的：

```
  user_auth_checks_total by outcome, 15m
      status=authorized                                             77.138
      reason=session_store_timeout status=error                      0.000
```

而同一個視窗的 Loki 有 8 筆 `user.auth_failed`，raw counter 也確實是 8。

原因是我剛剛重新 build 過 image，pod 重啟讓 counter 歸零，那個視窗裡的樣本長這樣：

```
13, 13, 13, 13, 8, 8, 16
```

`increase()` 處理得了 reset，但當它落在只看得到 `8, 8` 那段平的區間時，答案就是 0。
**這對值班的人為什麼危險**：`0.000` 跟「沒有這回事」長得一模一樣，而它旁邊那一列
`status=authorized` 有一個很漂亮的數字，看起來整個查詢是好的。一隻 agent 走到這一步
拿到 0，最合理的下一步就是回頭去怪 order-service 自己——而那正是這個劇本要考的東西。

這跟這個 repo 記過的另外兩個坑是同一類：histogram 的預設 ms bucket 讓
`histogram_quantile` 回傳一個看起來很像真的常數、Loki 的 `count_over_time` 配
`query_range` 讓總量膨脹一百多倍。**共通點都是「查詢成功、數字錯誤、沒有任何東西會抱怨」。**
所以 fixture 的那條路徑不能只寫 `increase(...[15m])`，跨過部署的視窗要嘛拉長、要嘛
配著 raw counter 或日誌對照一次。

### 洩題檢查

`verify_incident.py` 最後一段檢查的是另一半：**答案有沒有被免費送給 agent**。
registry 現在帶著這個事故的 `reason` 值，而 vocabulary 區塊是從 registry 編出來的。
`render_vocabulary` 只吐 label 名字不吐值域，這一段是去斷言它，而不是相信它的 docstring。

順著這條也修掉一個既有的洩題：`schema_catalog.md` 原本把 `user.auth_failed` 的 `reason`
值列出來（`not_found` / `transient`），跟 `payment.declined` 那一列的處理方式不一致
（那一列寫的是 `read the values off a result`）。另外 day22 的 `leakcheck.py` 的
`ANSWER_TOKENS` 只認得第一個劇本的答案詞，一個只認識第一個事故的掃描器，會在把第二個事故的
答案交出去的同時回報「乾淨」。

## 路上撞到的兩個 bug

**`flags.py` 在容器裡是 SyntaxError。** `except json.JSONDecodeError, OSError:` 是
PEP 758 的寫法，Python 3.14 收、3.12 不收，而 image 是 `python3.12-bookworm-slim`。
第一次 rollout 直接 CrashLoopBackOff。

**加上括號之後，`ruff format` 又把它拿掉了。** 根目錄的 ruff 設定 `target-version = "py314"`，
格式化器認為那個括號多餘。**這個 bug 是 lint 自己種回去的**，而且每一道檢查都是綠的。
修法是給 demo-services 自己的 ruff 設定：`extend = "../pyproject.toml"` 加
`target-version = "py312"`，跟它真正跑的 runtime 對齊。

## 怎麼跑

```bash
# 不需要叢集、不需要 LLM
python3 ironman-2026/day39/probe_intervention_memory.py

# 需要活的叢集 + 事故正在跑
cd demo-services && ./scripts/incident.sh start session-cache
kubectl -n demo port-forward svc/prometheus 9090:9090 &
kubectl -n demo port-forward svc/loki 3100:3100 &
python3 ironman-2026/day39/verify_incident.py
cd demo-services && ./scripts/incident.sh stop session-cache
```

產品端的改動在主 repo 的 `aiops-agent/service/`（`case_memory.py`／`governance.py`／
`store.py`／`action_requests.py`／`agent.py`）與 plugin 的 `InvestigationsPage.tsx`；
第二個劇本在 `demo-services/`。測試 495 → **528 passed**。

## 沒做的

- **這一天的東西全部沒有量測。** 四條回饋通道接上了、第二個劇本驗過了，但沒有任何一次
  真實 RCA 跑過它們。雜訊底線 ±67pp 還在，要有結論得先加 seeds。
- **新劇本沒有烤進 stack image。** `demo-services-o11y-stack` 只烤了第一個事故，所以
  `order-service-auth-degradation` 這個 fixture 只能對活叢集跑，進不了 `--stack` 的可重現
  路徑，也進不了 baseline 比對。這是接下來最該做的一件事。
- **plugin 沒在真的 Grafana 裡點過。** 駁回理由的輸入框驗到 tsc、lint、API 契約為止。
- **`needs_review` 那條降級路徑量不到**（上面第三節）。
- **eval 的流程檢查沒回饋給 agent。** 它連續三次犯同一個錯，報表寫下來，agent 不知道。
- **匹配還是硬的。** `symptom` 恆為空字串。放寬的兩種直覺做法都是反方向的：放寬根因等於
  擴大污染，放寬否證等於把一句在這裡對的話搬到那裡變成錯的。正解需要一個分類步驟，
  而它的正確性在目前的雜訊底線下驗不了。
- **取代舊根因沒做。** 同一個事故被確認成新根因時，舊的那句直接消失，不會變成死路。
- **`increase()` 那個 0 沒有被擋下來。** 上面那個坑我寫進 README 了，但 fixture 的
  process 檢查裡沒有任何一條會在 agent 讀到 0 的時候要求它去對照日誌。
- 探測腳本沒有斷言，也沒進 CI（`verify_incident.py` 的洩題檢查有離開碼，那半有）。
