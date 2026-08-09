# Day29：先讀現況（執行／治理平面）

這一天沒有新增功能，只有一支讀現況的工具，以及它修掉的一個盲點。

## `importgraph.py`

Day13 那支的續作。同樣是從 AST 把真實的 import 關係挖出來，差別在兩件事：

1. **補上 `from . import x` 這種寫法。** Day13 的版本只認得 `from .mod import Name`，遇到 `from . import store` 會把 `module=None` 轉成空字串然後把整條邊丟掉。`app/signals/` 沒人用這種寫法，所以那天的圖是對的；`app/` 有 16 處，所以那天的工具指到這裡會多報三個假孤兒（`store`／`breaker`／`execution`）。
2. **`--focus` 過濾。** 20 支模組一次全印太吵，`--focus` 只留下指定的模組加上直接跟它們相鄰的那些。

## 重現

從 o11y-bench 主 repo 的根目錄跑。

先看 Day13 的版本在 `app/` 上會怎麼漏：

```bash
python3 ironman-2026/day13/importgraph.py aiops-agent/service/app
```

```
nothing in this package imports: breaker, execution, main, store
```

修掉之後：

```bash
python3 ironman-2026/day29/importgraph.py aiops-agent/service/app
```

```
nothing in this package imports: main
  main             runnable as a CLI: NO
```

只看執行／治理那六支：

```bash
python3 ironman-2026/day29/importgraph.py aiops-agent/service/app \
  --focus actions,action_requests,governance,breaker,calibration,blast_radius
```

```
module           imports                                   imported by
---------------------------------------------------------------------------------
action_requests* audit, config, governance, store          agent, execution, main
actions        * blast_radius, config                      agent, execution, governance
blast_radius   * config                                    actions, agent, execution
breaker        * config, store                             execution, main
calibration    * config, store                             agent, execution, investigations, main, webhook
governance     * actions, config, store                    action_requests, agent
execution        action_requests, actions, agent, audit, blast_radius, breaker, calibration, config, rubric, runbook, store  main
```

讀法：`governance` 有 `agent` 跟 `action_requests` 兩個 importer，所以提案那條路是活的；`execution` 只有 `main` 一個 importer，所以執行那一段掛在 HTTP endpoint 底下，agent 自己走不過去。

## 當天量到的數字

| 項目 | 值 | 怎麼量的 |
| --- | --- | --- |
| 六支檔案總行數 | 1147 | `wc -l app/{actions,action_requests,governance,breaker,calibration,blast_radius}.py` |
| `test_governance.py` | 12 條 | `grep -c "^def test_"` |
| `test_blast_radius.py` | 9 條 | 同上 |
| 全套測試 | 354 條 | `pytest --collect-only -q`（`test_rubric.py` 因為缺 `respx` 沒收進來） |
| `test_actions.py` | 不存在 | `ls tests/` |
