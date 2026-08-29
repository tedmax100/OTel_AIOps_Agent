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
| `app/agent.py` | `_reconcile_version_with_provenance()` 掛在 `extract_findings()` 出口：provenance 說 template 沒變就清掉 `suspected_version`，並在 evidence 補一行說明 |
| `app/eval/process.py` | `used_tools` 檢查：這支工具到底有沒有被呼叫過。只算有沒有伸手，不算叢集有沒有回話 |
| `app/eval/harness.py` | `blames_forbidden_version()`：`forbid_versions` 改成同時讀 `suspected_version`／`summary`／`hypothesis`，而且兩種 grading mode 都讀（culprit 那側以前根本沒讀） |
| `app/eval/fixtures_live.yaml` | 新增。需要真叢集的 fixture 分檔放這裡 |
| `tests/` | `test_change_provenance.py` 7 條、`test_inapplicable_actions.py` 7 條、`test_runbook_branch.py` 10 條、`test_configmap_restart.py` 6 條、`test_findings_provenance.py` 7 條 |

## 量「它到底會不會用那支工具」

文章後半那個 5% 是這樣跑出來的。**這題不能跑在烤好資料的 stack 上**：那個 image 裡
沒有 Deployment、沒有 ReplicaSet、也沒有 ConfigMap，一個主題就是「叢集裡改了什麼」
的題目在那邊只會因為環境而紅。

```bash
# 1. 事故要是活的（flag 讀在啟動時，所以要重啟 payment）
demo-services/scripts/incident.sh status
demo-services/scripts/incident.sh start bad-validator

# 2. 三個 store + webapp + payment 的 port-forward
kubectl -n demo port-forward svc/prometheus 9090:9090 &
kubectl -n demo port-forward svc/loki       3100:3100 &
kubectl -n demo port-forward svc/tempo      3200:3200 &
kubectl -n demo port-forward svc/webapp     8002:8000 &
kubectl -n demo port-forward svc/payment-service 8001:8000 &
```

第三步是最容易漏的。`demo-services/scripts/load.sh` 打的金額**永遠是偶數**，而這個
事故的觸發條件是奇數分，所以光開壓測是永遠觸發不了它的：

```bash
cd demo-services && ./scripts/load.sh 4 &          # 背景流量
# 另一支：直接灌奇數分的 charge，這才是讓事故在資料裡看得見的東西
while true; do
  curl -sS -o /dev/null -X POST http://localhost:8001/charge \
    -H 'content-type: application/json' \
    -d "{\"order_id\":\"odd-$RANDOM\",\"user_id\":\"u-1\",\"amount_cents\":1001}"
  sleep 1
done &
```

等訊號真的出現再跑，不然量到的是環境不是模型：

```bash
curl -s localhost:9090/api/v1/query \
  --data-urlencode 'query=sum by (status) (rate(payment_charges_total[5m]))'
# declined 1.62 / authorized 1.05  → 拒付率 61%，可以跑了
```

```bash
cd aiops-agent/service
uv run python -m app.eval --fixtures app/eval/fixtures_live.yaml \
    --repeat 20 --no-record --store /tmp/eval-live.db
```

`--no-record` 是預設要帶的：那份 committed fixture record 是自治權門的證據，
用一座別人重現不了的叢集量出來的東西不應該替它背書。

跑完記得 `demo-services/scripts/incident.sh stop bad-validator`，並把背景那幾支收掉。

## 這一天是從哪幾天合併過來的

下面保留了合併之前每一份原始筆記，內容沒有改寫，所以裡面的日號指的是舊的編排。

- [`README.day35-applicability.md`](README.day35-applicability.md)（適用性檢查那半）
- [`README.day36-branch.md`](README.day36-branch.md)（runbook 分支那半）
