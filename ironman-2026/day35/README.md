# Day35：一個對的診斷，配一個沒用的處置

告警上帶著 `git_version`，agent 就說「那個版本的 code regression」。四次都這樣說，
四次都很有信心，而其中三次故障根本不在 pod template 裡，在那個 template 掛載的
ConfigMap 裡——`rollout undo` 還原一個從來不是問題的 template，症狀一動也不動。

這一天做兩件事，而它們的成效差很多：

| 檔案 | 內容 |
| --- | --- |
| `probe_applicability.py` | 對活著的叢集問一次「上一次 rollout 到底改了什麼」，再用三種形狀的 fixture 走一次適用性檢查與治理決策。零 token |

同時改的是 agent 服務自己的原始碼：

| 檔案 | 改了什麼 |
| --- | --- |
| `app/tools/k8s.py` | 新增 `k8s_change_provenance`：逐個 revision 比對 image／env／掛載的 ConfigMap，回一句 verdict |
| `app/facts.py` | 新工具進兩張表（domain=`change`、role=`trigger`），漏了會被默默降級成 unknown/context |
| `app/governance.py` | `inapplicable_by_provenance()`：提議之前先問叢集，`decide()` 多一個 `inapplicable` 分支 |
| `app/agent.py` | 提議前呼叫它，off-budget，跟 actuation 的刷新同一個待遇 |
| `tests/test_change_provenance.py` | 7 條 |
| `tests/test_inapplicable_actions.py` | 7 條，含「叢集查不到就不擋」的 fail-open |

## 跑探測

```bash
cd aiops-agent/service
uv run python ../../otel-aiops-agent/ironman-2026/day35/probe_applicability.py
```

### 這個叢集現在的樣子

```
rev 69   v2.5.0     demo-services/payment:dev    changed=(first)
rev 70   v2.5.0     demo-services/payment:dev    changed=[]
rev 71   v2.5.0     demo-services/payment:dev    changed=[]
rev 72   v2.5.0     demo-services/payment:dev    changed=[]

verdict: the last rollout changed nothing the process runs (at most a version label
or a restart). If behaviour changed, the cause is outside the template — check the
mounted config: configMap/payment-flags
```

四個 revision 同一個 image。**`git_version` 在這套 demo 裡是 pod template 的一個 label，
不是一個不同的 build**，所以「回滾到上一版」在這裡不會改變任何跑起來的東西。

### 三種形狀，告警分不出來

| 形狀 | `changed_vs_previous` | 是不是部署 |
| --- | --- | --- |
| ConfigMap 翻了個 flag ＋ 重啟 | `[]` | 不是 |
| 只有版本 label 動了 | `['git_version(label only)']` | 不是 |
| image 真的換了 | `['image']` | 是 |

### 同一個動作，同一個信心，兩種結果

```
shape                                   conf  verdict
a ConfigMap flip, plus a restart        0.95  ESCALATE (not proposed)
only the version label moved            0.95  ESCALATE (not proposed)
a real deploy: the image changed        0.95  propose
the cluster cannot answer               0.95  propose
```

最後一列是刻意的：叢集答不出來的時候**不擋**。fail-closed 會在 k8s 一安靜的時候
把所有提議都吃掉，而那正是值班的人最需要它們的時候。

## 真實驗收：兩次跑，兩種結果

同一個事故、同一份 prompt、同一個工具清單，連跑兩次：

| | 有沒有呼叫 `k8s_change_provenance` | 診斷 | 提議 |
| --- | --- | --- | --- |
| 第一次 | 有（結論裡引用了它的原話） | ✅ ConfigMap 造成的 | ⚠️ `rollout_undo → propose` |
| 第二次 | **沒有** | ❌ 又說成 v2.5.0 code regression | ✅ `rollout_undo → escalate` |

第二次那句理由是叢集自己回答的，不是模型：

```
governance fp=c8f06989c9d80200 action=k8s.rollout_undo -> escalate
  (the cluster says the last rollouts changed nothing the process runs, so a rollback
   restores an identical pod template; the mounted config (configMap/payment-flags)
   is where the change is)
```

**加一個工具，只是把正確答案放在它拿得到的地方；它拿不拿是機率問題。**
而那道在提議之前直接去問叢集的檢查，兩次都成立。

## 測試

```bash
uv run pytest tests/test_change_provenance.py tests/test_inapplicable_actions.py -q   # 14 passed
uv run pytest tests/ -q                                                              # 689 passed
```

`test_change_provenance.py` 最後一條特地去驗新工具有沒有進 `facts.py` 那兩張表：
漏了不會有人報錯，它只會被歸成 `unknown` ＋ `context`，然後安靜地不算證據。
