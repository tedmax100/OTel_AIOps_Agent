# Day14：讀現況

這一天沒有新增功能，只有一支用來讀現況的工具。

## `importgraph.py`

把一個 package 的真實 import 關係從 AST 裡挖出來，印成「誰 import 誰、誰被誰 import、以及沒有任何人 import 的是哪幾個」。

用 AST 而不是 grep，是因為函式內部的 `import`（延遲載入、`__main__` 底下的）也是一條真的邊，`grep "^from"` 會漏掉。這一天最重要的那個發現就藏在這種邊裡。

```bash
# 從 o11y-bench 主 repo 的根目錄跑
python3 ironman-2026/day14/importgraph.py aiops-agent/service/app/signals
```

輸出：

```
# aiops-agent/service/app/signals  (8 modules)

module     imports                             imported by
---------------------------------------------------------------------
compile    contract, topology                  —
context    contract, reconcile, topology       —
contract   —                                   compile, context, health, weaver
dq         reconcile                           —
health     contract, topology                  —
reconcile  topology                            context, dq
topology   —                                   compile, context, health, reconcile
weaver     contract                            —

nothing in this package imports: compile, context, dq, health, weaver
  compile    runnable as a CLI: yes
  context    runnable as a CLI: NO
  dq         runnable as a CLI: NO
  health     runnable as a CLI: NO
  weaver     runnable as a CLI: yes
```

它對任何 package 都能跑，不限這一個。

## 文章裡另外三段輸出怎麼重現

被讀的那個模組是 agent 服務自己的原始碼（`aiops-agent/service/app/signals/`），不在這個 repo 裡。下面的指令都在 `aiops-agent/service/` 底下跑：

```bash
# 契約引用的 metric 有沒有全部在 Weaver registry 裡宣告過
uv run python -m app.signals.weaver

# 注入給 agent 的那段 Signal context 長什麼樣（純函式，不需要 live stack）
uv run python -c "from app.signals.context import build_signal_context; \
    print(build_signal_context(['order-service']))"

# Data-Quality 判定（沒跑過 reconcile 時的預設狀態）
uv run python -c "from app.signals.dq import dq_verdict; print(dq_verdict())"
```
