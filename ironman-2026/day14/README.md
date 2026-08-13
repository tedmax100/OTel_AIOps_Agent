# Day14：拓撲對帳

這一天跑的是 agent 服務裡本來就有的 `app/signals/reconcile.py`，沒有改它。這個資料夾放的是「跑之前該先確認什麼」的那支工具。

## `tempo_probe.py`

對帳報告說「這六條邊都沒觀察到」的時候，有兩種完全不同的真相：圖錯了，或是那段時間根本沒有應用流量。這支工具先把後者排除掉。

```bash
python3 ironman-2026/day14/tempo_probe.py http://localhost:3210 120
```

它印三件事：這個位址上的 Tempo 到底是哪一版（避免打到另一座）、視窗內有幾筆 trace、以及其中有幾筆撐得過 `{ trace:duration > 5ms }` 這個探針過濾器。

沒有應用流量的時候：

```
http://localhost:3210 → Tempo 2.6.0 (rev e85bbc57d)
  last 120s: 214 traces
    slowest seen           : 1ms
    survives the >5ms filter: 0
    ⚠ reconcile would sample 0 traces here and report every declared
      edge as unobserved. That is 'no traffic', not 'the graph is wrong'.
```

灌了流量之後：

```
http://localhost:3210 → Tempo 2.6.0 (rev e85bbc57d)
  last 120s: ≥500 traces
    slowest seen           : 28ms
    survives the >5ms filter: 467
    (limit=500 hit — counts are floors; shorten the window to compare them)
```

## 重現文章裡的對帳結果

被跑的模組是 agent 服務自己的原始碼（`aiops-agent/service/app/signals/`），不在這個 repo 裡。下面在 `aiops-agent/service/` 底下跑，`3210` 換成你的 Tempo：

```bash
# 先灌一點流量
(cd ../../demo-services && ./scripts/load.sh 8 70)

# load.sh 不會走 api-gateway → payment-service 這條邊（它的付款都經由
# order-service 進去），所以要單獨打它，否則那條邊在每個取樣數下都是
# unobserved，也就看不到文章講的那個差異。api-gateway 沒有對外埠時先轉一個：
#   kubectl -n demo port-forward svc/api-gateway 8010:8000
for i in $(seq 1 15); do
  curl -sS -o /dev/null -X POST http://localhost:8010/api/payments \
    -H 'Content-Type: application/json' -d '{"order_id":"probe-'$i'","amount":101}'
done

# 對帳，並掃不同的取樣數
for n in 50 100 300; do
  uv run python -c "
import asyncio
from app.config import settings
settings.tempo_url='http://localhost:3210'
from app.signals.reconcile import reconcile
d=asyncio.run(reconcile(lookback='now-10m', max_traces=$n))
print(f'max_traces=$n sampled={d.traces_sampled} observed={d.observed_count} dq={d.dq_score}'
      f' unobserved={[(e.caller,e.callee) for e in d.unobserved_edges]}')
"
done
```

`max_traces` 的預設值是 50，而 50 跟 300 會給出不一樣的答案。文章講的就是這件事。

**這幾個數字不是常數。** 那條邊要在哪個取樣數才被看到，取決於它在那個視窗裡佔多少
比例：結帳流量越密，門檻越高。實測過一次連 300 都還是 `unobserved`，得再往上調。
所以照著跑而數字對不上是正常的，要看的是「同一份程式碼、同一張圖，答案會隨取樣數
改變」這件事本身。

---

## 讓拓撲對帳有資料源

前一天的對帳是手動敲的，而且它只回答「邊對不對」。這一天處理的是前一個問題：**這張圖上該有哪些服務，誰說了算。**

## `topology_watch.py`

同時問 Loki、Prometheus、Tempo「現在有哪些服務」，跟宣告的拓撲比對，並且用離開碼把結果講清楚，好讓它進 cron 或 CI。

```bash
python3 ironman-2026/day14/topology_watch.py \
    --topology aiops-agent/service/app/signals/topology.yaml \
    --loki  http://localhost:3100 \
    --prom  http://localhost:9090 \
    --tempo http://localhost:3200 \
    --lookback 6h
```

三個資料源都問：

```
# topology watch — declared 5, lookback 6h
  loki        sees  5: api-gateway, order-service, payment-service, user-service, webapp
  prometheus  sees  6: aiops-agent, api-gateway, order-service, payment-service, user-service, webapp
  tempo       sees  6: aiops-agent, api-gateway, order-service, payment-service, user-service, webapp
  ~ 'aiops-agent' is missing from loki but present in others
  ✗ live 'aiops-agent' is not declared (seen by prometheus, tempo)
exit=1
```

只問 Loki（也就是 `list_service_names()` 現在的行為）：

```
# topology watch — declared 5, lookback 6h
  loki        sees  5: api-gateway, order-service, payment-service, user-service, webapp
  ✓ declared set matches the live set (5 services)
exit=0
```

同一個叢集、同一個時間、同一份拓撲，一個說有漂移，一個說完全對齊。

沒有任何資料源答得出來的時候：

```
  ! loki did not answer (<urlopen error [Errno 111] Connection refused>) — treating it as no evidence
# topology watch — declared 5, lookback 6h
  no source answered; cannot tell alignment from silence
exit=2
```

（那行 `!` 印在標頭前面，因為它是查詢當下就寫出去的，不是最後才彙整的。）

## 離開碼

| 碼 | 意思 | 排程上該怎麼反應 |
| --- | --- | --- |
| 0 | 宣告的服務集合跟活著的一致 | 什麼都不用做 |
| 1 | 有漂移：宣告了但沒人看到，或活著但沒宣告 | 通知擁有那個服務的團隊 |
| 2 | 問不到，所以什麼都不能斷定 | 通知平台團隊，這是監控自己壞了 |

2 跟 1 一定要分開。把「查不到」算成「沒有漂移」，這個排程就變成一個永遠不會響的告警。

## 排程

```cron
*/30 * * * * cd /path/to/repo && python3 ironman-2026/day14/topology_watch.py \
    --topology aiops-agent/service/app/signals/topology.yaml \
    --loki $LOKI_URL --prom $PROM_URL --tempo $TEMPO_URL --lookback 6h \
    >> /var/log/topology_watch.log 2>&1
```

`--lookback` 要比服務最長的閒置週期長。只在月底跑的服務用 6 小時的視窗看，每天都會被報成死掉的。
