# Day24：先把量尺修好，再讓 fixture 去讀逐字稿

Day23 跑出一場好看的 RCA，然後發現答案寫在 prompt 裡。這一天做兩件事：把洩題拿掉，
並且讓 eval 不只看結論、也看它是怎麼查到的。

| 檔案 | 內容 |
| --- | --- |
| `leakcheck.py` | 把交給模型的每一個區塊（system prompt ＋ 所有注入）掃一次答案關鍵字。零 token，有洩題就 exit 1 |
| `ab_run.py` | 同一個告警跑兩次：A 用洩題版 prompt、B 用清乾淨的，印出兩邊的工具呼叫與結論 |
| `leaky_catalog.md` / `leaky_contracts.yaml` | 清理前那兩份 prompt 素材的原樣快照，`ab_run.py` 的 A 邊就吃這兩份 |
| `scripts/stage_incident.sh` | 把事故種進資料裡：先跑一段 v2.4.1 健康窗，再翻 flag ＋ 換版本，然後打 odd-cents 讓它拒絕 |

同時改的是 agent 服務自己的原始碼：

| 檔案 | 改了什麼 |
| --- | --- |
| `app/schema_catalog.md` | 拿掉版本轉換、flag 名稱、`new_validator_odd_cents`，以及那段就是本次結論的回答格式範例；feature flag 那節只留機制 |
| `demo-services/services/payment/signal.yaml` | 契約的 `role` 跟 caveat 不再寫出 flag 名字（改完要重跑 `python -m app.signals.compile`） |
| `app/agent.py` | `run_headless()` 多回傳 `messages`，evaluation 才讀得到逐字稿 |
| `app/eval/process.py` | 四條從逐字稿讀出來的檢查：`queried` / `grounded` / `discover_before_retry` / `evidence_or_hedge` |
| `app/eval/harness.py` | fixture 多一個 `process:` 區塊；過程沒過就不算對 |
| `app/eval/fixtures.yaml` | 三個 fixture 都補上 `process:`，並新增 `order-service-discover-before-query` |
| `tests/test_eval_process.py` | 每條檢查一個該綠的、一個該紅的逐字稿 |

## 掃洩題

從 `aiops-agent/service/` 底下跑，不需要 API key：

```bash
uv run python ../../otel-aiops-agent/ironman-2026/day24/leakcheck.py --show
```

清理前：

```
scanned 5 block(s), 29854 chars

[LEAK] system prompt (schema catalog)
         culprit version: 'v2.5.0'
           | payment-service 在 14:05 後 decline 率從 0% 跳到 18%，全集中在 v2.5.0、
         previous version: 'v2.4.1'
           | | payment-service | charges. Has the `payment_use_new_validator` flag | … | v2.4.1 |
         the flag that ships it: 'payment_use_new_validator'
         failure mechanism: 'odd_cents'
         decline reason value: 'new_validator_odd_cents'
[ok  ] injected #0: ## Live capability snapshot
[LEAK] injected #1: ## Signal context (topology v1.0.0)
         decline reason value: 'new_validator'
           | - caveat: … to find which deploy/reason drives it (e.g. the new_validator flag shipping in a release).
[ok  ] injected #2: ## Dependency health (live) — payment-service
[ok  ] injected #3: An alert just fired. Investigate the root cause and conclude

6 leak(s) across 2 block(s)
```

清理後：

```
[ok  ] system prompt (schema catalog)
[ok  ] injected #0: ## Live capability snapshot
[ok  ] injected #1: ## Signal context (topology v1.0.0)
[ok  ] injected #2: ## Dependency health (live) — payment-service
[ok  ] injected #3: An alert just fired. Investigate the root cause and conclude

no answer tokens in anything handed to the model.
```

## 種一次事故

前提：k3d demo stack 起來，而且 `webapp:8002`、`payment-service:8001`、
Prometheus/Loki/Tempo 都 port-forward 好了。

```bash
LOAD=/path/to/o11y-bench/demo-services/scripts/load.sh \
  ./scripts/stage_incident.sh 8 14      # 8 分鐘健康窗 + 14 分鐘事故
```

整段刻意壓在一小時內，因為 Tempo 的 `block_retention` 是 1h——窗開得更寬，
第 4 步「抓一條 trace 佐證」不是變慢，是變成不可能。

## A/B

要 `GOOGLE_API_KEY`，兩次真的 RCA：

```bash
uv run python ../../otel-aiops-agent/ironman-2026/day24/ab_run.py            # 用現在的時鐘
uv run python ../../otel-aiops-agent/ironman-2026/day24/ab_run.py 2026-08-06T13:21:10Z
```

## 跑 eval

```bash
uv run python -m app.eval run -n 2
```

```
aiops-agent eval — 3 fixture(s), 6 run(s), overall correct 50%

  fixture                        correct   service   version   conf  err
  ----------------------------------------------------------------------
  payment-decline-service        100% (2/2)    100%     100%   0.75    0
  user-service-no-incident        50% (1/2)    100%    n/a   0.60    0
  order-service-discover-before-query     0% (0/2)     50%    n/a   0.65    0

  failed process checks (the answer may still read fine):
    x user-service-no-incident seed1 — discover_before_retry: query_tempo_traces errored and was re-sent unchanged
    x order-service-discover-before-query seed0 — discover_before_retry: query_prometheus came back empty, retried query_prometheus without discovering
    x order-service-discover-before-query seed1 — discover_before_retry: query_prometheus came back empty, retried query_loki_logs without discovering
```

`baseline.json` 的數字跟你那座 stack 的資料有關，第一次跑完用 `--save-baseline`
寫自己的基準，之後的回歸才是跟自己比。

## 測試

```bash
uv run pytest tests/test_eval_process.py tests/test_eval_harness.py -q
```
