# Day32：Trace Explorer — 看它怎麼想的，以及那一次花了多少錢

Day28 確認了推理過程一直有被 trace，Day30 補上從結論走回去的那個欄位。這一天講最後
一段：那條 trace 被讀出來之後長什麼樣，以及它順便回答的另一個問題——一次調查多少錢。

| 檔案 | 內容 |
| --- | --- |
| `trace_tree.py` | 打 `/traces/{id}`，把 plugin 會畫的那棵樹印在終端機上（含 token 與成本），預設隱藏 httpx 那些管線 span |

同時改的是原始碼：

| 檔案 | 改了什麼 |
| --- | --- |
| `app/traces.py` | 價格表加上 `PRICES_AS_OF`，rollup 多一個 `cost_basis`：成本數字要自己講出它是怎麼算的 |
| `tests/test_traces.py` | 兩條新測試：有 LLM 呼叫時 rollup 要帶 cost_basis、沒有時要是 None |

## 一次 chat 調查的全貌

```bash
uv run python ../../otel-aiops-agent/ironman-2026/day32/trace_tree.py <trace_id>
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

這棵樹把幾件事一次講完：

- **一次「調查」其實是五次模型呼叫**，只有兩次在推理（`agent`），其他三次是意圖閘門、
  結論抽取、後續問題建議。
- **推理那兩次佔了 77% 的錢**（$0.00105 + $0.000454，總共 $0.001964），因為輸入很長。
- Day30 加的 `AIOps_Findings_Extractor` 在這裡是一筆看得見的帳：$0.000303，
  約 15%。信心分數不是免費的。
- `tools` 那一層只花 39ms，而模型每次思考要一秒半。**慢的不是查詢，是想。**

## 成本數字要自己講出它是怎麼算的

價格表是手打的，而且沒有任何東西拿它跟帳單對過。這個形狀在這系列出現過太多次
（宣告沒有對帳就會慢慢變成謊話），所以與其假裝它是事實，不如讓它自己承認：

```python
PRICES_AS_OF = (
    "2026-08-06, hand-entered from the public price list, "
    "never reconciled against billing"
)
```

rollup 只要算得出成本，就一定附上 `cost_basis`。沒有 LLM 呼叫時兩個欄位都是 `None`。

## 為什麼要隱藏一部分 span

那條 trace 有 55 個 span，其中十幾個是 httpx 打 Prometheus/Loki/Tempo 的 client span。
它們是真的、偶爾也有用（Day25 那些 API 怪癖就是在這一層），但印在推理樹裡會把
「它怎麼想」埋掉。所以 `trace_tree.py` 預設濾掉，`--all` 才全印。

Grafana plugin 那一側的 Trace Explorer 做的是同一件事，只是換成可以展開的節點：
`llm` 節點展開是 prompt 與回覆，`tool` 節點展開是參數與結果。
