# Day10：registry 成為 agent 的工具

`weaver registry mcp` 把 registry 開成一個 MCP（Model Context Protocol）server，
讓 LLM 自己去查「這個欄位叫什麼、有哪些值」，而不是把答案寫死在 prompt 裡。

這個資料夾只有一支腳本：`mcp_probe.py`，不接任何 LLM，直接用 stdio JSON-RPC 打
那個 server。用途是把「agent 講錯」跟「registry 教錯」分開。

驗證環境：weaver 0.25.1。用的 registry 是 Day9 的 `base-v2/` 與 `team-orders/`。

## 跑一輪

```bash
python3 ironman-2026/day10/mcp_probe.py             # 完整的一輪
python3 ironman-2026/day10/mcp_probe.py <registry>  # 只列 tool 清單
```

從 repo 根目錄跑。腳本本身沒有相依套件，只用標準函式庫。

## 這一輪會證明什麼

**八個 tool，分三種職責。** `search` / `browse_namespace` 負責發現，`get_attribute`
/ `get_metric` / `get_span` / `get_event` / `get_entity` 負責理解，`live_check`
負責驗證。

**`search` 是關鍵字 AND，不是語意搜尋。** `order` 找得到 `biz.order.id`（score 70），
`訂單識別碼` 也找得到（brief 進了索引，score 40），但 `identifier` 找不到，
`order user` 也找不到，因為兩個詞必須同時出現。

**同一個 deprecated 屬性，兩個入口兩種待遇。** `search` 會把 `deprecated` 整塊帶
出來、分數壓到 7；`browse_namespace` 完全看不出那個 namespace 已經被更名了。

**查不到東西的時候 `isError` 是 `false`**，回的是一句散文
`Attribute '...' not found in registry`。

**分層 registry 預設只看得到自己那層。** `get_span` 拿得到 base 來的四個屬性，
`provenance.source` 還會標出是哪一版；但 `get_attribute("biz.user.id")` 回 not found，
`browse_namespace` 的 `total_attribute_count` 是 1。加 `--include-unreferenced`
之後變成 940（含官方 semconv），代價見 Day8 那個 flag 已被標為 deprecated 的討論。

**`get_span` 要的是 span type，不是 group id。** 傳 `orders.create` 拿得到，
照抄 YAML 裡的 `span.orders.create` 拿到 not found。
