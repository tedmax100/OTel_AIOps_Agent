# Day15：把 registry 接進 Signal Plane

這一天改的是 agent 服務自己的原始碼（`aiops-agent/service/app/signals/`），不在這個 repo 裡，所以這裡只放重現步驟。動到的東西：

| 檔案 | 改了什麼 |
| --- | --- |
| `signals/weaver.py` | 多一個 `alignment_report()`，`__main__` 把結果寫成 `schema_alignment.json` |
| `signals/schema_alignment.json` | 新的產物，要 commit 進版控 |
| `signals/dq.py` | `dq_verdict()` 讀那份產物，把 schema 對齊納入判定 |
| `tests/test_dq.py` | 四條新斷言，蓋住 schema 那個維度 |
| `.github/workflows/ci.yml` | Weaver job 多一步：重生產物並比對 diff |

## 產生對齊產物

在 `aiops-agent/service/` 底下跑：

```bash
uv run python -m app.signals.weaver
```

```
weaver registry declares 6 Prom metrics; checked 5 contracts
✓ all contract SLIs reference metrics declared in the Weaver registry
  wrote schema_alignment.json
```

產物本身是決定性的，沒有時間戳，這樣 CI 才能重生一次然後比對：

```json
{
  "checked": 5,
  "declared_metrics": 6,
  "undeclared": [],
  "note": "5 contracts checked against 6 registry metrics"
}
```

## 看 DQ 判定

```bash
uv run python -c "
import asyncio
from app.signals.reconcile import reconcile
from app.signals.dq import dq_verdict
print(dq_verdict())          # 還沒對帳 → unproven
asyncio.run(reconcile())
print(dq_verdict())          # 兩個維度都過 → proven_good True
"
```

## 重現那個 fail-open 陷阱

registry 讀不到的時候，`weaver_prom_metric_names()` 回一個空集合。直接拿它去比對，每一條 SLI 都會被判成「registry 沒宣告」：

```bash
uv run python -c "
from pathlib import Path
from app.signals.weaver import weaver_prom_metric_names
from app.signals.contract import get_contracts, validate_against_weaver
empty = weaver_prom_metric_names(Path('/nonexistent/metrics.yaml'))
for c in get_contracts().contracts:
    for w in validate_against_weaver(c, empty): print(' ', w)
"
```

六筆假的違規。`alignment_report()` 就是為了這件事才把「讀不到」記成 `checked: 0` 而不是記成違規。

## 測試

```bash
uv run pytest tests/test_dq.py -q
```
