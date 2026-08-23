# Day16：把對帳的噪音降下來

改的是 agent 服務自己的原始碼（`aiops-agent/service/app/signals/`），這裡只放重現步驟。

| 檔案 | 改了什麼 |
| --- | --- |
| `signals/reconcile.py` | `TopologyDrift` 多一個 `caller_samples`（每個服務出現在幾筆取樣的 trace 裡）＋ `services_from_trace()` |
| `signals/context.py` | ⚠ 只在「呼叫方真的被跑過」時才給；同一條邊只講一次；DQ 那行交代自己沒涵蓋什麼 |
| `tests/test_reconcile.py` | 四條新斷言（有證據／沒證據／不重複／DQ 註解） |

## 看 before / after

在 `aiops-agent/service/` 底下跑（要有一座在收 trace 的 stack）：

```bash
# 先灌一點流量
(cd ../../demo-services && ./scripts/load.sh 8 60)

uv run python -c "
import asyncio
from app.signals.reconcile import reconcile
from app.signals.context import build_signal_context
d = asyncio.run(reconcile(lookback='now-30m', max_traces=30))
print('unobserved:', [(e.caller, e.callee) for e in d.unobserved_edges])
print('caller_samples:', d.caller_samples)
print()
print(build_signal_context(['api-gateway', 'payment-service']))
"
```

改之前，同一條邊會在兩個服務的區塊各出現一次，而且標題那行說 100%：

```
Topology data-quality (last reconcile, 30 traces): declared/observed agreement 100%.
### api-gateway
- downstream (...): order-service, payment-service (⚠ declared, not seen in recent traces), user-service
### payment-service
- upstream (...): api-gateway (⚠ declared, not seen in recent traces), order-service
```

改之後：

```
Topology data-quality (last reconcile, 30 traces): declared/observed agreement 100%. That score
only grades edges seen in traffic; 1 declared edge(s) were not exercised in this sample and are
marked below.
### api-gateway
- downstream (...): order-service, payment-service (⚠ not seen in 30 sampled traces of api-gateway), user-service
### payment-service
- upstream (...): api-gateway, order-service
```

## 沒有證據的時候

呼叫方本身只出現在少數幾筆 trace 裡，那它沒走的那些邊什麼都不能證明。這種情況 ⚠ 會退成一句沒有警示符號的描述：

```
- downstream (...): payment-service (not exercised in this sample)
```

門檻是 `context.py` 裡的 `_MIN_CALLER_EVIDENCE`，目前是 5。

## 測試

```bash
uv run pytest tests/test_reconcile.py -q
```
