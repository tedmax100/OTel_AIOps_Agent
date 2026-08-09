# Day30：狀態機撞牆測試

沒有改產品程式碼，只有一支探測腳本，走現有 9 條單元測試沒走過的路徑。

## `probe_lifecycle.py`

用一個暫存 SQLite 檔加真的 `app.action_requests` / `app.store` 模組，沒有 mock、沒有叢集、沒有 LLM。

```bash
# 從 o11y-bench 主 repo 的根目錄跑
python3 ironman-2026/day30/probe_lifecycle.py
```

四個探測：

| # | 撞什麼 | 現有測試為什麼沒蓋到 |
| --- | --- | --- |
| 1 | 8 個執行緒同時 `approve()` | 現有的 double-approve 測試是單執行緒依序呼叫兩次 |
| 2 | 同樣過期的請求，`approve()` vs `reject()` | 只測過 approve 那一側 |
| 3 | 過期但沒有人碰的請求會出現在哪 | 沒有測試看過 `list_requests()` 的內容 |
| 4 | `executing` 中途 pod 被砍 | 沒有測試進到 `executing` 之後又離開 |

## 實際輸出

```
[1] 8 threads approve the same request simultaneously
    approve() returned a request 1 time(s) out of 8
    after                  status=approved   actor=human-2 outcome=''

[2] the same stale request: approve() vs reject()
    approve() -> None
    approved path          status=expired    actor=None outcome='approval TTL elapsed before action'
    reject()  -> a request
    rejected path          status=rejected   actor=human outcome=''

[3] a stale request nobody touches
    listed under status=proposed: 1
    stored                 status=proposed   actor=None outcome=''

[4] the pod dies between claim and outcome
    executor claimed it: True
    after the crash        status=executing  actor=human outcome=''
    a restarted executor re-claims it: False
    approve() on it now: None
```

## 結論

1. **CAS 在真的併發下是對的。** 8 個執行緒恰好一個贏，連跑三次贏家分別是 `human-2`／`human-1`／`human-0`，數量永遠是 1。
2. **`reject()` 沒有 TTL 檢查，`approve()` 有。** 同樣過期的兩列，一列變成 `expired` 並留下原因，另一列變成 `rejected` 並記上那個人。稽核軌跡上這是兩個不同的故事。
3. **過期是被動的。** `_expire_if_stale()` 全專案只有 `approve()` 一個呼叫點，所以沒人按的提案會用 `proposed` 的身分留在清單上。
4. **`executing` 沒有回收機制。** 認領之後 pod 死掉，那列永遠停在 `executing`：executor 找 `approved` 找不到它，`approve()` 找 `proposed` 也找不到它。

三個洞今天都只量不補。腳本本身沒有斷言，不是測試。

---

## 治理平面的授權判斷

沒有改產品程式碼，只有一支探測腳本，把註冊表裡**真的存在**的行動丟進 `governance.decide()` 掃一遍。

## `probe_governance.py`

用暫存 SQLite 檔加真的 `app.governance` / `app.actions` / `app.calibration` 模組，沒有 mock、沒有叢集、沒有 LLM。

```bash
# 從 o11y-bench 主 repo 的根目錄跑
python3 ironman-2026/day30/probe_governance.py
```

四個探測：

| # | 撞什麼 | 現有測試為什麼沒蓋到 |
| --- | --- | --- |
| 1 | 真實註冊表的行動 × 四個信心值 | 每條測試都自建 `ActionSpec(requires_approval=False)`，那個形狀註冊表裡不存在 |
| 2 | 同樣的行動，`requires_approval` 翻掉 | 沒有測試對照過這個旗標對結果的影響 |
| 3 | 25 筆自我標註 vs 20 筆 grader 標註 | `test_governance.py` 用 `governance_min_human_labeled_runs=0` 繞過這道門 |
| 4 | 真實 store 現在的判斷 | 單元測試一律給合成的 calib dict |

## 實際輸出

`[4]` 這一段是 Day31 把 eval 標註搬進來**之前**跑的。之後再跑會變成 `non-self=35 / calibration ok`，但兩個行動的 autonomy 仍是 `propose`。

```
[0] registered actions (2)
    k8s.rollout_undo   reversible=True requires_approval=True impl=wired
    k8s.scale          reversible=True requires_approval=True impl=wired

[baseline] 25 grader labels, overconfidence -0.1 — every calibration gate satisfied

[1] the real registry
    k8s.rollout_undo   0.3->escalate 0.6->propose  0.9->propose  1.0->propose
    k8s.scale          0.3->escalate 0.6->propose  0.9->propose  1.0->propose

[2] the same actions with requires_approval flipped off
    k8s.rollout_undo   0.3->escalate 0.6->propose  0.9->auto     1.0->auto
    k8s.scale          0.3->escalate 0.6->propose  0.9->auto     1.0->auto

[3] self-produced labels vs grader labels, at confidence 0.9
    after 25 x remediation-verified  labeled=25  non-self=0
        -> propose  insufficient human/grader labels (0 < 20); self-produced labels cannot unlock AUTO
    after 20 x grader                labeled=45  non-self=20
        -> auto     calibration ok (overconfidence -0.1, 45 runs)

[4] the real store, right now
    recorded=0 labeled=0 non-self=0 overconfidence=None
    k8s.rollout_undo   -> propose  high confidence but action is approval-gated
                          calibration unproven (0 labeled run(s) < 20); autonomy withheld
    k8s.scale          -> propose  high confidence but action is approval-gated
                          calibration unproven (0 labeled run(s) < 20); autonomy withheld
```

## 結論

1. **AUTO 在真實註冊表上到不了，而擋住它的不是校準，是 `requires_approval`。** 那格判斷排在校準之前，所以 `_calibration_verdict()` 的結果每次都算、每次都被寫進 `Decision.calibration_note`，但從來沒有改變過任何一次結果。[2] 只翻一個布林值 AUTO 就出現，證明後面那段是活的。
2. **「自己說自己修好了」不能解鎖自主權，這道門是真的裝好的。** 25 筆 `remediation-verified` 過得了第一道門（總數 ≥ 20），被第二道門擋下；補 20 筆 grader 標註才變 AUTO。ARE §6.2 constraint 1 最字面的一行程式碼。
3. **現在按下去的答案是 PROPOSE，三道鎖同時鎖著**（`requires_approval` / 校準 0 筆 / `actions_enabled=False`），而 `reason` 與 `calibration_note` 講的是兩個不同的原因。
4. **過度自信只檢查正的一側。** `if overconf > max` 讓負值（低估自己）一路通行，baseline 那個 `-0.1` 就是這樣過的。

沒有補任何一個洞。腳本沒有斷言，不是測試。真正該補的是一條「拿註冊表裡真的存在的行動走 AUTO 那條路」的測試。
