# Day10 — `weaver registry mcp`：讓 agent 直接查 registry

對應文章：Day10（2026 鐵人賽《AIOps with OpenTelemetry》）

不動 demo stack。這裡是一支**不需要 LLM** 就能驅動 MCP server 的探針腳本，加兩份 before/after
的 instrumentation 範例。registry 直接用 `day14/base-v2`（Day9 那個改過名、標過 obsoleted 的版本）。

環境：weaver `0.24.1`。

```
day15/
  mcp_probe.py                     spawn weaver registry mcp、走 stdio JSON-RPC、印出原始回應
  run_and_extract.py               真的跑一次 instrumentation，把實際送出的 span 轉成 live-check 樣本
  samples/
    payment_handler_before.py      四行、四種問題：camelCase / obsoleted / 值域大小寫 / 已移除的欄位
    payment_handler_after.py       照 MCP 查到的定義改過的版本（順手把 retry 搬到 span event）
  team-retry/                      第三輪才長出來的 registry：在自己那一層定義 retry.count
```

`run_and_extract.py` 需要 `opentelemetry-api` 跟 `opentelemetry-sdk`（不需要任何 exporter
套件，用的是 SDK 內建的 `InMemorySpanExporter`）。

## 探針怎麼用

**所有指令都從這個 repo 的根目錄跑**（`-r` 的路徑跟 Day8 的 `registry_path` 一樣綁工作目錄）。

只跑握手＋列工具：

```bash
python3 day15/mcp_probe.py day14/base-v2
```

第二個參數是 `tools/call` 的清單（JSON array），會依序送出：

```bash
python3 day15/mcp_probe.py day14/base-v2 '[{"name":"search","arguments":{"query":"payment"}}]'
```

第三個之後的參數原封不動傳給 weaver：

```bash
python3 day15/mcp_probe.py day13/team '[{"name":"get_attribute","arguments":{"key":"payment.outcome"}}]' \
  --include-unreferenced=true
```

## 文章裡每一段的重現指令

八個 tool（不是文件說的三個）：

```bash
python3 day15/mcp_probe.py day14/base-v2 | \
  python3 -c "import sys,json;s=sys.stdin.read().split('=== tools/list')[1];d,_=json.JSONDecoder().raw_decode(s.strip());[print(t['name'],'|',list(t['inputSchema'].get('properties',{}).keys())) for t in d['result']['tools']]"
```

search 是關鍵字 AND，不是語意搜尋（最後兩個回 0 筆）：

```bash
python3 day15/mcp_probe.py day14/base-v2 '[
  {"name":"search","arguments":{"query":"payment"}},
  {"name":"search","arguments":{"query":"交易"}},
  {"name":"search","arguments":{"query":"payment method"}},
  {"name":"search","arguments":{"query":"payment amount"}},
  {"name":"search","arguments":{"query":"how do I record the payment amount"}}]'
```

`browse_namespace` 不標 deprecated、`search` 會標而且降權（score 80 vs 8）：

```bash
python3 day15/mcp_probe.py day14/base-v2 '[
  {"name":"browse_namespace","arguments":{"prefix":"payment"}},
  {"name":"search","arguments":{"query":"payment"}}]'
```

查不到的東西回 `isError: false` 加一句散文：

```bash
python3 day15/mcp_probe.py day14/base-v2 '[
  {"name":"get_attribute","arguments":{"key":"payment.amount"}},
  {"name":"get_metric","arguments":{"name":"payment.duration"}}]'
```

`live_check` 對 before 那四個欄位（五個樣本、三種 level 全出現）：

```bash
python3 day15/mcp_probe.py day14/base-v2 '[{"name":"live_check","arguments":{"output":"findings_only","samples":[
  {"attribute":{"name":"paymentId","type":"string","value":"pay-1001"}},
  {"attribute":{"name":"payment.id","type":"string","value":"pay-1001"}},
  {"attribute":{"name":"payment.transaction_id","type":"string","value":"pay-1001"}},
  {"attribute":{"name":"payment.outcome","type":"string","value":"DECLINED"}},
  {"attribute":{"name":"payment.retry_count","type":"int","value":2}}]}}]'
```

after 那三個欄位（只剩 `not_stable`，所以 `samples_with_findings` 是 3 不是 0）：

```bash
python3 day15/mcp_probe.py day14/base-v2 '[{"name":"live_check","arguments":{"output":"findings_only","samples":[
  {"attribute":{"name":"payment.transaction_id","type":"string","value":"pay-1001"}},
  {"attribute":{"name":"payment.method","type":"string","value":"credit_card"}},
  {"attribute":{"name":"payment.outcome","type":"string","value":"declined"}}]}}]'
```

## 閉環：從真實 span 到 live-check（三輪）

樣本不是手打的，是從 `InMemorySpanExporter` 收到的 span 上抽出來的：

```bash
python3 day15/run_and_extract.py before             # 看真實 span（可讀格式）
python3 day15/run_and_extract.py before --samples   # 轉成 weaver 樣本 JSON
```

第一輪 before：6 個 violation、exit 1。

```bash
python3 day15/run_and_extract.py before --samples \
  | weaver registry live-check -r day14/base-v2 --input-source stdin
echo $?    # 1
```

第二輪 after：只剩 1 個 violation，而且是自己剛加的 `retry.count`——把欄位搬到 span event
上，在 registry 眼裡是新增，不是搬移。手打樣本抓不到這種東西。

```bash
python3 day15/run_and_extract.py after --samples \
  | weaver registry live-check -r day14/base-v2 --input-source stdin
echo $?    # 1
```

第三輪：合規的修法是把 `retry.count` 定義出來（自己那一層、自己的 namespace），不是刪掉
`add_event`。exit 0，但還有 6 條 `improvement`（全部是 `not_stable`，因為整份 registry
都是 development）。

```bash
weaver registry check -r day15/team-retry
python3 day15/run_and_extract.py after --samples \
  | weaver registry live-check -r day15/team-retry --input-source stdin --include-unreferenced=true
echo $?    # 0
```

`live_check` 只認得 attribute——未定義的 attribute 是 `violation`，未定義的 signal 名稱是沉默：

```bash
echo '[{"span":{"name":"totally.unknown.span","kind":"internal","attributes":[
  {"name":"payment.method","type":"string","value":"credit_card"}]}}]' \
  | weaver registry live-check -r day14/base-v2 --input-source stdin
```

## 分層與版本

分層 registry 預設是空的（三個回應互相矛盾），加上 flag 才對，而且 provenance 多出 `source`：

```bash
python3 day15/mcp_probe.py day13/team '[
  {"name":"browse_namespace","arguments":{}},
  {"name":"get_attribute","arguments":{"key":"payment.outcome"}},
  {"name":"search","arguments":{"query":"checkout"}}]'

python3 day15/mcp_probe.py day13/team '[
  {"name":"browse_namespace","arguments":{}},
  {"name":"get_attribute","arguments":{"key":"payment.outcome"}}]' --include-unreferenced=true
```

版本盲點：同一個 query 對 v1／v2 兩份 registry 得到不同答案，而 agent 無從得知自己讀的是哪一版：

```bash
for r in day14/base-v1 day14/base-v2; do
  python3 day15/mcp_probe.py $r '[
    {"name":"get_attribute","arguments":{"key":"payment.retry_count"}},
    {"name":"search","arguments":{"query":"transaction"}}]'
done
```

## 接上真的 coding agent

專案根目錄放一份 `.mcp.json`（平台團隊維護、產品團隊只是取用）：

```json
{
  "mcpServers": {
    "semconv": {
      "command": "weaver",
      "args": ["registry", "mcp", "-r", "day14/base-v2", "--include-unreferenced", "true"]
    }
  }
}
```

配套要寫進 agent 指令（`CLAUDE.md` 或 system prompt）的三條規則，理由見文章的四個坑：

1. 查 semconv 一次只用一到兩個關鍵字，零筆就換詞再試，不要把整句問題丟進 `search`。
2. 挑欄位用 `search`（會標 deprecated、會降權），不要用 `browse_namespace`（不標）。
3. 任何欄位名寫進程式碼之前，必須先出現在某一次 `get_attribute` 的成功回應裡；
   `not found` 就停下來問人，不准自己命名。
