# Day31：答案怎麼變成面板與那顆按鈕

agent 的回答不是純文字。fenced block 會被 plugin 換成活的面板，`alert` 提案會變成一張
有按鈕的卡。這一天把這個契約的兩端（prompt 那邊的發送方、parser 那邊的接收方）攤開，
然後修掉兩個讓它斷掉的地方。

| 檔案 | 內容 |
| --- | --- |
| `render_probe.py` | 跑一次 chat（或吃一份現成答案），印出每個 fenced block 會被渲染成什麼、哪些會退成純文字 |

同時改的是原始碼：

| 檔案 | 改了什麼 |
| --- | --- |
| `app/alerts.py` | 送出規則之前先確認 folder 存在，不存在就建（冪等）；`parse_alert_blocks` 也接受 ```` ```json ```` 的合法 spec |
| `app/agent.py` | 系統 prompt 明列禁止項：不要輸出 Prometheus 風格的 ```` ```yaml ```` 規則 |
| `plugin/src/pages/ChatPage.tsx` | `splitQueryBlocks` 一起接受 ```` ```json ````（要能驗成 AlertSpec 才變成卡片） |
| `tests/test_alerts.py` | 三條新測試：folder 存在時不建、不存在時先建再送、`json` fence 的合法 spec 要收、不是 spec 的 JSON 要略過 |

## 契約長什麼樣

| 回答裡的 block | plugin 渲染成 |
| --- | --- |
| ```` ```promql ```` | 活的時序圖（Prometheus） |
| ```` ```logql 10 ```` | 活的 logs 面板，資訊行上的數字是行數上限 |
| ```` ```traceql 3 ```` | 活的 traces 表 |
| ```` ```alert ```` | 提案卡＋「Create alert」按鈕 |

```bash
uv run python ../../otel-aiops-agent/ironman-2026/day31/render_probe.py "近10筆 payment-service 的 log"
```

```
answer: 75 chars, 1 fenced block(s)

```logql 10  -> live logs panel
     panel row limit: 10
     {service_name="payment-service"}
```

## 兩個真的斷掉的地方

**一，folder 不存在，Grafana 直接拒絕。**

```console
$ curl -X POST localhost:8091/alerts/provision -d '{"title":"payment decline rate high", …}'
{"detail":"grafana rejected the rule: {\"message\":\"invalid alert rule: folder does not exist\"}"}
```

`folder_uid` 的預設值是 `aiops`，而使用者從頭到尾沒有選過 folder，是 AlertSpec 的預設值
選的。**使用者不可能弄錯的東西，就不該由使用者去修。** 改成送規則之前先 GET 一次 folder，
404 就建（409 也當成成功，因為那代表別人剛建好）。

```console
$ curl -X POST localhost:8091/alerts/provision -d '…'
{"ok":true,"uid":"bfudlf17fvw8wb","title":"payment decline rate high"}

$ curl -H "Authorization: Bearer $TOKEN" localhost:3001/api/v1/provisioning/alert-rules
bfudlf17fvw8wb  payment decline rate high  aiops  5m
```

**二，模型不照契約寫。** 「幫我對 payment-service 的拒絕率設一個告警」第一次拿到的是：

````
```yaml
alert: PaymentDeclinedRateHigh
expr: sum(rate(payment_charges_total{…,status="declined"}[5m])) / sum(rate(…)) > 0.05
for: 5m
```
````

內容完全正確，格式完全沒用——plugin 只認 ```` ```alert ````，所以那張卡不會出現，使用者
得自己把它複製到 Grafana 去。

在 prompt 裡明寫禁止項（「不要輸出 ```` ```yaml ```` 的 Prometheus 規則」）之後，JSON 對了，
但 fence 變成 ```` ```json ````，卡片還是不會出現。所以第二步是讓接收方寬容一點：
```` ```json ```` 只要驗得成 AlertSpec 就當成提案，驗不成就照樣當程式碼區塊顯示。

**要求發送方寫對、同時讓接收方認得出來，兩件事都要做。** 只靠 prompt 的契約是機率性的。

## 測試

```bash
uv run pytest tests/test_alerts.py -q      # 28 passed
```
