# Day17：順著圖走的異常偵測，跟它走不到的地方

改的是 agent 服務自己的原始碼（`aiops-agent/service/app/signals/health.py`），這裡放對照用的腳本跟重現步驟。

| 檔案 | 內容 |
| --- | --- |
| `flat_scan.py` | 平鋪掃描的對照組：掃 Prometheus 現有的每一條 series，跟 baseline 比，超過門檻就算異常候選 |
| `signals/health.py` | 沒有 SLI 的服務不再被靜靜丟掉，回 `verdict="unjudgeable"`；三句會從「查不到」推出「沒問題」的結論文案都補上適用範圍 |
| `tests/test_health.py` | 兩條新斷言（服務不被丟掉／根因結論不順手宣告判不了的下游是健康的），三條既有斷言改掉（它們原本釘的是舊的錯誤行為） |

## 前置

要有一座在收指標的 stack，以及 port-forward：

```bash
kubectl -n demo port-forward svc/prometheus 9090:9090 &
kubectl -n demo port-forward svc/webapp 8002:8000 &
kubectl -n demo port-forward svc/payment-service 8001:8000 &
(cd demo-services && ./scripts/load.sh 8 3600 &)
```

指標要跑滿 `rate(...[5m])` 的視窗才有意義，灌完流量等個五到十分鐘再開始。

## 平鋪掃描（對照組）

沒有任何事故的穩定狀態下：

```console
$ python3 flat_scan.py --baseline 10m --min-rel 0.5
metric families: 34  series sampled: 221
anomaly candidates (rel change >= 50%): 20
```

二十個候選，全部是誤報。同一批資料把門檻拉十倍：

```
min-rel 0.5 -> 20
min-rel 1.0 -> 18
min-rel 2.0 -> 18
min-rel 5.0 -> 8
```

剩下的八個 baseline 是零、相對變化是 `inf%`，多高的門檻都擋不住。

## 製造事故

```bash
kubectl -n demo patch cm payment-flags --type merge \
  -p '{"data":{"flags.json":"{\"payment_use_new_validator\": true}\n"}}'
kubectl -n demo rollout restart deploy payment-service
kubectl -n demo rollout status deploy payment-service
```

兩個坑：

1. **flag 是啟動時讀的**，不 restart 完全沒效果，而且不會有任何錯誤訊息。
2. **order-service 的金額永遠是偶數分**（價格 `100 * i`），照原本的流量跑一筆都不會被拒絕。要直接打 payment：

```bash
while true; do
  curl -sS -o /dev/null -X POST localhost:8001/charge \
    -H 'content-type: application/json' \
    -d "{\"order_id\":\"o-$RANDOM\",\"user_id\":\"u-1\",\"amount_cents\":$(( (RANDOM % 500) * 2 + 1 ))}"
  sleep 0.15
done
```

幾分鐘後確認：

```bash
curl -sG localhost:9090/api/v1/query --data-urlencode \
  'query=sum by (status) (rate(payment_charges_total[5m]))'
```

## 順著圖走

在 `aiops-agent/service/` 底下跑。`SIGNAL_HEALTH_BASELINE_OFFSET` 預設是 `1h`，如果 stack 才剛起來，baseline 會落在沒有資料的區間，調短一點：

```bash
SIGNAL_HEALTH_BASELINE_OFFSET=30m uv run python -c "
import asyncio
from app.signals.health import evaluate_dependency_health
for s in (['payment-service'], ['order-service'], ['api-gateway'], ['webapp']):
    print(asyncio.run(evaluate_dependency_health(s))); print()
"
```

四個服務分別會走到四條不同的結論路徑：

| 服務 | 走到哪一支 |
| --- | --- |
| payment-service | 自己壞、沒有下游 → `LIKELY ROOT CAUSE` |
| order-service | 自己好、下游壞、但歸因量沒漲 → `only topologically adjacent` |
| api-gateway | 沒有 SLI → `CANNOT be judged`（改之前：被丟掉，然後結論宣告它 healthy） |
| webapp | 自己跟唯一的下游都沒有 SLI（改之前：整個函式回 `None`） |

## 改之前 / 改之後

api-gateway，改之前：

```
- downstream payment-service: error 57.5% — UNHEALTHY (breaches objective declined_rate < 1%)
→ A downstream dependency is unhealthy (payment-service), but the service(s) under
  investigation show HEALTHY SLIs themselves. ...
```

`this service api-gateway` 那一行不存在，然後結論說它 healthy。

改之後：

```
- this service api-gateway: no error SLI declared — CANNOT be judged from metrics
  (a missing declaration, not a healthy verdict; judge it from its logs)
...
→ A downstream dependency is unhealthy (payment-service), but the service(s) under
  investigation could NOT be judged from metrics. ... NOTE: api-gateway has no error
  SLI of its own, so this verdict says nothing about it ...
```

## 覆蓋率

拓撲上五個節點，這個分析實際判得動幾個：

```bash
uv run python -c "
from app.signals.topology import get_topology
from app.signals.health import _health_sli
for n in get_topology().names():
    s = _health_sli(n)
    print(f'{n:16s} -> {s.kind if s else \"NO SLI — invisible to the walk\"}')
"
```

```
api-gateway      -> NO SLI — invisible to the walk
order-service    -> error
payment-service  -> error
user-service     -> throughput
webapp           -> NO SLI — invisible to the walk
```

## 量測限制：payment 的百分比會失真

payment-service 跑兩個 replica，但它的 metric 沒有任何 pod / instance 維度的 label，
兩個獨立累加的 counter 寫進同一條 series。`rate()` 把每次交錯當成 counter reset，
於是會憑空生出流量（實測過：零流量時 `rate(payment_charges_total[2m])` 報 40.86 rps）。

所以上面那些 declined rate 的百分比要打折看。拿 Loki 的事件計數對照（log 逐行，不受影響）：

| 時間 (UTC) | Loki | Prometheus |
| --- | --- | --- |
| 15:25 | 77.2% | 60.2% |
| 15:30 | 76.9% | 62.6% |
| 15:35 | 36.5% | 80.2% |

```bash
TS=1785943847   # 事故視窗內的任一時間點
curl -sG localhost:3100/loki/api/v1/query --data-urlencode \
  'query=sum(count_over_time({service_name="payment-service"} | event="payment.declined" [5m]))' \
  -d "time=${TS}000000000"
```

定性的結論不受影響（1% 的目標被 36% 跟 77% 打穿的程度一樣），受影響的是數字本身。
要修得讓 collector 保留 `service.instance.id`，代價是 series 數量乘上 replica 數。

## 收拾

```bash
kubectl -n demo patch cm payment-flags --type merge \
  -p '{"data":{"flags.json":"{\"payment_use_new_validator\": false}\n"}}'
kubectl -n demo rollout restart deploy payment-service
```

## 測試

```bash
uv run pytest tests/test_health.py -q
```
