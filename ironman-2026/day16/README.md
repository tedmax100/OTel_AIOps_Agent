# Day16：讓拓撲對帳有資料源

前一天的對帳是手動敲的，而且它只回答「邊對不對」。這一天處理的是前一個問題：**這張圖上該有哪些服務，誰說了算。**

## `topology_watch.py`

同時問 Loki、Prometheus、Tempo「現在有哪些服務」，跟宣告的拓撲比對，並且用離開碼把結果講清楚，好讓它進 cron 或 CI。

```bash
python3 ironman-2026/day16/topology_watch.py \
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
  ! loki did not answer (Connection refused) — treating it as no evidence
  no source answered; cannot tell alignment from silence
exit=2
```

## 離開碼

| 碼 | 意思 | 排程上該怎麼反應 |
| --- | --- | --- |
| 0 | 宣告的服務集合跟活著的一致 | 什麼都不用做 |
| 1 | 有漂移：宣告了但沒人看到，或活著但沒宣告 | 通知擁有那個服務的團隊 |
| 2 | 問不到，所以什麼都不能斷定 | 通知平台團隊，這是監控自己壞了 |

2 跟 1 一定要分開。把「查不到」算成「沒有漂移」，這個排程就變成一個永遠不會響的告警。

## 排程

```cron
*/30 * * * * cd /path/to/repo && python3 ironman-2026/day16/topology_watch.py \
    --topology aiops-agent/service/app/signals/topology.yaml \
    --loki $LOKI_URL --prom $PROM_URL --tempo $TEMPO_URL --lookback 6h \
    >> /var/log/topology_watch.log 2>&1
```

`--lookback` 要比服務最長的閒置週期長。只在月底跑的服務用 6 小時的視窗看，每天都會被報成死掉的。
