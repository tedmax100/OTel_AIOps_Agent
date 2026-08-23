# Day20：agent 開始想之前，手上有什麼

`run_headless()` 組裝完一輪之後才呼叫圖。這裡放兩支腳本：一支把那一刻的 state
印出來（不花 token），一支真的跑一次 RCA 並保留逐字稿。

| 檔案 | 內容 |
| --- | --- |
| `probe_turn.py` | 把 `_build_agent()` 換成只記錄的樁，照正常路徑跑 `run_headless()`，印出交給圖的每一則訊息。零 token |
| `run_rca.py` | 跑真的 RCA（要 `GOOGLE_API_KEY`），把圖產出的每一則訊息側錄下來印成逐字稿 |

同時改的是 agent 服務自己的原始碼：

| 檔案 | 改了什麼 |
| --- | --- |
| `signals/health.py` | 區塊開頭的 `read just now` 改成印出實際使用的時鐘（`current_now()`，在告警調查中會被釘到 `startsAt`） |
| `tests/test_health.py` | 一條新斷言：在 `now_override` 裡產生的區塊要寫出被釘住的那個時間，且不得出現 `just now` |

## 跑 probe

前提是 Prometheus / Loki / Tempo 都 port-forward 好了。從 `aiops-agent/service/` 底下跑：

```bash
uv run python ../../otel-aiops-agent/ironman-2026/day20/probe_turn.py
```

```
runbook payment-bad-deploy matched alertname 'PaymentDeclineRateHigh' only after
normalization (trigger says 'payment-decline-rate-high') — align the alert rule
or the runbook trigger
budget: 6 tool calls
messages handed to the graph: 6

0. [system   ]    517 chars  ## Live capability snapshot
1. [system   ]   2212 chars  ## Signal context (topology v1.0.0)
2. [system   ]    785 chars  ## Runbook: payment-bad-deploy — payment-service decline-rate spike after…
3. [system   ]   1305 chars  ## Runbook diagnostics auto-run: payment-bad-deploy
4. [system   ]    572 chars  ## Dependency health (live) — payment-service
5. [user     ]   3444 chars  An alert just fired. Investigate the root cause and conclude with the sin…

total: 8835 chars before the first token of reasoning
```

加 `--full` 印出每一則的完整內容：

```bash
uv run python ../../otel-aiops-agent/ironman-2026/day20/probe_turn.py --full
```

## 釘住的時鐘

`probe_turn.py` 裡的 `ALERT["startsAt"]` 是 `2026-08-05T15:30:00Z`，也就是 payment 事故
真的在跑的那個時間點。s4 的依賴健康會在 `now_override` 裡讀，所以印出來的是事故當下的
數字，不是現在的：

```
Each service's SLI, read at 2026-08-05T15:30:00Z (the incident clock for this
investigation, not necessarily wall-clock now), to attribute root cause to the
right node:
- this service payment-service: error 61.5% — UNHEALTHY (breaches objective declined_rate < 1%)
```

改之前那一行寫的是 `read just now`，而它讀的是一天前。

要在自己的環境重現，把 `startsAt` 換成你那座 stack 有事故資料的時間。

那個時間點沒有資料的話**不會**退成 `unavailable`：contracts.yaml 裡的 error SLI 寫成
`(sum(rate(...)) or vector(0)) / clamp_min(sum(rate(...)) or vector(0), 1)`，
分子分母都有 fallback，所以查無資料會算出 `0` 並印成 `error 0.0% — healthy`。
（本機在 Prometheus 保留期外的時間點跑，看到的就是這個。）

## 為什麼只有六則

注入有六個（runbook 那一個自己產兩則），少掉的是過去事故：

```bash
uv run python -c "
from app.agent import _past_incident_context
print('past:', repr(_past_incident_context('payment-service','PaymentDeclineRateHigh')))"
```

```
past: ''
```

過去事故庫從來沒有被寫入過，而注入是 fail-open：拿不到就不注入。

runbook 反而是有比對到的，只是靠正規化：trigger 寫 `payment-decline-rate-high`，
告警叫 `PaymentDeclineRateHigh`。`match_runbook()` 要連 `service_name`、`severity`
一起餵才會中，只丟 `alertname` 進去會拿到 `None`（是餵少了，不是沒有 runbook）。

## 測試

```bash
uv run pytest tests/test_health.py -q
```

## 跑真的 RCA

要 `GOOGLE_API_KEY`（Gemini），從 `aiops-agent/service/` 底下跑：

```bash
uv run python ../../otel-aiops-agent/ironman-2026/day20/run_rca.py
```

一次大約十三秒、四次工具呼叫（上限六次）。輸出包含它在每次呼叫前說了什麼，
所以看得到 Step 0 的假設樹有沒有真的列出來。

## 兩個要注意的量測限制

**Tempo 只留一小時。** `tempo-config` 裡 `compaction.block_retention: 1h`，
所以任何超過一小時的告警，第 4 步「抓一條 trace 佐證」都不可能成功。
agent 會照樣花掉預算去試，因為沒有任何地方宣告過這個保留期。

**系統 prompt 洩題。** `build_system_prompt()` 的 schema catalog 為了說明
`payment_use_new_validator` 這個 flag，把它造成的事故一起寫進去了：

```bash
uv run python -c "
from app.agent import build_system_prompt
p = build_system_prompt()
print('v2.4.1' in p, 'new_validator' in p)"
```

（寫這篇的當下這行印 `True True`。洩題後來被拿掉了，所以現在跑同一行會拿到
`False False` — 要重現當時的狀態得 checkout 當時的 commit。）

裡面包含版本轉換（`v2.4.1` → `v2.5.0`）、失效機制（odd-cents 被拒）、
以及一段格式範例直接就是這次事故的結論。所以在這座 demo 上跑出來的 RCA 成績
**不能拿來評估 agent 的根因分析能力**，它是開書考。
