# Day36：讓診斷去挑處置，而不是事後把錯的那個劃掉

Day35 的適用性檢查其實是倒著做的。runbook 對每一張 decline-rate 告警都只提供
`k8s.rollout_undo`，然後在提議的最後一刻，provenance 檢查再把它劃掉——動作一直
都在清單上，只是被否決了。今天把分岔往前搬到 runbook 本身：一份 runbook 可以有
兩個處置，由已經跑完的 Tier 1 診斷決定哪一個適用，錯的那個從頭到尾不會被提議。

| 檔案 | 改了什麼 |
| --- | --- |
| `app/runbook.py` | 新增 `Condition`／`Step.when`／`Step.id`；`select_remediation()` 與 `format_remediation_choices()`；`DiagnosticResult` 多帶一份未截斷的 `output_text` |
| `app/agent.py` | `_inject_runbook` 改回傳 `(runbook, diagnostics)`；提議前先分岔，分岔結果也注入給模型 |
| `runbooks/payment-bad-deploy.yaml` | 新的 `provenance` 診斷步驟，兩條處置分支 |
| `app/tools/k8s_write.py` | `k8s.configmap_flag_set` 多一個 `restart_deployment`：翻完 flag 順手滾一次 Deployment |
| `app/blast_radius.py` | 乾跑要算進被重啟掉的 pod，以及「重啟的那個根本沒掛這份 ConfigMap」 |
| `tests/test_configmap_restart.py` | 6 條 |
| `tests/test_runbook_branch.py` | 10 條 |

## 條件長什麼樣

```yaml
diagnostics:
  # 分岔點。故意不帶 `check`——這一步是用來「分類事故」，不是用來斷言前提
  - id: provenance
    action: k8s_change_provenance
    args: { service: payment-service }

remediation:
  - desc: Roll back payment-service to the previous version
    action: k8s.rollout_undo
    when:
      diagnostic: provenance
      output_contains: "restores a genuinely different pod template"
```

`when` 刻意做得很不會表達：沒有 or、沒有 not、沒有運算式，所有子句是 AND。
半夜三點看不懂的分支比沒有分支更糟，比這個複雜的東西應該是第二份 runbook。

**`check` 跟 `when` 不是同一件事。** `execution.py` 在核准後執行前會重跑診斷，
**任何一條 `check` 失敗就中止**。所以拿來分類的診斷不能帶 `check`——那條 check
在另一條分支上本來就該失敗，而它會中止這條分支上正確的處置。這個坑寫在
`select_remediation()` 的 docstring 跟 runbook 的註解裡，測試也釘住了。

## 對這個叢集跑一次

```bash
cd aiops-agent/service
uv run python ../../otel-aiops-agent/ironman-2026/day36/probe_branch.py
```

同一張告警、同一個 `git_version` label，兩種結果：

```
a real deploy: the image changed      -> k8s.rollout_undo
a ConfigMap flip, plus a restart      -> k8s.configmap_flag_set (restart_deployment: payment-service)
```

值班的人看到的是這樣，**沒被選上的那條留在畫面上，還帶著原因**：

```
## Runbook remediation branch
- [NOT FOR THIS INCIDENT] Roll back payment-service to the previous version — `k8s.rollout_undo`
  (provenance does not say 'restores a genuinely different pod template')
- [APPLIES] Turn the new payment validator back off and restart payment-service
  (the change is in the mounted config, not in the image)
```

「我們沒有回滾，因為上幾次 rollout 根本沒改到跑起來的東西」是一句關於這次事故的
事實。一份被默默縮短的清單什麼都沒教到人。

## 第二條分支：重啟是動作的一部分

payment-service 的 flag 是**開機時讀一次**，所以只翻 ConfigMap 而不重啟，跑著的東西
不會有任何變化。第一版我把這條分支寫成一個未註冊的 `manual.` 名字（寫給人看、不執行），
因為當時 `k8s.configmap_flag_set` 不會重啟任何東西——提議它就是今天要修的那個錯誤
換一件衣服：**診斷對，動作沒辦法生效**。

當天稍晚把那個動作補完了：多一個 `restart_deployment` 參數，patch 完 ConfigMap 之後
用 kubectl 那個 `kubectl.kubernetes.io/restartedAt` 註記把 Deployment 滾一次
（不是砍 pod，rollout 會照 maxUnavailable 走）。於是這條分支變成真的可以執行：

```yaml
    action: k8s.configmap_flag_set
    args:
      flag: payment_use_new_validator
      value: false
      restart_deployment: payment-service     # ← 這一行才讓它成為一個修法
```

`session-cache-timeout` 那份**沒有**這一行，而且測試釘住了：user-service 是每個 request
重讀，重啟它是白買的爆炸半徑。

爆炸半徑也跟著變了——沒有重啟的時候不換掉任何一個 pod，有重啟的時候會，而那正是人在
核准的東西。對真實叢集乾跑：

```
payment-service | pods 2 | singleton False
   - restarts payment-service (2 pod(s)) after the flip
order-service   | pods 2 | singleton True
   - restarts order-service (1 pod(s)) after the flip
   - 'order-service' does not mount this ConfigMap — restarting it will not make it read the new value
```

最後那一句是給打錯字的人看的：重啟一個根本沒掛這份 ConfigMap 的服務，什麼都不會改變，
而那兩個參數只差一個名字。

## 分岔往「開」的方向壞

只有在條件**明確為假**的時候才會拿掉一個步驟：

```
case                                             offered
diagnostics never ran                            2 (both branches)
the condition names an id that does not exist    2 (both branches)
the provenance query errored                     2 (both branches)
```

拿錯的代價是值班的人永遠看不到那個修法；留錯的代價是治理閘門多審一行。
這兩個代價差很多。

## 兩層防線都留著

Day35 的 `inapplicable_by_provenance()` 沒有拿掉。分岔是在 runbook 寫對的時候
省下麻煩，適用性檢查是在 runbook 寫錯、或者根本沒有分支的時候接住——一個是設計，
一個是保險，兩個都問同一個叢集。
