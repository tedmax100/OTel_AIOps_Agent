# Day24：使用者到底拿到了什麼 — 入口、格式、帳單

前面二十九天的驗證，全部是從告警那頭進去的（`/webhook/alert` 或 `run_headless()`）。這一天換方向，從使用者那一側看回來，分三段：他從哪個門進來（入口）、agent 輸出的東西能不能被操作（格式）、以及那一次回答花了多少（帳單）。

| 檔案 | 內容 |
| --- | --- |
| `chat_probe.py` | 對一組問題印出意圖閘門的判定（in_scope / lookup vs investigate）與服務解析結果，零工具呼叫 |
| `chat_turn.py` | 真的跑一次 chat 回合，印出事件序列（status / tool_start / findings / suggestions）與最後存下來的那一列 |
| `render_probe.py` | 跑一次 chat（或吃一份現成答案），印出每個 fenced block 會被渲染成什麼、哪些會退成純文字 |
| `trace_tree.py` | 打 `/traces/{id}`，把 plugin 會畫的那棵樹印在終端機上（含 token 與成本），預設隱藏 httpx 那些管線 span |

同時改的是 agent 服務自己的原始碼：

| 檔案 | 改了什麼 |
| --- | --- |
| `app/agent.py` | 新增 `_investigation_instructions()`：investigate 模式的 chat 現在拿到跟告警同一份 RCA playbook；回合結束後抽 findings、發 `findings` 事件、存一列 investigation；並注入過去事故 |
| `app/agent.py` | 系統 prompt 明列禁止項：不要輸出 Prometheus 風格的 ```` ```yaml ```` 規則 |
| `app/investigations.py` | `InvestigationRecord` 多一個 `source`（`alert` / `chat`） |
| `app/store.py` | `inv_query_similar()` 的 `alertname` 改成可選 |
| `app/alerts.py` | 送出規則之前先確認 folder 存在，不存在就建（冪等）；`parse_alert_blocks` 也接受 ```` ```json ```` 的合法 spec |
| `plugin/src/pages/ChatPage.tsx` | `splitQueryBlocks` 一起接受 ```` ```json ````（要能驗成 AlertSpec 才變成卡片） |
| `app/traces.py` | 價格表加上 `PRICES_AS_OF`，rollup 多一個 `cost_basis`：成本數字要自己講出它是怎麼算的 |
| `tests/` | 十條新測試（instructions 帶著 playbook 與語言規則、source 欄位、alertname 可選、folder 冪等、`json` fence、cost_basis） |

---

## 一、入口：兩條路以前拿到的東西不一樣

| | 人打字（改之前） | 告警 webhook |
| --- | --- | --- |
| 意圖閘門 / 服務解析 / clarify | ✅ | — |
| 能力快照、Signal context、依賴健康 | ✅ | ✅ |
| RCA playbook（假設樹 ＋ 五步 ＋ 信心規則） | ❌ | ✅ |
| findings（結論／信心／suspected_version） | ❌ | ✅ |
| 過去事故 | ❌ | ✅ |
| investigation 紀錄 ＋ `trace_id` | ❌ | ✅ |
| 面板、alert 提案卡 | ✅ | — |

改完之後，中間那四列 chat 也有了。

```bash
uv run python ../../otel-aiops-agent/ironman-2026/day24/chat_probe.py
```

```
payment-service 的拒絕率為什麼變高了     in_scope=True  mode=investigate  services=['payment-service']
order-service 的 p95 latency          in_scope=True  mode=lookup       services=['order-service']
近10筆 payment 的錯誤 log              in_scope=True  mode=lookup       services=['payment-service']
幫我寫一個 python 快排                 in_scope=False mode=investigate  services=[]
哪個服務最近最不健康？                  in_scope=True  mode=investigate  services=[]
```

`mode` 決定走哪條路：`lookup` 一次 LLM 呼叫吐出查詢、讓面板自己渲染；`investigate` 走完整的圖，而且從這天起會帶著 playbook。

```bash
uv run python ../../otel-aiops-agent/ironman-2026/day24/chat_turn.py "payment-service 的拒絕率為什麼變高了？"
```

```
tool_start query_prometheus {'expr': 'sum by (git_version, reason) (rate(payment_charges_total…
findings   confidence=0.7 services=['payment-service'] version=v2.5.0
suggestions ['payment-service v2.5.0 的部署差異', 'payment-service 的錯誤日誌', …]

stored row: fp=ui-demo-1 source=chat confidence=0.7 trace_id=10d35edee3e4a743d43395ee6b55f5c8
```

`trace_id` 要有值，這一回合得從被 instrument 的服務進去（Day25）。

**踩到的細節：** playbook 第一版是接在使用者訊息後面的，結果中文問題拿到一半英文的回答，因為一大塊英文指令黏在問句後面，模型就跟著換語言。改成獨立的 system message，並在最後一行重申「用使用者的語言回答」（近因效應）。第二版還會把假設樹整棵印在回答裡，告警那條路沒人看無所謂，chat 這條路很吵，所以指令要明說「內部想，不要印」。

## 二、格式：契約的兩端

| 回答裡的 block | plugin 渲染成 |
| --- | --- |
| ```` ```promql ```` | 活的時序圖（Prometheus） |
| ```` ```logql 10 ```` | 活的 logs 面板，資訊行上的數字是行數上限 |
| ```` ```traceql 3 ```` | 活的 traces 表 |
| ```` ```alert ```` | 提案卡＋「Create alert」按鈕 |

```bash
uv run python ../../otel-aiops-agent/ironman-2026/day24/render_probe.py "近10筆 payment-service 的 log"
```

```
answer: 75 chars, 1 fenced block(s)

```logql 10  -> live logs panel
     panel row limit: 10
     {service_name="payment-service"}
```

**斷點一，folder 不存在，Grafana 直接拒絕。**

```console
$ curl -X POST localhost:8091/alerts/provision -d '{"title":"payment decline rate high", …}'
{"detail":"grafana rejected the rule: {\"message\":\"invalid alert rule: folder does not exist\"}"}
```

`folder_uid` 的預設值是 `aiops`，而使用者從頭到尾沒有選過 folder，是 AlertSpec 的預設值選的。**使用者不可能弄錯的東西，就不該由使用者去修。** 改成送規則之前先 GET 一次 folder，404 就建（409 也當成成功，因為那代表別人剛建好）。

**斷點二，模型不照契約寫。** 第一次拿到的是一份完全正確、完全沒用的 Prometheus YAML；在 prompt 裡明寫禁止項之後 JSON 對了，但 fence 變成 ```` ```json ````，卡片還是不會出現。所以第二步是讓接收方寬容一點：```` ```json ```` 只要驗得成 AlertSpec 就當成提案，驗不成照樣當程式碼區塊顯示。

**要求發送方寫對、同時讓接收方認得出來，兩件事都要做。** 只靠 prompt 的契約是機率性的。

## 三、帳單：一次 chat 調查的全貌

```bash
uv run python ../../otel-aiops-agent/ironman-2026/day24/trace_tree.py <trace_id>
```

```
trace 10d35edee3e4a743d43395ee6b55f5c8
  55 spans, 5 LLM call(s), 1 tool call(s), 18070 tokens, $0.001964
  models: ['gemini-2.5-flash-lite']
  cost basis: 2026-08-06, hand-entered from the public price list, never reconciled against billing

[http    ] POST /chat                                             7064ms
  [business] AIOps_Intent_Gate                                      1400ms
    [llm     ] ChatGoogleGenerativeAI.chat                            1397ms in=684 out=69 $9.6e-05
    [business] invoke_agent LangGraph                                 3094ms
      [business] LangGraph                                              3093ms
        [business] agent                                                  1491ms
          [llm     ] ChatGoogleGenerativeAI.chat                            1488ms in=10039 out=115 $0.00105
          [business] route_after_agent                                         1ms
        [business] tools                                                    39ms
          [tool    ] query_prometheus                                        37ms
        [business] agent                                                  1553ms
          [llm     ] ChatGoogleGenerativeAI.chat                            1549ms in=4050 out=123 $0.000454
        [business] rubric_trace                                             4ms
    [business] AIOps_Findings_Extractor                               1445ms
      [llm     ] ChatGoogleGenerativeAI.chat                            1442ms in=2408 out=156 $0.000303
    [business] AIOps_FollowUp_Suggester                                904ms
      [llm     ] ChatGoogleGenerativeAI.chat                             902ms in=366 out=60 $6.1e-05
```

- **一次「調查」其實是五次模型呼叫**，只有兩次在推理（`agent`），其他三次是意圖閘門、結論抽取、後續問題建議。
- **推理那兩次佔了 77% 的錢**（$0.00105 + $0.000454，總共 $0.001964），因為輸入很長。
- 上面那段加的 `AIOps_Findings_Extractor` 在這裡是一筆看得見的帳：$0.000303，約 15%。信心分數不是免費的。
- `tools` 那一層只花 39ms，而模型每次思考要一秒半。**慢的不是查詢，是想。**

價格表是手打的，而且沒有任何東西拿它跟帳單對過。這個形狀在這系列出現過太多次（宣告沒有對帳就會慢慢變成謊話），所以與其假裝它是事實，不如讓它自己承認：

```python
PRICES_AS_OF = (
    "2026-08-06, hand-entered from the public price list, "
    "never reconciled against billing"
)
```

rollup 只要算得出成本，就一定附上 `cost_basis`。沒有 LLM 呼叫時兩個欄位都是 `None`。

那條 trace 有 55 個 span，其中十幾個是 httpx 打 Prometheus/Loki/Tempo 的 client span。它們是真的、偶爾也有用（Day23 那些 API 怪癖就是在這一層），但印在推理樹裡會把「它怎麼想」埋掉。所以 `trace_tree.py` 預設濾掉，`--all` 才全印。

## 測試

```bash
uv run pytest tests/test_alerts.py tests/test_traces.py -q
```
