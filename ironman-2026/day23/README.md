# Day23：下一步建議，要連「多大」一起講

`blast_radius.py` 只做一件事：在任何動作執行之前，用唯讀的方式算出它會碰到什麼。
這一天把它跑滿，然後修掉三個讓「建議」講不清楚的地方。

| 檔案 | 內容 |
| --- | --- |
| `dryrun_probe.py` | 八個提案的唯讀乾跑＋policy 判決，最後用 generation / resourceVersion 證明它真的沒有改動任何東西。零 token |
| `propose_probe.py` | 同一個事故、兩種 alertname 拼法，各跑一次真的 RCA，印出比對到的 runbook、governance 決策、以及產生的 action request |

同時改的是 agent 服務自己的原始碼：

| 檔案 | 改了什麼 |
| --- | --- |
| `app/agent.py` | 新增 `_proposal_footprint()`：提案的當下就跑一次乾跑，把範圍跟 policy 判決一起存進 ActionRequest |
| `app/action_requests.py` | `create_from_decision()` 收 `blast_radius` |
| `app/blast_radius.py` | scale 到 0 的拒絕理由改成講「歸零」，不再誤報成 singleton |
| `app/runbook.py` | alertname 正規化後的 fallback 比對＋比對失敗時的 warning |
| `tests/` | 七條新測試（runbook 三條、blast radius 兩條、action request 兩條） |

## 乾跑

從 `aiops-agent/service/` 底下跑，kubeconfig 指到 demo cluster：

```bash
uv run python ../../otel-aiops-agent/ironman-2026/day23/dryrun_probe.py
```

```
roll back the suspect deploy
  footprint: target demo/payment-service, revision 25→24, replicas 2→2, affected 2 pod(s)
  policy   : ALLOW — within policy (affected 2 pod(s), ns demo)

roll back a single-replica service
  footprint: target demo/user-service, revision 3→2, replicas 1→1, affected 1 pod(s), singleton
  policy   : REFUSE — target is a singleton (single replica) — denied by policy

roll back something that isn't there
  footprint: dry-run unavailable: no Deployment named 'typo-service' in demo
  policy   : REFUSE — dry-run unavailable (…); fail-closed

roll back in kube-system
  footprint: target kube-system/coredns, revision 1→None, replicas 1→1, affected 1 pod(s), singleton,
             no previous revision to roll back to
  policy   : REFUSE — namespace kube-system is protected

scale 2 -> 4    ALLOW — within policy (affected 2 pod(s), ns demo)
scale 2 -> 60   REFUSE — affected pods 58 exceeds max 5
scale to zero   REFUSE — scaling to zero takes the service fully down
scale without a replica count
  policy   : REFUSE — dry-run unavailable (scale requires an integer 'replicas' arg); fail-closed
```

「scale to zero」那一列改之前的拒絕理由是 `target is a singleton`，因為 `singleton`
的定義是「目標副本數 ≤ 1」，0 也算。訊息沒有錯，但它會把人推去試 `replicas=1`，
而那一樣會被拒（理由才是真的 singleton）。現在歸零有自己的理由。

第二段是唯讀的證據：

```
  before: replicas=2 generation=28 resourceVersion=606260
  after : replicas=2 generation=28 resourceVersion=606260
  6 dry-runs later, the object is unchanged
```

## 從診斷到建議

```bash
uv run python ../../otel-aiops-agent/ironman-2026/day23/propose_probe.py
```

改之前，同一個事故、兩種 alertname 拼法，結果完全不同：

```
as the alert rule names it: alertname='PaymentDeclineRateHigh'
runbook matched: None
confidence     : 0.70
decisions      : 0
action requests: 0

as the runbook declares it: alertname='payment-decline-rate-high'
runbook matched: payment-bad-deploy
confidence     : 0.90
decisions      : 1
  - k8s.rollout_undo → propose (high confidence but action is approval-gated)
action requests: 1
  - k8s.rollout_undo status=proposed args={'deployment': 'payment-service', 'namespace': 'demo'}
    footprint at proposal time: None
```

兩個問題：大小寫拼法不同就整條鏈斷掉而且沒有人講話，以及**提案送到人面前時
`blast_radius` 是 `None`**——範圍要等到人按下同意、進了執行管線才算。

改之後兩邊都會比對到，而且提案自己帶著範圍：

```
runbook matched: payment-bad-deploy
decisions      : 1
  - k8s.rollout_undo → propose
action requests: 1
    footprint at proposal time: {'target': 'demo/payment-service', 'current_revision': '25',
      'target_revision': '24', 'current_replicas': 2, 'target_replicas': 2, 'affected_pods': 2,
      'singleton': False, 'cross_namespace': False, 'in_protected_namespace': False,
      'available': True, 'policy_ok': True,
      'policy_reason': 'within policy (affected 2 pod(s), ns demo)'}
```

用正規化比對到的時候會留一行 warning，因為這是要去修的東西，不是要一直吃下來的：

```
runbook payment-bad-deploy matched alertname 'PaymentDeclineRateHigh' only after
normalization (trigger says 'payment-decline-rate-high') — align the alert rule
or the runbook trigger
```

執行前那道乾跑沒有拿掉，兩次都要跑：提案的那次是給人看的，執行的那次是防
TOCTOU 的（叢集會在這中間動）。

## 測試

```bash
uv run pytest tests/test_runbook.py tests/test_blast_radius.py tests/test_action_requests.py -q
```
