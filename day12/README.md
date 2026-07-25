# Day12 — `live-check`：補上 CI 看不到的那一半

對應文章：Day12（2026 鐵人賽《AIOps with OpenTelemetry》）

不動 demo stack。這裡只有兩份遙測樣本，拿去跟 [`../day06/weaver/registry`](../day06/weaver/) 比對——`registry check` 檢查定義自不自洽，`live-check` 檢查**實際送出去的資料**符不符合那份定義。

```
day12/samples/
  drift.json   # Day1 的現況：flat key + userId/user_id 並存 + 未治理的 metric
  clean.json   # 一字不差照 registry 送
```

## 跑法

```bash
# 從 submodule 根目錄
weaver registry live-check -r day06/weaver/registry --input-source day12/samples/drift.json
weaver registry live-check -r day06/weaver/registry --input-source day12/samples/clean.json
```

不需要把任何服務跑起來——`--input-source` 吃檔案路徑（也吃 `stdin`，預設是 `otlp`）。

## 樣本檔格式（文件沒明講，試出來的）

必須是**陣列**，每個元素用型別當外層的鍵：

```json
[
  {"span": {"name":"POST /api/orders","kind":"server","attributes":[
    {"name":"user_id","value":"u-5"}
  ]}},
  {"metric": {"name":"orders_total","instrument":"counter","unit":"{order}"}}
]
```

寫錯時的錯誤訊息其實很有用：

```
× invalid type: map, expected a sequence at line 1 column 1
      ↑ 忘了包成陣列

× unknown variant `name`, expected one of `attribute`, `span`, `span_event`,
  `span_link`, `resource`, `metric`, `log`
      ↑ 支援的七種樣本型別，直接列在錯誤裡
```

## 真實輸出

`drift.json` → exit **1**（有 violation）；`clean.json` → exit **0**（只有 improvement）。

```
Span POST /api/orders `server`
    user_id = u-5
        - [violation] Attribute 'user_id' does not exist in the registry.
        - [improvement] Attribute key 'user_id' must include a namespace (e.g. '{namespace}.{attribute_key}')
    userId = u-7
        - [violation] Attribute 'userId' does not exist in the registry.
        - [improvement] Attribute key 'userId' must include a namespace
        - [violation] Attribute key 'userId' does not match name formatting rules.

Span span.app.order.create `server`
    biz.user.id = u-5
        - [improvement] Attribute 'biz.user.id' is not stable; stability = development.
    app.outcome = CREATED
        - [information] Enum attribute 'app.outcome' has value 'CREATED' which is not documented.

Metric orders_total `counter`, `{order}`
    - [violation] Metric does not exist in the registry.

Advisories given
  - total: 14
  - advice level:
    - improvement: 7
    - information: 1
    - violation: 6

Registry coverage
  - total seen: 3.77%
```

## 三級嚴重度在這裡才是真的

Day10 找不到的 `information` / `improvement` / `violation`，屬於 live-check 的 advice 系統，不是 `registry check` 的 policy。而且它**決定離開碼**：有 violation → 1，只有 improvement/information → 0。所以 CI 可以要求「不准有 violation」，同時讓 improvement 只當技術債看板。

### 六種內建 advice type

| advice type | 等級 | 意思 |
|---|---|---|
| `missing_attribute` | violation | attribute 不在 registry 裡 |
| `missing_metric` | violation | metric 不在 registry 裡 |
| `invalid_format` | violation | 名字不符命名規則（`userId`）|
| `missing_namespace` | improvement | 名字沒有 namespace |
| `not_stable` | improvement | 用到還是 `development` 的定義 |
| `undefined_enum_variant` | information | enum 送出沒定義過的值（`CREATED`）|

`not_stable` 對**完全正確**的資料也會叫——因為 day06 那份 registry 100% 都是 `development`。它是技術債提醒，不是錯誤。

`missing_namespace` 跟 `invalid_format` 是 Day10 手寫規則的內建版，差別在守的時間點：Day10 守 PR 階段的**定義**，這裡守 runtime 的**實際資料**。

## 兩個坑

### 1. 預設綁 `0.0.0.0:4317`，會吃到別人的遙測

```
$ ss -tlnp | grep weaver
LISTEN 0 128 0.0.0.0:4317 0.0.0.0:*  users:(("weaver",...))
LISTEN 0 128 0.0.0.0:4320 0.0.0.0:*  users:(("weaver",...))
```

4317 是 OTLP/gRPC 標準 port，本機所有 OTel 工具的預設值。實際踩過：live-check 收到了同時在跑的 coding agent 自己的遙測，裡面帶 `user.email` 這種 PII，就這樣進了報告。污染統計、外洩風險，而且 live-check 不會告訴你這批資料來自別的程序。

一律指定 port 並綁 localhost：

```bash
weaver registry live-check -r day06/weaver/registry \
  --otlp-grpc-address 127.0.0.1 --otlp-grpc-port 14317 --admin-port 14320
```

（`--admin-port` 預設 4320，`/stop` 掛在上面；預設不活動 10 秒自動停。）

### 2. `--advice-policies` 是覆蓋，不是疊加

help 寫的是 "Set this to **override** the default policies"。實測給一個沒有有效規則的目錄，前後對照：

```
# 不給 --advice-policies          # 給了一個空的
invalid_format: 1                  （消失）
missing_attribute: 4               missing_attribute: 4
missing_metric: 1                  missing_metric: 1
missing_namespace: 4               （消失）
not_stable: 3                      not_stable: 3
undefined_enum_variant: 1          undefined_enum_variant: 1
```

五條 advice 不見，沒有任何警告。

順帶揭露內建 advice 分成兩層：`missing_attribute` / `missing_metric` / `not_stable` / `undefined_enum_variant` 寫死在 weaver 裡，`--advice-policies` 動不到；`invalid_format` / `missing_namespace` 是 Rego 實作的預設 advice policy，會被整個換掉。

**尚未解出**：怎麼正確寫一條自訂 advice policy。試過的 package 名稱（`live_check_advice`、`advice`、`livecheck`、`after_resolution`…）都沒讓自訂規則生效。
