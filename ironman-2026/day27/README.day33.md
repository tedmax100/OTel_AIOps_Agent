# Day33：把開關打開，然後讓每一道門紅一次

前半在真實叢集上按下去，後半是可重複的防護網回歸測試。

## 前半：真實叢集（k3d `demo` namespace）

`ACTIONS_ENABLED=true` 從 2026-06-22 就設著，不是這天才打開的。那 46 天裡叢集的 store 累積了：

```
action_requests: 10 proposed（最舊 2026-06-22，TTL 900s 早就過期，仍顯示為待處理）
                  1 aborted
executions:       0
```

那筆 `aborted` 的稽核軌跡（2026-06-22，第一次也是唯一一次 smoke test）：

```
proposed → approved(nathan-smoke-test) → execute start → precondition ok(checked 2)
→ dry_run ABORT
   blast_radius: demo/payment-service, revision 17→16, replicas 1→1, affected 1 pod(s), singleton
   reason: target is a singleton (single replica) — denied by policy
```

**這條管線第一次遇到真實輸入就紅了，而且紅得正確。** 當時 payment-service 只有一個副本。

今天 payment-service 是兩個副本，所以同一道門不會再擋。發一次真告警、按核准：

```
proposed → approved(day33-live) → execute start → precondition ok(checked 2)
→ dry_run OK
   blast_radius: demo/payment-service, revision 25→24, replicas 2→2, affected 2 pod(s)
   reason: within policy (affected 2 pod(s), ns demo)
→ execute  FAIL  (401) Unauthorized
→ rollback FAIL  UnauthorizedException: (401) Unauthorized
最終狀態 rollback_failed；Deployment 停在 revision 25，未被動過
```

401 的原因：pod 掛的是舊式不會過期的 ServiceAccount token（`iss=kubernetes/serviceaccount`、`exp=None`），而 k3d 叢集中間被重建過，簽章金鑰換了。**token 不是過期，是簽它的那座叢集不在了**，而 46 天內沒有任何地方會說。

修法：刪掉 Secret 重建（annotation `kubernetes.io/service-account.name` 讓 token controller 重新簽），重啟 agent。再跑一次同一個告警：

```
status=aborted
outcome=idempotent: target already acted on for this incident (48e7df7697ac4034)
```

第三次改標籤再發：

```
{"accepted":[],"skipped":[{"fingerprint":"383238a67e692abb","reason":"cooldown"}]}
```

**四道門、三種不同的拒絕、一次都沒有執行成功。**

三個沒改只量出來的問題：

| 問題 | 形狀 |
| --- | --- |
| `rollback_failed` | 同時代表「execute 就失敗、叢集沒動過」（最安全）與「改了但滾不回來」（最危險） |
| `idempotent: already acted on` | 第一次其實 401 失敗、什麼都沒做，冪等紀錄照樣佔用 key，該事故永遠不能重試 |
| 提案上的 `blast_radius` 是 `null` | 影響範圍到執行當下才算，人按核准的時候看不到（Day24 的主張沒走到人眼前） |

## 後半：`regress_guards.py`

跟 `day12/regress.sh` 同構：每條寫死輸入與預期拒絕理由的字串片段，全綠 exit 0，任何一道門放行 exit 1。暫存 SQLite ＋真模組，不需要叢集或 LLM。

```bash
# 從範例 repo 的根目錄跑
python3 ironman-2026/day33/regress_guards.py
python3 ironman-2026/day33/regress_guards.py -v    # 印出每一條
```

| 平面 | 撞什麼 |
| --- | --- |
| governance | 不可逆行動、信心低於下限、approval-gated、overconfidence 超標、50 筆自我標註、50 筆 `inconclusive` 標註、無 grading_mode 的標註 |
| blast radius | 乾跑讀不到（fail-closed）、受保護 namespace、不在白名單、跨 namespace、scale-to-zero、單副本、超過 pod 上限、沒有前一版可回滾 |
| breaker | 連續失敗跳閘、跳閘後不會自己關、只有人工 reset 能關、視窗內執行數觸發全域限流 |

```
22/22 guards behaved as specified
```

**三條 `[control]` 是故意寫成應該放行的**（culprit 標註夠時 AUTO 要通、2 pod 的 demo 回滾要通、全新的 breaker 要通）。沒有它們，把 `evaluate_policy` 改成 `return False, "no"` 也能讓整份清單全綠——一個什麼都拒絕的守門跟一個什麼都不拒絕的守門一樣沒用。

兩條值得單獨看：

- **scale-to-zero 的理由要講對。** 縮到零的目標同時也是單副本，兩條規則都會擋；如果訊息說「因為是單副本」，值班的人會去把副本數設成 1，然後被同一道門用另一個理由再擋一次。`evaluate_policy` 把 scale-to-zero 排在 singleton 前面就是為了這個。
- **熔斷之後不會自己好。** 連續失敗跳閘 → 再檢查仍是開的 → 只有 `breaker.reset()` 會關。會自我復原的熔斷器在 flapping 場景等於沒有。

## 沒做的

- 沒有一次真的成功執行，所以 `execute → verify → settle window → 驗證失敗自動回滾` 的後半仍未被真實輸入走過。
- `rollback_failed` 與 `already acted on` 兩個訊息都沒改。
- 十筆過期提案留著當證據，背景過期沒做。
- `regress_guards.py` 沒進 CI。
- 憑證健康沒有任何檢查，今天的 token 是手動修的。
