# Day29：第一道門：信心分數要先能被查證

`calibration_report.py` 印可靠度圖，`promote_labels.py` 把外部標註接進正式的校準表，`backfill_grading_mode.py` / `fix_grading_mode.py` 處理那個「兩種 correct 不是同一種對」的欄位，`gate_probe.py` 跟 `slo_report.py` 讀門的現值。

## 這一天是從哪幾天合併過來的

下面保留了合併之前每一份原始筆記，內容沒有改寫，所以裡面的日號指的是舊的編排。

- [`README.day31.md`](README.day31.md)

- [`README.day35.md`](README.day35.md)

## 停止條件：`probe_sufficiency.py`

這一天有兩件事，共用同一個立場：**推理平面自己講的分數，治理平面沒有義務相信**。

一是校準門（那個分數準不準，誰有資格說它錯了）。二是調查迴圈的停止條件——同一個分數
一直在更前面決定「還要不要繼續查」，而那個位置沒有任何人在量它。

| 檔案 | 內容 |
| --- | --- |
| `probe_sufficiency.py` | 把舊的信心門檻跟新的四條檢查放在同一批 run 上並排，印出兩者的判決、不夠時發出去的指令，以及門檻改成三會付什麼代價。零 token、不碰 stack |

同時改的是 agent 服務自己的原始碼：

| 檔案 | 改了什麼 |
| --- | --- |
| `app/sufficiency.py` | 新增。`evaluate_sufficiency()` 四條確定性檢查，`pivot_instruction()` 把沒過的檢查翻成下一步要查什麼 |
| `app/agent.py` | `run_headless` 的迴圈條件從 `findings.confidence < threshold` 換成 `not verdict.sufficient`；證據跨 pivot 累積 |
| `app/config.py` | `sufficiency_min_sources` / `sufficiency_min_causal_roles`，兩個都預設 2 |
| `tests/test_sufficiency.py` | 18 條，其中 4 條驅動真的 `run_headless` 迴圈 |

## 跑探測

不需要 stack、不需要 API key，四組 run 都是手工組出來的 fact，因為整條規則的重點就是
**它可以從落盤的紀錄重算，不必再問模型一次**：

```bash
cd aiops-agent/service
uv run python ../../otel-aiops-agent/ironman-2026/day29/probe_sufficiency.py
```

### 1. 四組 run，一條一條判

```
one store, one role, sounds certain  (stated confidence 0.90)
  verdict : sufficient=False
    ok observed                   2/2 tool results were usable as evidence
    XX independent_sources        1 independent source(s) ['runtime']; needs 2
    XX causal_roles               observations speak to ['mechanism']; needs 2 distinct roles
    ok conclusion_cites_evidence  1 evidence item(s) cited in the conclusion

three stores, two roles, sounds unsure  (stated confidence 0.55)
  verdict : sufficient=True
    ok observed                   4/4 tool results were usable as evidence
    ok independent_sources        4 independent source(s) ['change', 'log', 'runtime', 'trace']
    ok causal_roles               observations speak to ['impact', 'mechanism', 'trigger']
    ok conclusion_cites_evidence  2 evidence item(s) cited in the conclusion
```

第三組（全部查空）示範 `catalog` 的位置：discovery 算得到一個 domain，但它的 role 是
`context`，所以 `causal_roles` 是空的。**列過有哪些 metric 不是一份佐證。**

第四組是證據齊全但結論一個值都沒引用。四條檢查裡這條最像形式主義，它擋的其實是
「查得很認真、結論卻是憑印象寫的」那種 run。

### 2. 不夠的時候，它收到什麼

```
The evidence for this conclusion is not yet sufficient. What is missing:
- independent_sources: 1 independent source(s) ['runtime']; needs 2
- causal_roles: observations speak to ['mechanism']; needs 2 distinct roles

Query a store you have not used yet this incident: logs; traces; the deploy/commit history.
Establish what changed (a deploy, a rollout, a config or code diff); and what users or
callers actually saw (error logs, failed requests).
Do NOT repeat a query that already came back empty - change the selector, the window,
or the store. …
```

舊版說的是「你的信心 0.55 低於門檻，換一個假設」，那是叫它再猜一次。

### 3. 兩條規則在哪裡不同意

```
run                                           conf  old       new
one store, one role, sounds certain           0.90  stop      pivot      <-- disagree
three stores, two roles, sounds unsure        0.55  pivot     stop       <-- disagree
everything came back empty                    0.65  pivot     pivot
solid evidence, conclusion cites none of it   0.80  stop      pivot      <-- disagree
```

分數是舉例用的，不是量出來的：這張表要看的是**兩條規則各自做了什麼決定**。

兩個方向都會不同意，這件事比只會變嚴格重要。第二列是一場四筆觀測、三個 store、
有 trigger 也有 impact 的完整調查，只因為模型對自己沒把握，舊規則會叫它再跑一輪。

### 4. 門檻改成三會怎樣

```
run                                          2 of each    3 of each
one store, one role, sounds certain          False        False
three stores, two roles, sounds unsure       True         True
incident older than trace retention          True         False
everything came back empty                   False        False
solid evidence, conclusion cites none of it  False        False
```

第三列是超過一小時的事故最常見的樣子：metrics 跟 logs 對得上、traces 已經被 Tempo 的
保留期吃掉、那天也沒有人部署。三選三會讓它永遠停不下來，而理由是 stack 的保留設定，
不是調查的品質。**一道經常因為錯誤理由亮紅燈的門，遲早會在凌晨三點被人偷偷調鬆。**

## 測試

```bash
uv run pytest tests/test_sufficiency.py -q      # 18 passed
```

最後四條會拿 stub 掉模型的真 `run_headless` 跑，確認迴圈真的照 verdict 轉向、
pivot 訊息真的送進去、以及證據跨 pivot 累積（每一輪的 ledger 照樣重置）。
