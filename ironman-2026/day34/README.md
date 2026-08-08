# Day34：狀態機撞牆測試

沒有改產品程式碼，只有一支探測腳本，走現有 9 條單元測試沒走過的路徑。

## `probe_lifecycle.py`

用一個暫存 SQLite 檔加真的 `app.action_requests` / `app.store` 模組，沒有 mock、沒有叢集、沒有 LLM。

```bash
# 從 o11y-bench 主 repo 的根目錄跑
python3 ironman-2026/day34/probe_lifecycle.py
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
