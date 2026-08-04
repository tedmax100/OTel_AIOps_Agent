# Day15：拓撲對帳

這一天跑的是 agent 服務裡本來就有的 `app/signals/reconcile.py`，沒有改它。這個資料夾放的是「跑之前該先確認什麼」的那支工具。

## `tempo_probe.py`

對帳報告說「這六條邊都沒觀察到」的時候，有兩種完全不同的真相：圖錯了，或是那段時間根本沒有應用流量。這支工具先把後者排除掉。

```bash
python3 ironman-2026/day15/tempo_probe.py http://localhost:3210 120
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
