# Day10 — 命名漂移：用 Rego policy 把它攔下來

對應文章：Day10（2026 鐵人賽《AIOps with OpenTelemetry》）

不動 demo stack。這裡是一份**獨立的最小 registry**，刻意保留 Day1 那個命名漂移（`userId` / `user_id` 並存），外加幾個常見的命名壞味道，用來示範 naming policy 怎麼把它們攔下來。跟 `demo-services` 的正式 registry（`../day06/weaver/`）無關。

```
day10/
  registry/
    manifest.yaml
    model/drift.yaml     # userId / user_id / status / biz.order.id
  policies/
    naming.rego          # 三條規則：camelCase / 撞名 / 缺 namespace
```

## 跑法

```bash
cd day10

# 基準：不帶 policy，內建規則對 userId 完全沒意見
weaver registry check -r registry
weaver registry stats -r registry        #   - 2 groups（不是 0，見 Day7 的假綠燈）

# 帶上三條 naming policy
weaver registry check -r registry -p policies

# Finding 的完整結構
weaver registry check -r registry -p policies --diagnostic-format json

# 確認規則真的被執行過
weaver registry check -r registry -p policies --display-policy-coverage
```

## 真實輸出

不帶 policy：乾淨通過。weaver 的內建規則不檢查命名風格——`userId` 有 `brief`、有 `stability`、型別合法，該有的都有。

帶上 policy：9 個違規，離開碼 1。

```
✔ All `after_resolution` policies checked (9 violations found)

  - id=missing_namespace,     group=registry.order,     attr=status
  - id=missing_namespace,     group=span.order.create,  attr=status
  - id=camel_case_attribute,  group=registry.order,     attr=userId
  - id=missing_namespace,     group=registry.order,     attr=userId
  - id=camel_case_attribute,  group=span.order.create,  attr=userId
  - id=missing_namespace,     group=span.order.create,  attr=userId
  - id=duplicate_concept,     group=(registry-wide),    attr=userId <-> user_id
  - id=missing_namespace,     group=registry.order,     attr=user_id
  - id=missing_namespace,     group=span.order.create,  attr=user_id
```

四個 attribute 裡只有 `biz.order.id` 完全乾淨。

同一個 `userId` 被 `camel_case_attribute` 報兩次是預期行為——Rego 看到的是 resolved schema，`ref` 已經展開，那個 attribute 真的同時存在於定義它的 `registry.order` 跟引用它的 `span.order.create` 裡。這個數字剛好是「改名要動幾個地方」的影響範圍。

## 三個實測出來的行為（weaver 0.24.1，文件沒寫）

### 1. `level` 寫了沒用，`registry check` 只有一種嚴重度

文件裡那套 `information` / `improvement` / `violation` 三級嚴重度，**在 `registry check` 的 policy 上不存在**：

- violation 物件裡寫 `"level": "improvement"` → 被忽略，輸出仍是 `Level: violation`（三種值都試過）
- 改用規則名稱分級（除了 `deny` 再定義 `violation` / `improvement` / `information` 三組規則）→ **只有 `deny` 會被收集**，其他三個一個 Finding 都不產生

三級嚴重度屬於 `live-check` 的 advice 系統（`weaver registry live-check --advice-policies`），也是 `signal_type` / `signal_name` 會被填上的地方；check 階段這兩個欄位恆為 `null`。

要在 check 階段分級，只能拆成兩個資料夾跑兩次，一次的離開碼進 CI 硬擋，另一次只印給人看。

### 2. `type` 只能是 `semconv_attribute`

寫成別的值，**整份 policy 檔會被拒絕**（不是那一條規則失效），錯誤訊息還會誤導：

```
  × Invalid policy file 'registry', error: Violation evaluation error:
  │ invalid type: map, expected A policy violation)
  help: Check the policy file for syntax errors.
```

語法沒有錯，錯的是字串值；而且 `'registry'` 指的不是 `.rego` 檔名，很難據此定位。

| `type` 的值 | 結果 |
|---|---|
| `semconv_attribute` | ✅ 唯一合法 |
| `semconv_metric` / `semconv_span` / `semconv_event` | ❌ 整份被拒絕 |
| `semconv_group` / `semconv_registry` / 任何自訂字串 | ❌ 整份被拒絕 |

必填欄位 `id` / `type` / `category` / `group` / `attr` 少一個也是整份被拒絕。多寫的欄位安靜忽略（所以 `level` 寫了沒反應）。

固定形狀：

```rego
{
	"id":       "<你的規則 id，自由命名>",
	"type":     "semconv_attribute",   # 固定
	"category": "<自由分類字串>",
	"group":    "<自由字串，weaver 不驗證它存不存在>",
	"attr":     "<自由字串，weaver 不驗證它存不存在>",
}
```

`group` / `attr` 不被驗證，所以規則二才能塞 `(registry-wide)` 跟 `userId <-> user_id` 這種非 group/attr 的字串——彈性的代價是打錯字不會有人提醒。

### 3. Rego 物件 → Finding 的欄位對應是錯位的

| Rego 裡寫的 | Finding 裡變成 |
|---|---|
| `"type": "semconv_attribute"` | 頂層 **`id`**（不是 `type`）|
| 整個物件 | **`context`** |
| `"id": "missing_namespace"` | `context.id`，以及 `message` 開頭 |

CI 上要抓的是 `context.id`，不是頂層 `id`（後者所有 Finding 都是 `semconv_attribute`）。
