# Day41：把第二個事故跑完一圈，然後看它到底記住了什麼

Day36 把迴路關起來過一次：一個事故、一個動作，而且**沒有人檢查事後寫下了什麼**。從那之後蓋上去的
每一層——案例記憶、人的否證、runbook 成績單、`cases.resolution`——都站在那一次之上。

第二個事故（session-cache，告警在 order-service、原因在 user-service）到今天為止**根本沒有入口**：
沒有 runbook，也沒有一個修得好它的動作。它的原因是一個旗標不是一個版本，所以 `k8s.rollout_undo`
在這裡不只是錯，是**不適用**。

這一天做兩件事：把入口補上，然後真的按下去。

## 一、能真的修好它的動作

`k8s.configmap_flag_set`。demo 的服務每個請求讀一次掛進去的旗標檔，所以在這座叢集上「處置」真正的
形狀就是翻旗標：不重啟、不換 image。

三個刻意的決定：

- **read-modify-write 單一 key。** strategic merge 會把 `flags.json` 整條字串換掉。真正危險的不是
  patch 失敗，是 patch 成功、順手把別人一小時前設的另一個旗標還原了。
- **文件裡沒有的旗標直接拒絕。** 一個因為我們寫進去才存在的旗標，不會有任何程式在讀它。
- **dry-run 的 footprint 是「誰掛了這張 map」。** ConfigMap patch 不直接碰到任何一個 pod，所以它的
  影響範圍只能算、不能假設。共用時寫進 notes——「這張旗標不只是你的」是核准前必須看到的一句。

RBAC 用 `resourceNames` 把寫入權限釘在 `payment-flags` / `user-flags` 兩張上。整個 namespace 放行
`patch configmaps` 會連 collector pipeline 跟兩份 datasource 設定一起送出去。

**旗標的方向差點寫反。** `user_session_cache_disabled` 是 **true 代表故障中**（快取關掉、每次 auth
check 都掉進慢的 session store），`false` 才是健康。第一版 runbook 的處置寫 `value: true`，核准下去
等於再按一次故障開關，而 rollback 會把系統「還原」成健康。現在方向釘在測試裡，理由寫在旁邊。

rollback 依然是**回到壞掉的狀態**，這是對的：undo 的意思是把系統放回值班的人剛剛在看的那個狀態，
不是憑空生出第三種沒人見過的組態。

## 二、runbook 替 agent 跨過那一跳

`session-cache-timeout.yaml`。diagnostics 自己走到上游：先確認取消集中在 auth 而不是 payment，
然後直接查 `user_auth_checks_total{status="error"}`。

留在 order-service 上的每一項檢查都會是健康的——這就是這個事故的形狀，也是 agent 至今跨不過去的
那一步（它會回答「order-service 自己的程式碼」然後停下來）。所以這一跳由 runbook 帶，不留給推理。

沒有提供 `k8s.scale`：多幾個 replica 一起等同一個慢的 session store 不是修好，而一個 verify 過不了
的動作，失敗的時候會往案例記憶寫一件假的事。

verify 讀**上游**的訊號而不是告警自己的指標：訂單停了告警就會安靜，而「呼叫器不叫了」跟
「auth check 恢復了」是兩個不同的主張。

## 三、第一次 drill：全綠，而且是假的

```
[16:26:15]   request b15df9e51c06424b action=k8s.configmap_flag_set autonomy=propose status=proposed
[16:26:15] approving b15df9e51c06424b (the human in human-in-the-loop)
[16:29:06] terminal state: succeeded  outcome=executed and verified

  phase          verdict      detail
  proposed       ok           {"action": "k8s.configmap_flag_set", "autonomy": "propose", ...}
  approved       ok           {"trace_id": "1e5cb1ec978ac76f8a1aad8ef33fac24"}
  precondition   ok           {"checked": 4}
  dry_run        ok           {"blast_radius": "target demo/user-flags, ..."}
  execute        success      {"result": "{'action': 'configmap_flag_set', ...}"}
  verify         settle       {"settle_seconds": 165}
  verify         pass         {"detail": "value 0 ≤ max_value 0.01"}
```

告警到提案 15 秒，八個 phase 全綠，終端狀態 `succeeded`。

而這座叢集的 Prometheus 當時**一個 demo 指標都沒有**：30 個 metric 全是 agent 自己的 `gen_ai_*`
遙測，沒有 `orders_total`、沒有 `user_auth_checks_total`。

因為我的腳本沒有流量。Day36 特地寫了一個 Traffic thread，我這支漏掉了：沒有請求就沒有訂單、沒有
auth check、counter 從來沒被建立過。事故注入了，但**沒有任何東西在壞**。

### 那面綠燈揭出來的 bug

```python
elif rt == "vector":
    if not result:
        val = 0.0        # 「沒有 series = 這個指標是 0」
```

空的 instant vector 被讀成 0，0 ≤ 0.01，門開了。

**這對值班的人為什麼危險**：指標改名、scrape target 掛掉、label 被丟掉——每一種都會讓這道門在
它是「錯誤動作」與「案例記憶學到這個動作有效」之間唯一那道防線的時候，全部放行。而且它不會抱怨，
audit trail 上是漂亮的一行 `verify pass`。

這跟這個 repo 記過的另外兩個坑同一類（histogram 預設 bucket 回傳假常數、Loki `count_over_time`
配 `query_range` 膨脹一百多倍）：**查詢成功、數字錯誤、沒有任何東西會抱怨。**

修法是 fail-closed：沒有 series 就代表這個查詢看不到症狀，那它就不能說症狀停了。runbook 需要時可以
用 `empty_ok: true` 明講「沒有資料就是訊號」。

順手修的第二個：executions 帳本上的 `target` 是 `demo/`——尾巴是空的。scope key 只認 `deployment`，
ConfigMap 動作填不進去，於是整個 namespace 的每個旗標共用**一個斷路器作用域跟一把冪等鑰匙**：其中
一個跳閘會把其他全部封住，兩次不同的翻轉會被當成互為重試。現在是
`demo/user-flags#user_session_cache_disabled`。

## 四、第二次 drill：這次症狀真的在

腳本補上流量，而且**注入之後、發告警之前**先確認症狀存在：

```
[16:34:59] symptom is observable: orders_total and user_auth_checks_total both have series
[16:35:00] alert posted (startsAt=2026-08-20T16:34:59Z, drill=True)
[16:35:20]   request eae0be82321c4f12 action=k8s.configmap_flag_set autonomy=propose status=proposed
[16:38:10] terminal state: succeeded  outcome=executed and verified
```

這次的 `verify pass` 是真的：門已經改成空結果不放行，所以它讀到的 `value 0` 來自一條真的存在、而且
在處置後歸零的 series。旗標翻回去、auth 錯誤率掉到 0、`succeeded`。

**迴路合起來了**：告警 → runbook → 提案 → 人核准 → 前置條件重驗 → 影響範圍 → 執行 → settle →
驗證。第二個事故第一次走完。

## 五、然後看它記住了什麼——這才是重點

```
  case key on the request: ffa6ab9638c72564
  occurrences: 2   status: open
  root_cause : (none — nobody has confirmed one)
  resolution : (empty — nothing recorded what fixed it)
  ruled out  : [query] PromQL referencing orders_total, reason
  ruled out  : [query] PromQL referencing reason, user_auth_checks_total
  ruled out  : [query] PromQL referencing reason        (x5)
  ruled out  : [query] PromQL referencing status
```

`resolution` 是空的，這是**設計如此**：drill 上 `remember_resolution()` 直接 return，排練一個自己
注入的故障不是關於真實事故的證據。

但上面那幾列不是設計如此。下一次執行拿到的召回區塊長這樣：

```
### Already ruled out here — do not spend budget re-checking
- [query] PromQL referencing reason (no such metric in this Prometheus)
- [query] PromQL referencing status (no such metric in this Prometheus)
- [query] PromQL referencing user_authcheck_duration_seconds_bucket (no such metric ...)
- [query] PromQL referencing reason, user_auth_checks_total (no such metric ...)
```

`reason` 跟 `status` **是 label 不是指標**，這個 Prometheus 裡當然沒有叫 `reason` 的 series。而
`user_auth_checks_total` 是這個事故的答案所在。

也就是說，這套系統剛剛學會了「不要去查寫著答案的那個指標」，理由是一個它自己算錯的判斷。

原因在指標名稱的抽取：

```python
_PROM_METRIC_RE.findall('sum by (reason) (rate(orders_total{status="cancelled"}[5m])))')
# → ['orders_total', 'reason']
```

`by (...)` 裡面是 **label 名字**，`{...}` 裡面也是。它們被當成指標名，於是「這裡沒有這個指標」永遠
成立，而這個判斷被歸類為**環境屬性**（相對於「這個時間窗沒東西」）——所以它會被寫進案例、跨執行留著。
分類的邏輯本來是對的：一個名字不存在確實是環境的事實。錯的是餵給它的東西。

修法是抽取前先把 grouping 子句跟 label matcher 這兩塊拿掉。`by` / `without` / `on` / `ignoring` /
`group_left` / `group_right` 都算。

**這一條比 verify 那條更值得記住**：verify 的假綠燈只影響一次執行，而寫進案例記憶的錯誤 dead end
會**跨執行累積**，而且它長得跟真的一模一樣——同樣的表格、同樣的日期、同樣權威的語氣。一個會學習的
系統，第一次真正跑起來的時候，學到的第一件事是錯的。

## 六、按下去之後：排練吃掉了真實那一次，而它藏在兩道門後面

`--no-drill` 跑了。第一次的結果是 `aborted`：

```
terminal state: aborted
outcome=idempotent: target already acted on for this incident (eae0be82321c4f12)
```

`eae0be82321c4f12` 是十分鐘前那次**演習**。冪等鑰匙是 `動作|目標|事故`，裡面沒有「這是不是排練」
這一格，所以排練花掉了這個事故唯一被允許的那次動作。而排練刻意不寫 `resolution`，被擋掉的那次也就
永遠拿不到寫它的機會。

修法跟 `target` 那次同一個形狀：後綴只加在演習那側（`...|drill`），正式請求的鑰匙一字不變，否則
帳本裡每一把舊鑰匙都對不上自己——那是把 bug 換成另一個 bug。

**修完之後再跑一次，發現同一個病其實有兩層，而擋住的是更前面那道。** 真實告警發出去，RCA 根本
沒被叫起來，連一列 investigation 都沒有。原因在 `webhook._in_cooldown()`：

```python
def fingerprint(labels: dict) -> str:      # alertname | service | git_version
alert_cooldown_seconds: int = 600
```

fingerprint 不吃 `drill`，cooldown 十分鐘寬。演習 15:26:40 蓋了章，真實告警 270 秒後到，被當成
重複的告警直接丟掉。冪等那道門修得對，但它在後面，永遠等不到人。

cooldown 的 key 因此也加上同樣的後綴。**`fp` 本身刻意不動**：它同時是 LangGraph 的 thread id 跟
案例檢索的 key，切開它會讓排練的發現對它所排練的那個事故隱形，那正是 Day38 記過的「太窄」。

驗證用鑰匙自己說話：

```
15:42:16  2eae7c48  ...|2b0a13c99c8f670a          aborted   superseded_by 92690e75（真實）
15:40:17  0ac80e85  ...|2b0a13c99c8f670a|drill    aborted   superseded_by 7ebc84ac（演習）
15:26:48  7ebc84ac  ...|2b0a13c99c8f670a|drill    succeeded
15:15:52  92690e75  ...|2b0a13c99c8f670a          succeeded  ← resolution 的第一筆
```

15:42 那次真實告警**通過了 cooldown**（15:37 才跑過演習），提案有被建出來，這正是修之前沒發生的事。
它最後仍然 aborted，但這次 `superseded_by` 指的是一次真實執行，不是一次排練。同樣是 aborted，
理由從錯的變成對的。

`cases.resolution` 的第一筆來自 15:15 那次：

```
resolution : {"action": "k8s.configmap_flag_set", "runbook_id": "session-cache-timeout",
              "request_id": "92690e7562a54af8", "verified": true}
retracted  : 9 dead end(s) kept as history, not recalled
```

**這一條的教訓不是「少寫了一格」**，是排練跟真的在這套系統裡共用了幾條路徑，而我只數到一條就以為
數完了。要問的問題是「一次排練會在哪些地方被誤認成真的」，不是「哪一個 key 少了欄位」。

## 怎麼跑

```bash
kubectl apply -f demo-services/k8s/15-aiops-agent.yaml   # 新的 RBAC（ConfigMap patch）
aiops-agent/scripts/deploy.sh                            # 服務端改動要在叢集裡才算數
# ACTIONS_ENABLED=true 要自己翻，腳本不會幫你

python3 ironman-2026/day41/close_the_loop.py preflight
python3 ironman-2026/day41/close_the_loop.py run          # drill（預設）
python3 ironman-2026/day41/close_the_loop.py cleanup
```

preflight 會擋這次特別會踩的那個雷：寫入 SA 到今天為止不能 patch ConfigMap，而它會通過現有每一項
readiness 檢查，然後在唯一重要的那一次呼叫上 403。

輸出：`drill-20260821.txt`（第一輪，假綠燈）、`drill-20260821b.txt`（第二輪，真的）、
`nodrill-20260821.txt`（第一次真實執行，被排練擋下來）、`nodrill-20260822.txt`（修完之後，
`resolution` 的第一筆）、`drill-20260822.txt` 與 `nodrill-20260822b/c.txt`（兩道門的驗證）。

## 沒做的

- **`fp` 兼四份差事那件事沒動。** 這次只在 cooldown 這一格加了第五種區分（排練 vs 真的），
  Day38 那張「三種粒度，一個欄位」的表本身還在。
- **沒有在乾淨窗內跑出一次「演習後、真實成功」的完整綠燈。** 要那張截圖得等一小時讓真實那側的
  冪等窗過期。目前是靠 `idem_key` 的形狀跟 `superseded_by` 指到誰來證明的。
- **`k8s.scale` 仍然可以被提案在這個事故上。** runbook 沒提供它，不代表 governance 會擋它。
- **第二輪的 RCA 答對了沒有，這裡沒有量。** 這一天量的是處置迴路，不是診斷正確率——而診斷正確率
  正好是 day40 停下來的地方。
- **verify 的 `empty_ok` 沒有任何 runbook 在用**，所以那條分支只有單元測試走過。
