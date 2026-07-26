# Day8 — 自訂 semconv 與多 registry 分層

對應文章：Day8（2026 鐵人賽《AIOps with OpenTelemetry》）

不動 demo stack。這裡是五份獨立的 registry，示範「從零寫一份 semantic convention」以及「多團隊分層」會撞到什麼。

```
day13/
  base/              第一層：平台團隊的 payments-base（從零寫）
  team/              第二層：checkout-team，dependencies → base。乾淨版
  team-collision/    第二層：同上，但重新定義了 base 已有的 payment.id（型別還不同）
  division/          第二層：commerce-division，dependencies → base
  squad/             第三層：checkout-squad，dependencies → division ＋ base
  policies/
    layering.rego    before_resolution：signal group 不准 inline 定義 attribute
    collision.rego   after_resolution：同一個名字不准有兩種型別
```

## 跑法

**所有指令都從這個 repo 的根目錄跑** —— `registry_path` 是相對於工作目錄的（見陷阱一）。

```bash
weaver registry check -r day13/base
weaver registry check -r day13/team
weaver registry check -r day13/team-collision -p day13/policies   # exit 1
weaver registry check -r day13/squad
weaver registry stats -r day13/team                               # 1 groups
weaver registry stats -r day13/team --include-unreferenced true   # 3 groups
```

| registry | groups | check + policy |
|---|---|---|
| `base` | 2 | ✅ exit 0 |
| `team` | 1 | ✅ exit 0 |
| `team-collision` | 2 | ❌ exit 1（`conflicting_attribute_definition`）|

## 四個實測陷阱（weaver 0.24.1）

### 1. `registry_path` 相對於「你在哪裡跑」，不是相對於 manifest

| `registry_path` | cwd | `-r` | 結果 |
|---|---|---|---|
| `../base` | repo 根 | `day13/team` | ❌ 找不到 |
| `day13/base` | repo 根 | `day13/team` | ✅ |
| `base` | `day13/` | `team` | ✅ |
| `../base` | `day13/` | `team` | ❌ 找不到 |

`manifest.yaml` **不是自足的**——同一份檔案 `cd` 到不同地方跑結果不同。本機好好的、CI 爆掉（或反過來）就是這樣來的。

配上 Day5 那個 `-r .` 不能用的坑，慣例只能是：**路徑寫成相對於 repo 根目錄，所有指令固定從 repo 根目錄跑**。

### 2. 重複定義不是覆寫，是造出一個沒有人用的孤兒

`team-collision` 重新定義了 base 的 `payment.id`（`string` → `int`）：

```
$ weaver registry check -r day13/team-collision
✔ No `after_resolution` policy violation
$ echo $?
0
```

綠燈。但實際 resolved 出來是兩份並存，而所有 `ref` 都解到 base 那份：

```
group=event.checkout.completed      type=string  brief=支付交易識別碼   ← ref 解到這個
group=event.payment.authorized      type=string  brief=支付交易識別碼
group=registry.checkout_override    type=int     brief=團隊版：把它改成整數  ← 孤兒
group=registry.payment              type=string  brief=支付交易識別碼
```

團隊以為改成功了，實際每個 signal 上的 `payment.id` 還是 `string`；而下游（`generate` / `mcp` / `live-check`）看到的是同一個名字兩種型別。**Weaver 沒有「覆寫」這個動作**——要嘛改 base，要嘛在自己 namespace 下開新欄位。

`policies/collision.rego` 就是用來擋這個的。

### 3. 依賴不會遞移

`squad` → `division` → `base`。三份 manifest 都會被載入，但 `ref` 只看得到**直接依賴**：

```
ℹ Found registry manifest: day13/squad/manifest.yaml
ℹ Found registry manifest: day13/division/manifest.yaml
ℹ Found registry manifest: day13/base/manifest.yaml     ← 載入了

  × Attribute reference: payment.id （來自 base，解不到）
exit=1
```

只 ref `commerce.channel`（直接依賴那層）則正常通過。

解法：把實際用到的每一層都列成直接依賴（`squad/manifest.yaml` 現在同時列了 division 跟 base）。

### 4. 但全部列出來，`--include-unreferenced` 會撞重複載入

```
$ weaver registry stats -r day13/squad --include-unreferenced true
  × The attribute id `payment.id` is declared multiple times in the following
  │ groups: ["registry.payment", "registry.payment"]
```

base 被載入兩次（squad 直接列一次、透過 division 一次）。

| 做法 | 一般 `check` | `--include-unreferenced true` |
|---|---|---|
| 只列直接依賴 | ❌ 隔層 `ref` 解不到 | — |
| 所有層都列 | ✅ | ❌ 重複載入硬錯誤 |

兩層以內沒事，三層以上而且有共同祖先就會撞到。

## 兩條 policy

### `layering.rego`（`before_resolution`）

signal group（event/span/metric）不准 inline 定義 attribute，一律要用 `ref`。

支點是 `attr.id`——**只有 `before_resolution` 寫得出來**：它看到的 attribute 保持手寫原樣（inline 的有 `id`、引用的只有 `ref`），`after_resolution` 的 `ref` 已展開、鍵統一是 `name`，分不出誰是 inline。

強制走 ref 之後，同名問題會在 resolve 階段變成硬錯誤，而不是陷阱二那樣安靜並存。

驗證它真的會動（故意在 event group 裡 inline 一個 `checkout.cart_size`）：

```
- Message : id=inline_attribute_in_signal_group, category=layering,
            group=event.checkout.completed, attr=checkout.cart_size
```

### `collision.rego`（`after_resolution`）

同一個 attribute 名字不准有兩種型別。用 comprehension 把散在各 group 的同名 attribute 攤平成型別集合，`count > 1` 就是衝突。

```
- Message : id=conflicting_attribute_definition, category=layering,
            group=(cross-registry), attr=payment.id
```

## coverage 報告的用法

```bash
weaver registry check -r day13/team -p day13/policies --display-policy-coverage
```

跑乾淨的 `team` 時，`collision.rego` 顯示 full coverage，`layering.rego` 會被**逐行列出來**——因為那條規則沒被觸發過。coverage 報告不只告訴你檔案有沒有被執行，還告訴你哪幾行從來沒跑到。
