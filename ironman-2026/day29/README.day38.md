# Day38：一個 fingerprint 兼四份差事，跟案例記憶的第一版 schema

Day32 說過去事故庫沒活過來，當時歸因到 `_past_incident_context()` 撈的那個 JOIN，
並且補了 `eval/harness.py` 的 investigations 寫入。查完之後那句話要再往下修一層：
**JOIN 只是症狀，病在 `fp` 一個欄位同時被當四種 key 用。**

`webhook.fingerprint(labels)` = `sha256(alertname|service|git_version)[:16]`：

| 角色 | 誰在用 | 這個角色要的粒度 |
| --- | --- | --- |
| LangGraph `thread_id` | `run_headless(alert, thread_id=fp)` | 一個告警實例 |
| 告警去重 / cooldown | `_in_cooldown(fp)` | 一個告警實例 |
| 調查紀錄 | `investigations.fp` | **一次執行** |
| 校準標註 | `calibration.run_id = fp` | **一次執行** |
| 過去事故檢索 | `inv_query_similar` 的 JOIN | **一個事故，跨版本跨次數** |

三種粒度，一個欄位。所以它同時太窄也太寬，而 day36 那顆演習快照剛好兩種都拍到了。

## 太窄：drill 每部署一次就開一個新世界

演習每跑一輪換一個 image tag，`git_version` 在 key 裡，於是同一個事故裂成六個 fingerprint：

```
git_version=(none)                   rows=9  fp=1
git_version=v2.5.1-drill-055043      rows=1  fp=1
git_version=v2.5.1-drill-055519      rows=1  fp=1
git_version=v2.5.1-drill-061013      rows=1  fp=1
git_version=v2.5.1-drill-061239      rows=1  fp=1
git_version=v2.5.1-drill-061516      rows=1  fp=1
-> 6 fingerprints, 1 case_key: 1c2866de3a58ada9
```

`git_version` 進 fingerprint 對「去重」是對的——換了版本那確實是一個該重新查的新告警。
兩個角色要的東西直接衝突，不是誰寫錯了。

## 太寬：兩筆判決撐起十列「先例」

`cal_label` 的 UPDATE 是 `WHERE id = (SELECT id ... ORDER BY id DESC LIMIT 1)`，
一個 run_id 只有最後一列拿得到判決。而 `JOIN ... ON c.run_id = i.fp` 會把那一列的判決
攤到同 fp 的每一列調查上：

```
rows the old JOIN calls precedent: 10
human verdicts actually recorded:  2
of those rows, ones that concluded there was no incident: 3
  - [ui] Code regression in payment-service v2.5.1-drill ... new_validator_odd_cents ...
  - [ui] The alert was a false positive; no traffic, errors, or decline spikes were detected ...
  - [ui] Code regression in payment-service v2.5.0 introduced a new_validator_odd_cents ...
```

`LIMIT 5` 會從這十列裡抓五列注進 prompt，其中有在說「這是誤報、沒事」的，
而且全部帶著「人判定為正確」的身分。**這比空的事故庫糟**：空庫是沒有先驗，
這是有一個帶著人工背書的錯誤先驗。

順帶一提，`eval/harness.py` 早就自己繞過了——它的 run_id 是
`eval-<fixture>-seed<n>-<nonce>`，註解寫著「否則判決會貼到錯的實體列上」。
**修法在一個 caller 裡已經存在，只是沒長進 schema。**

## 產品端改動

拆成三個 key，粒度各自對上自己的角色。

| key | 粒度 | 從哪來 |
| --- | --- | --- |
| `fp` | 一個告警實例 | 現有 `fingerprint()`，**一行沒動** |
| `run_id` | 一次執行 | `{fp}-{ts}-{nonce6}` |
| `case_key` | 一個事故 | `sha256(norm(alertname)|service|symptom)`，**不含 git_version** |

| 改哪裡 | 改什麼 |
| --- | --- |
| `store.py` | 新增 `cases` / `case_ruled_out` 兩張表、五條 additive migration（`investigations.run_id`／`investigations.case_key`／`calibration.case_key`／`calibration.fp`／`action_requests.run_id`）＋ `cal_resolve_run_id()`、`case_key()`／`new_run_id()`／`case_upsert()`／`case_confirm()`／`case_query_similar()`／`case_ruled_out_for()`／`backfill_cases()` 等十一支函式 |
| `case_memory.py`（新） | ContextVar scope（死路是在工具層發現的，那裡不知道自己在查哪個事故）＋ `confirm_from_label()` 這個唯一的政策邊界 |
| `investigations.py` | 寫 `run_id`／`case_key`，並 `case_upsert` 記一次「被調查過」 |
| `calibration.py` | `record_run` 帶 `case_key` 與 `fp`；`label_run` 先把手上的 id 解析成一次執行，標完再把那一列讀回來（`cal_latest`），非自我來源才確認案例 |
| `action_requests.py` | 提案記下是哪一次執行提的（從 scope 拿，不改 signature） |
| `execution.py` | 自我驗證改標 `req.run_id or req.fp` |
| `webhook.py` | `_investigate_and_sink` 包住整個 run 開 scope（`reinvestigate` 走同一個入口） |
| `tools/query.py` | Prom「沒有這個指標名」、Loki「不是可索引標籤」兩處寫 `ruled_out` |
| `agent.py` | `_past_incident_context()` 改讀 cases ＋ ruled_out；舊的那支留成 `_legacy_past_incident_context()` 當 A/B 的對照組 |
| `config.py` | `case_memory_enabled`（只影響寫入）、`case_recall_enabled`（選 A/B 的哪一邊），都預設 True |
| `day22/leakcheck.py` | 認得召回區塊，給它自己的判決 `RCLL` ＋ 一行 `OPEN BOOK` |
| `eval/harness.py`、`eval/__main__.py` | `--recall {on,off,both}` 兩臂、`library_overlap()` 開書偵測、A/B 報表、fixture 新增 `forbid_versions` |
| `eval/fixtures.yaml` | 新增 `payment-latency-false-alarm`——A/B 的對照題 |
| `runbook.py` | `_norm` 升成公開的 `norm_alertname`，`store.case_key()` 直接用它 |

最後一項是 Day23 那個教訓：trace id 的 regex 在三個地方各寫一份，其中兩份是錯的。
**「這兩個是不是同一個告警」也不能有第二份定義。**

判斷「誰的話可以變成先例」用**允許清單**（`ui`／`manual`／`eval`／`eval-harness`），
不是照抄 `governance._SELF_LABEL_SOURCES` 那種排除清單。兩者的失效方向相反：
排除清單遇到將來新增的自我標註來源會**預設放行**，而這段文字是要進 prompt 的。

## `probe_case_memory.py`

前四項讀 day36 那顆真快照（**先複製到暫存目錄**——`store._connect()` 開檔就跑 migration，
day35 就發生過一支唯讀探測把它要保存的證據給升級了），後兩項用暫存 store。無叢集無 LLM。

```bash
# 從範例 repo 的根目錄跑
python3 ironman-2026/day38/probe_case_memory.py
```

```
[1] the snapshot's shape
    investigation rows: 23
    distinct fp:        8
    distinct case_key:  3

[4] after backfill
    backfill_cases: {'run_id': 23, 'case_key': 23, 'cases': 3}
    payment-decline-rate-high              occurrences=14  status=open  source=None
    payment-decline-rate-high-wrong-test   occurrences=8   status=open  source=None
    payment-decline-rate-high-v2           occurrences=1   status=open  source=None
    retrievable precedent: []

[5] who may write a root cause
    remediation-verified   mode=culprit       -> ignored         status=open
    ui                     mode=inconclusive  -> false_positive  status=false_positive
    ui                     mode=None          -> ignored         status=open
    ui                     mode=culprit       -> confirmed       status=resolved
    eval-harness           mode=culprit       -> confirmed       status=resolved
    retrievable precedent: 2

[6] dead ends
    outside a scope: False
    recalled inside the TTL: ['trace lookup older than the retention window',
                              'PromQL referencing http_requests_total']
    recalled after it      : ['PromQL referencing http_requests_total']
```

`[4]` 的召回是 **0**，而這是對的數字：舊的 `correct=1` 說不出它 judge 的是哪一次執行
（那正是這張表要修的 bug），硬把它們升格等於把錯誤先驗固化進新 schema。
案例庫從空的開始長。

`[5]` 那五列是整份改動的重點。自我驗證（`remediation-verified`）判 correct 也寫不進根因；
`inconclusive` 上的 correct 意思是「它正確地誰都沒怪」，記成 `false_positive` 而不是根因；
`grading_mode` 是 NULL 的來源不明，fail closed。

`[6]` 兩件事：模型自己說的「我排除了 X」會存但永不召回（沒有工具證據的自證，
注回去只會讓下一次更早停止思考）；「Tempo 查不到」帶 TTL，因為那是關於保留期的事實，
釘死會讓下一次連該查的都不查。同理，**只有「名字在這個環境不存在」被記成死路，
空視窗不記**——那是關於時間的事實，記下來會變成「別往那邊看」。

## 召回長什麼樣子

```markdown
## Past cases for this service (reference — current evidence wins)
- PaymentDeclineRateHigh (×6, last 2026-08-16, confirmed by ui)
  root cause: new_validator rejects odd cents
  resolved by: k8s.rollout_undo

### Already ruled out here — do not spend budget re-checking
- [query] LogQL stream selector on service (not an indexable stream label in this Loki)
```

兩半的排序邏輯不同：根因是「一直發生」所以值得召回，死路是「最近才被否證」所以
它被否證的那個環境比較可能還是現在這個。**真正會改變行為而不改變答案的是下半**——
它省掉的是這次執行本來要花在重發一條問不出東西的查詢上的預算。

## leakcheck：這個區塊是刻意洩題

召回區塊結構上就是「把上次的答案放回桌上」，所以拿 `ANSWER_TOKENS` 去掃一定會中——
那是它在運作，不是它壞了。但也不能像 measured 區塊那樣安靜放行：**有召回的那一次執行是
開書考，它的分數跟沒有召回的不可比。** 所以給它第三種判決。

空的案例庫（今天的真實狀態）：

```
[ok  ] injected #1: ## Label vocabulary (compiled from the Weaver registry)
[ok  ] injected #2: ## Runbook: payment-bad-deploy ...
no answer tokens in anything handed to the model.
```

種一筆確認過的案例之後，同一支腳本：

```
[RCLL] injected #2: ## Past cases for this service (reference — current evidence
...
OPEN BOOK: 1 recalled item(s) from the case library are in this prompt. Whatever this
run scores is not comparable to a run without them — an A/B has to use a fixture the
library has never seen.
```

離開碼還是 0（沒有意外的洩題），但報表上寫明了這是哪一種考試。這比擋下來有用：
真正要防的不是這個區塊存在，是**在不知情的情況下拿它的分數去跟別人比**。

## 測試

`tests/test_store.py` 新增 12 條（key 的兩個方向、回填冪等、召回一個 case 一列、
誤報不召回、TTL、依 kind 作廢），`tests/test_eval_harness.py` 新增 4 條（`forbid_versions` 的三種輸入、
出貨的 fixture 真的構成一組對照），`tests/test_case_memory.py` 新增 26 條（scope 的邊界、
五種標註來源的政策、召回區塊的內容、model 自證的死路不進 prompt、A/B 兩邊確實不同）。
全套 466 → **495 passed**。

## 一筆判決只蓋一次執行

「太寬」那半原本只被繞過（召回不再經過 investigations，所以不會重複），判決本身仍然
說不出它 judge 的是哪一次。要真的解掉，卡點是**兩個標註端手上都只有 fingerprint**：
plugin 的 `POST /investigations/{fp}/label`，跟 `execution.py` 的自我驗證。

做法不是逼它們生出 run_id，是**把那次解析寫出來**：

- `calibration` 多一個 `fp` 欄位。`run_id` 從此是一次執行，`fp` 是分組。
- `cal_resolve_run_id(ident)`：精確的 run_id 優先，比不到就解析成「這個告警最後那一次」，
  而且回傳的字串跟傳進去的不一樣——呼叫端看得出來剛剛做了一個選擇。
- `action_requests` 記下提案是哪一次執行提的（從 scope 拿，不動 signature），
  自我驗證改標那一次，而不是「這個告警最後那一次」——告警風暴之後那是兩份不同的推理。

原本這個解析是**意外發生**的，藏在 `cal_label` 那句 `ORDER BY id DESC LIMIT 1` 裡：
行為一樣，但沒有任何地方說有人在做選擇，而落選的那幾次永遠不會被標到。

實測（九次執行同一個 fp、一筆人工判決）：

```
labeled = {'fp1-run-8': 1}          # 不是九列都是
list_investigations -> [correct=True]，run_id=fp1-run-8
```

代價要講清楚：**這不會讓校準樣本變多。** 九次執行還是只換一個樣本，因為只有一個人按了
一次。差別在於現在那一筆說得出它在講哪一次，而另外八次誠實地留在 unlabeled——
以前它們是「被判定為正確」。

## 讓 A/B 變成跑得動的東西

A/B 本身還沒跑（要整套 stack ＋ LLM），但**跑它需要的東西都做完了**，
因為這個實驗最容易做錯的地方不是跑，是不知道自己在跑什麼。

```bash
python -m app.eval run --recall both -n 3
```

`--recall both` 把同一組 fixture 跑兩輪（先對照組，因為召回那輪不會寫回案例庫，
但把對照組排後面會多吃 N 次牆鐘漂移），然後印出並排。真正重要的是報表的第一段：

```
OPEN BOOK — the case library already answers these fixtures:
  payment-decline-culprit: 1 case(s) recalled
  The recall arm is retrieving an answer it was told. Whatever the delta
  below is, it is not evidence that recall helps an unseen incident.

fixture                             recall off   recall on    delta
payment-decline-culprit                   67%        100%     +33%
order-service-discover                    33%         33%      +0%

A delta here is a difference between two small samples of a non-deterministic model.
Day27 measured the same code scoring 2.5-3.5 across three runs; read the transcripts
before reading the delta.  (seeds/arm: 3)
```

`library_overlap()` 有一個細節值得單獨講：**它讀的是 production store，不是 eval store。**
`_past_incident_context()` 不吃 path 參數，所以召回在 eval 過程中一樣是走
`settings.store_path`——查 eval store 會得到「這個實驗很乾淨」，而 agent 讀的是另一顆檔案。
Day32 那個 JOIN 安靜回零筆就是同一條接縫（兩張表在不同檔案裡），這次先把它釘成測試。

那個 `+33%` 在這種樣本數下什麼都不是，所以報表自己會這樣說——Day27 量過同一份程式碼
連跑三次分數在 2.5–3.5 之間跳。**寫這行字比寫那個數字重要。**

## 對照題：同一個服務，不同的告警

A/B 最容易做出來的假結論是「開了召回分數變高」——但如果那題的答案就在案例庫裡，
量到的是檢索不是推理。所以要有一題**案例庫答不出來、但又離得夠近**的。

離得夠近很重要。隨便找一個沒資料的服務當對照，只證明「沒有召回就沒有召回」。
真正要抓的失效是：payment-service 的事故一旦成為案例，**這個服務的每一個告警**
都離「被塞一份 v2.5.0 是元凶」只差一次比對放寬。

這座 stack 剛好給了材料。延遲是平的——6 小時視窗的平均，v2.4.1 是 0.059s、
v2.5.0 是 0.041s，**「壞掉的」那版反而比較快**：

```
sum by (git_version) (increase(payment_charge_duration_seconds_sum[6h]))
  / sum by (git_version) (increase(payment_charge_duration_seconds_count[6h]))
v2.4.1  0.05894514767932489
v2.5.0  0.04062898751733703
```

於是 `payment-latency-false-alarm`：同一個服務、不同的 alertname、`expect: inconclusive`。
誠實的答案是「延遲沒有動」。

**這題需要一個新的判準。** `forbid_services` 抓不到這個失效——告警指名 payment-service，
答案也講 payment-service，服務是對的，錯的是它把延遲掛在一個從別的症狀繼承來的版本上。
所以 `Fixture` 加 `forbid_versions`：

```
primed answer (conf 0.5, payment-service, v2.5.0) -> correct=False
honest hedge  (conf 0.5, payment-service, None)   -> correct=True
overconfident (conf 0.9, nobody named)            -> correct=False
```

## `seed_case.py`：讓 A/B 可以重跑

沒有這支，實驗不可重現：你得跑一輪、在 plugin 上手動標一筆、再跑一輪，
而每次被標的都是不同的調查，兩臂之間差的就不只是那個開關。

它走的是真正的入口（`case_upsert` ＋ `confirm_from_label`），不是塞 SQL，
所以連「誰有資格變成先例」那條政策也一起被跑到。

```bash
python3 ironman-2026/day38/seed_case.py --store <runtime store>
```
```
case 38687efd6b6aaed0 -> confirmed
  occurrences       1
  status            resolved
  root_cause_source manual
  seeded from fp    356562681819193e  (git_version v2.4.9)
  dead ends         2
```

`--fp-version` 那個參數是這支腳本的重點：**種下去的那次事故掛在另一個版本上**，
所以在舊的 key 底下，它跟 eval 要跑的那個告警是兩件不相干的事，召回不可能發動。
發動了，就代表 case key 真的活過了一次改版。

種完之後的實際狀態：

```
overlap: [('payment-decline-service', 1)]        # 只有這題是開書
_past_incident_context('payment-service', 'PaymentHighDeclineRate')
  -> 根因 ＋ 兩條死路
_past_incident_context('payment-service', 'PaymentChargeLatencyHigh')
  -> ''                                          # 對照題乾淨
```

`--clear` 會把根因清掉並作廢死路，`overlap` 回到 `[]`——兩臂之間可以來回切。

## 完整的 A/B 流程

```bash
python -m app.eval run --stack --recall off -n 3          # 乾淨基線
python3 ironman-2026/day38/seed_case.py --store aiops.db  # 種一筆案例
python -m app.eval run --stack --recall both -n 3         # 兩臂並排
python3 ironman-2026/day38/seed_case.py --store aiops.db --clear
```

## 跑完了：兩個結果，第二個才是重點

2026-08-18，四個 fixture × 3 seeds × 2 臂 = 24 次真實 RCA，資料是同一顆已經開著的
stack 容器（兩臂打的是位元相同的資料），完整報表在 `ab-report-20260818.txt`。

```
OPEN BOOK — the case library already answers these fixtures:
  payment-decline-service: 1 case(s) recalled

fixture                             recall off   recall on    delta
payment-decline-service                   67%        100%     +33%
user-service-no-incident                  33%          0%     -33%
order-service-discover-before-query         0%         67%     +67%
payment-latency-false-alarm                0%          0%      +0%
```

### 一、那個 +33% 什麼都不是，而這次能證明

跑之前先量了一件事：四個 fixture 裡**只有一個拿得到召回**。

```
payment-service  PaymentHighDeclineRate       recall=664 chars
payment-service  PaymentChargeLatencyHigh     recall=0 chars
user-service     UserServiceLatencyWarning    recall=0 chars
order-service    OrderErrorRateWarning        recall=0 chars
```

也就是說，`user-service-no-incident` 跟 `order-service-discover-before-query` 這兩題，
**兩臂的 prompt 一個位元組都沒有差**。它們動了 −33% 跟 **+67%**。

所以這次實驗真正的產出不是那個 +33%，是**它自己量出來的雜訊底線：在 3 seeds 之下
至少 ±67 個百分點**。開書那題只動了 +33%，比雜訊還小。

這比「召回沒有幫助」強得多——後者是一個沒有力量的結論，前者是一把尺：
**任何用 3 seeds 量出來、小於 67 個百分點的 A/B 差異，都不能拿來說事。**
要談召回有沒有用，得先把 seeds 加到能把這個底線壓下來的數量，
而那是算得出來的成本，不是感覺。

Day27 當時量到「同一份程式碼連跑三次總分在 2.5–3.5 之間跳」，那時只能說「會跳」。
這次因為有三題結構上不受影響，跳的幅度第一次有了一個下界。

### 二、對照題兩臂都是 0%，而原因不是召回

`payment-latency-false-alarm` 六次全錯，兩臂一樣：

```
arm  run                              conf  correct
off  payment-latency-false-alarm s0   0.7   0
off  payment-latency-false-alarm s1   0.7   0
off  payment-latency-false-alarm s2   0.8   0
on   payment-latency-false-alarm s0   0.7   0
on   payment-latency-false-alarm s1   0.9   0
on   payment-latency-false-alarm s2   0.7   0
```

六次的 `suspected_version` 全部是 **v2.5.0**，而這座 stack 裡 v2.5.0 的延遲比 v2.4.1
**還低**（0.041s vs 0.059s）。摘要長這樣：

```
Code regression in payment-service version v2.5.0 caused increased latency.
Code regression in the latest deployment (v2.5.0) of payment-service caused high latency.
Code regression in payment-service v2.5.0 causing latency due to new_validator_odd_cents.
```

**這個失效跟召回無關**——關掉召回的那三次一模一樣，而且那三次的 prompt 裡連一個字的
案例都沒有。它的來源是環境本身：這座 demo 只有一個響亮的事故，`reason="new_validator_odd_cents"`
就長在 Prometheus 的 label 上、查得到，於是**這個服務的任何告警都會被歸到它頭上**。

我原本是拿這題當「召回會不會污染別的告警」的對照組，結果它先抓到一個更基本的問題：
**不需要案例記憶，這個 agent 就已經在做「把手邊唯一認識的事故套到新症狀上」這件事。**
案例記憶只會讓這件事更順手——所以那條 `forbid_versions` 判準留著是對的，
只是它現在擋的是一個比我預期更早出現的失效。

順帶一提，`user-service-no-incident` 三次全掛在 `discover_before_retry`：
查回空的就換一支工具再查，沒有先去 discover。**Day1 那個坑，今天還在。**

## 沒做的
- **A/B 跑了，但沒有結論。** 雜訊底線 ±67pp 蓋過了唯一那題的 +33%。要有結論得加 seeds，
  而該加到多少目前只知道下界。
- **「一個響亮事故蓋住一切」沒有處理。** 對照題六次全錯的原因不在召回，在環境；
  這需要的是第二個獨立事故，不是改 schema。`eval/harness.py` 依然刻意不開 case scope——開了的話 fixture 每跑一次就在
  案例庫長一筆，第二輪就自動變成開書考。
- **沒有 case 的合併／拆分介面。** 正規化把兩個真的不同的告警合在一起時只有 warning。
- **`symptom` 恆為空字串。** chat 那條沒有 alertname 的路徑還是只能靠 service 匹配。
- 探測腳本沒有斷言，也沒進 CI。

設計稿在主 repo 的 `doc/aiops-agent-case-memory.md`。
