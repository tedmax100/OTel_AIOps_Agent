# Day36：把 Act 那一格真的走通一次

`executions` 只有一列、`success=0`、那次失敗是 401。ARR / DQ-SLO / AE-SLO 三個 SLO 的分母是零，
所以這一天做的不是「再寫一點程式」，是**讓那件事真的發生一次，而且被記下來**。

已經跑完了。2026-08-16 的結果：

```
ts                    success  drill
2026-08-08T09:02:45Z     0       0     ← 那個 401
2026-08-16T05:35:55Z     0       1     ← settle window 誤判（見下）
2026-08-16T05:59:56Z     1       1     ← 劇本 a：第一次成功
2026-08-16T06:19:58Z     0       1     ← 劇本 b：設計上就該失敗
```

這個資料夾有：Stage 0 的常駐可執行性探針（程式在服務裡，這裡只寫怎麼驗）、
Stage 1 的演習腳本 `gameday.py`、以及演習前後的 store 快照。

## 那個 401 的真正原因（更正）

不是憑證過期。`tools/k8s_write.py` 把認證前綴掛在 `api_key_prefix["authorization"]`，
而 kubernetes client（36.0.2）找 key 時用 `"BearerToken"` 當主鍵、`"authorization"` 當別名，
**找 prefix 時只認主鍵**。所以 token 找得到、`Bearer ` 前綴永遠加不上去，裸的 JWT 送出去，
API server 解析不了就回 401。

一個格式壞掉的 header 跟一張死掉的憑證，從外面看是同一個 401。修法是兩個 key 都掛，
回歸測試直接斷言送出去的字串是 `Bearer <jwt>`（`tests/test_k8s_write.py`）。

## Stage 0：可執行性變成常駐訊號

確認部署的 image 夠新（沒有輸出就要先跑 `aiops-agent/scripts/deploy.sh`）：

```bash
curl -s localhost:8000/openapi.json | jq -r '.paths | keys[]' | grep actions/readiness
```

這兩個是不同的東西，兩個都要看：

```bash
curl -s localhost:8000/healthz           | jq .actuation   # 快取的判決 + age（常駐訊號）
curl -s localhost:8000/actions/readiness | jq .verdict     # 現場探一次（權威）
```

探針每 `ACTUATION_PROBE_INTERVAL_SECONDS`（預設 300 秒）跑一次，每一次都寫進
`actuation_probes` 表。驗收方式是刻意把權限拿掉，看它多久變紅：

```bash
kubectl -n demo delete rolebinding aiops-agent-write   # 破壞
sleep 320
curl -s localhost:8000/healthz | jq .actuation          # 應該 proven_good=false
kubectl apply -f demo-services/k8s/15-aiops-agent.yaml  # 修回來
```

## Stage 1：演習

### 先手動打開 kill switch

腳本**不會**幫你打開，這是刻意的：

```bash
kubectl -n demo set env deploy/aiops-agent ACTIONS_ENABLED=true
kubectl -n demo rollout status deploy/aiops-agent --timeout=180s
```

演習做完記得關掉（`ACTIONS_ENABLED=false`）。

### 兩個劇本

| 劇本 | 壞掉的東西住在哪 | `rollout undo` 修得好嗎 | 預期終態 |
| --- | --- | --- | --- |
| a bad-deploy | pod template（新 ReplicaSet） | 修得好 | `succeeded` |
| b bad-config | `payment-flags` ConfigMap | 修不好 | `rolled_back` |

兩個劇本的**症狀一模一樣**（payment-service 拒絕率飆高），根因不同。
b 比 a 重要：它才會逼 verify 失敗、逼自動回滾真的動一次。只跑 a 量出來的 AE-SLO 100%，
跟原本的 0% 一樣沒有資訊。

```bash
# 從 repo 根目錄跑
uv run python ironman-2026/day36/gameday.py plan            # 只印計畫跟現況，不動任何東西
uv run python ironman-2026/day36/gameday.py run --scenario a
uv run python ironman-2026/day36/gameday.py cleanup
uv run python ironman-2026/day36/gameday.py run --scenario b
uv run python ironman-2026/day36/gameday.py cleanup
```

腳本會：跑 preflight（agent 活著、寫入憑證現場探測 OK、kill switch 真的開著、webhook secret 在，
任一條不過就拒跑）→ 把 store 從 pod 裡 `kubectl cp` 出來存一份 → 打奇數分的流量
（demo 自己的 `load.sh` 金額永遠是偶數，不會被 new validator 拒絕，直接拿來用會注入一個看不見的事故）
→ 注入故障 → 等 90 秒讓 Prometheus 看得到 → 送一則**當下時間戳**的告警（不是重播六月那份 JSON，
RL-SLO 已經因此量到過自己的手）→ 等 ActionRequest → 核准 → 追到終態 → 評分 → 印出 audit 全鏈
→ 再存一份 store。

### 每次演習是一個新的事故

告警的指紋是 `alertname|service_name|git_version`，而冪等鍵吃這個指紋。兩次演習共用同一個
`git_version`，第二次就會被正確地判成第一次的重複。所以每一輪用一個新的
`v2.5.1-drill-<HHMMSS>`，注入、告警、清理三邊都從 `.drill-state.json` 讀同一個值。
這不是繞過冪等，是承認每次演習真的是一次新的部署。

### 跑之前要知道的三件事

演習過程中被擋下來的，多數不是腳本壞掉：

- **斷路器會跳開。** 同一個目標兩次連續失敗就 open，而且不會自己關。
  `curl -X POST localhost:8000/actions/breaker/reset -H 'Content-Type: application/json' -d '{}'`
- **副本數要 ≥ 2。** 單副本會被 `deny_singletons` 政策擋掉（這是對的）。
  `20-payment-service.yaml` 裡寫的是 `replicas: 1`，所以任何重新套用 manifest 的動作
  都會把它打回 1；`cleanup` 會還原它記錄到的實際副本數。
- **cleanup 會失敗給你看。** 它用 `$patch: delete` 明確移除注入的 volume（`kubectl apply`
  做不到，三方合併不刪它不擁有的欄位），然後 checked 的 `rollout status`。
  之前它印過「done」而叢集其實是壞的，現在不會了。

### 演習資料要標記出來

告警帶 `drill=true` 跟 `drill_scenario` 兩個 label，`executions` 跟 `action_outcomes`
都有 `drill` 欄位，值在寫入當下就決定。算 SLO 的時候演習跟真實事故不能混在同一個比率裡，
不然就是 RL-SLO 那個坑的翻版。

## 評分（AE-SLO）

```bash
# 一次執行的人工判決；只有真的動過叢集的終態可以評
curl -X POST localhost:8000/actions/requests/<request_id>/outcome \
  -H 'Content-Type: application/json' \
  -d '{"resolved": true, "actor": "nathan", "side_effect": false, "note": ""}'

curl -s localhost:8000/actions/ae-slo | jq
```

四條規則寫在 `store.ae_slo()` 裡，不靠人記得：n < 5 不印比率、演習不進事故的比率、
有副作用不算有效、只有真的執行過的請求可以評分。verify 自己的判決也存下來，
一不一致是算出來的（`verify_agreement`）。

自產標註（`remediation-verified/-failed`）不能用來解鎖 AUTO，人按的才可以，
這條在 `governance_min_human_labeled_runs` 就有了。

目前：`incidents 0/0`、`drills 1/3`、三次演習 verify 與人工判斷一致。

## 這裡沒做的事

- 沒有讓任何動作變成 AUTO。註冊表裡兩個動作都 `requires_approval=True`，
  而 governance 在高信心之後第一道就是這個判斷，所以 ARR 的分子目前結構上不可能大於 0。
  要拆這個天花板得把 `requires_approval` 從靜態布林換成讀 blast radius 的判斷，留給後面。
- 沒有接 SLO → 治理旋鈕的自動連動。
- AE-SLO 的分母只有演習，而且三筆全部同一個事故類型、同一個目標。
- runbook 只有一本，而且 `_verify_outcome()` 在沒有 verify 契約時會樂觀跳過並回報成功，
  等於一份沒寫 verify 的 runbook 自動拿到一筆有效性成功。這個預設該反過來。

## 這裡的快照

保留七份 store 快照，都是文章引用到的那幾次：

| 檔案 | 是什麼 |
| --- | --- |
| `snapshot-before-a-20260816T051342Z.db` | 任何演習發生之前 |
| `snapshot-before-a-20260816T053302Z.db` / `after-…T053558Z.db` | settle window 誤判那次（第一次 `execute success`，然後被自己回滾） |
| `snapshot-before-a-20260816T055519Z.db` / `after-…T060000Z.db` | 第一次成功：`verify pass (value 0)` |
| `snapshot-before-b-20260816T061515Z.db` / `after-…T062002Z.db` | 劇本 b：`verify fail (6.77)` → 自動回滾 |

其他回合的快照被 `.gitignore` 擋掉了。一次演習大約 400KB，而同一個坑重跑五次不是五個發現。

用法：

```bash
sqlite3 snapshot-after-a-20260816T060000Z.db \
  "SELECT ts, action, success, drill FROM executions ORDER BY id"
```
