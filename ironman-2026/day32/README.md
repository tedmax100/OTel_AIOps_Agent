# Day32：一個對的診斷，配一個沒用的處置

文章 Day32 用到的東西。三個層次，一個比一個往前搬：加一支工具把答案放在模型拿得到的
地方、在提議之前直接問叢集、最後把分岔搬進 runbook 自己的資料結構。

| 檔案 | 內容 |
| --- | --- |
| `probe_applicability.py` | 對活著的叢集問一次「上一次 rollout 到底改了什麼」，再用三種形狀的 fixture 走一次適用性檢查與治理決策。零 token |
| `probe_branch.py` | 讀出貨中的 runbook 在哪裡分岔，用兩種 provenance verdict 各跑一次，並示範三種「條件無法判定」的情況都會保留兩條分支 |

兩支都從 `aiops-agent/service/` 底下跑：

```bash
uv run python ../../otel-aiops-agent/ironman-2026/day32/probe_applicability.py
uv run python ../../otel-aiops-agent/ironman-2026/day32/probe_branch.py
```

同時改的是 agent 服務自己的原始碼：

| 檔案 | 改了什麼 |
| --- | --- |
| `app/tools/k8s.py` | `k8s_change_provenance`：逐個 revision 比對 image／env／掛載的 ConfigMap，回一句 verdict |
| `app/facts.py` | 新工具進兩張表（domain=`change`、role=`trigger`），漏了會被默默降級成 unknown/context |
| `app/governance.py` | `inapplicable_by_provenance()`：提議之前先問叢集，`decide()` 多一個 `inapplicable` 分支 |
| `app/runbook.py` | `Condition`／`Step.when`／`select_remediation()`：處置照診斷挑，沒被選上的留著並附原因 |
| `app/tools/k8s_write.py` | `k8s.configmap_flag_set` 多一個 `restart_deployment` |
| `app/blast_radius.py` | 乾跑要算進被重啟掉的 pod，以及「重啟的那個根本沒掛這份 ConfigMap」 |
| `tests/` | `test_change_provenance.py` 7 條、`test_inapplicable_actions.py` 7 條、`test_runbook_branch.py` 10 條、`test_configmap_restart.py` 6 條 |

## 這一天是從哪幾天合併過來的

下面保留了合併之前每一份原始筆記，內容沒有改寫，所以裡面的日號指的是舊的編排。

- [`README.day35-applicability.md`](README.day35-applicability.md)（適用性檢查那半）
- [`README.day36-branch.md`](README.day36-branch.md)（runbook 分支那半）
