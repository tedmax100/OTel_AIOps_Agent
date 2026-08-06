# Day30：人在 Grafana 打字的那一側

前面二十九天的驗證，全部是從告警那頭進去的（`/webhook/alert` 或 `run_headless()`）。
這一天處理另一個入口：一個人在 Grafana 的輸入框打一句話。

| 檔案 | 內容 |
| --- | --- |
| `chat_probe.py` | 對一組問題印出意圖閘門的判定（in_scope / lookup vs investigate）與服務解析結果，零工具呼叫 |
| `chat_turn.py` | 真的跑一次 chat 回合，印出事件序列（status / tool_start / findings / suggestions）與最後存下來的那一列 |

同時改的是 agent 服務自己的原始碼：

| 檔案 | 改了什麼 |
| --- | --- |
| `app/agent.py` | 新增 `_investigation_instructions()`：investigate 模式的 chat 現在拿到跟告警同一份 RCA playbook；回合結束後抽 findings、發 `findings` 事件、存一列 investigation |
| `app/agent.py` | investigate 模式的 chat 會注入過去事故（同一個服務、不限 alertname） |
| `app/investigations.py` | `InvestigationRecord` 多一個 `source`（`alert` / `chat`） |
| `app/store.py` | `inv_query_similar()` 的 `alertname` 改成可選 |
| `tests/` | 五條新測試（instructions 帶著 playbook 與語言規則、source 欄位、alertname 可選的查詢） |

## 兩個入口，以前拿到的東西不一樣

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

## 意圖閘門與解析

```bash
uv run python ../../otel-aiops-agent/ironman-2026/day30/chat_probe.py
```

```
payment-service 的拒絕率為什麼變高了     in_scope=True  mode=investigate  services=['payment-service']
order-service 的 p95 latency          in_scope=True  mode=lookup       services=['order-service']
近10筆 payment 的錯誤 log              in_scope=True  mode=lookup       services=['payment-service']
幫我寫一個 python 快排                 in_scope=False mode=investigate  services=[]
哪個服務最近最不健康？                  in_scope=True  mode=investigate  services=[]
```

`mode` 決定走哪條路：`lookup` 一次 LLM 呼叫吐出查詢、讓面板自己渲染；`investigate` 走完整的
圖，而且從這天起會帶著 playbook。

## 一個 investigate 回合

```bash
uv run python ../../otel-aiops-agent/ironman-2026/day30/chat_turn.py "payment-service 的拒絕率為什麼變高了？"
```

```
tool_start query_prometheus {'expr': 'sum by (git_version, reason) (rate(payment_charges_total…
findings   confidence=0.7 services=['payment-service'] version=v2.5.0
           The payment-service has a high decline rate due to the new_validator reason, with the
           latest deployment v2.5.0 being the primary contributor.
suggestions ['payment-service v2.5.0 的部署差異', 'payment-service 的錯誤日誌', …]

stored row: fp=ui-demo-1 source=chat confidence=0.7 trace_id=10d35edee3e4a743d43395ee6b55f5c8
```

`trace_id` 要有值，這一回合得從被 instrument 的服務進去（Day28）。

## 一個踩到的細節

playbook 第一版是接在使用者訊息後面的，結果中文問題拿到一半英文的回答——一大塊英文指令
黏在問句後面，模型就跟著換語言。改成獨立的 system message，並在最後一行重申「用使用者的
語言回答」（近因效應），問題才消失。

第二版還會把假設樹整棵印在回答裡。告警那條路沒人看，chat 這條路很吵，所以指令要明說
「內部想，不要印」。
