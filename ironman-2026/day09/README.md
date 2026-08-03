# Day9：breaking change 與三層驗證

同一份 base registry 的兩個版本，中間夾著五種變更，用來看 `registry diff` 報得出
哪幾種、報不出哪幾種，以及怎麼用 `comparison_after_resolution` 把漏掉的補回來。

驗證環境：weaver 0.25.1、semantic-conventions v1.43.0。

```
day09/
├── base-v1/          # = Day8 的 base，多一個 biz.cart.id
├── base-v2/          # 五種變更都在這裡
├── team-orders/      # 下游團隊，依賴 base-v2
├── policies/         # comparison_after_resolution 的三條規則
├── future-demo/      # --future 的示範（舊式 deprecated 寫法）
└── live-check/       # 服務還在送舊值的樣本
```

v1 → v2 的五種變更：

| # | 變更 | `registry diff` |
| --- | --- | --- |
| 1 | 新增 `biz.tenant.id` | ✅ Added |
| 2 | `biz.cart.id` 更名為 `biz.basket.id` | ✅ Renamed |
| 3 | `biz.order.id` 型別 `string` → `int` | ❌ 靜音 |
| 4 | `app.outcome` 移除 enum member `gateway_error` | ❌ 靜音 |
| 5 | `biz.user.id` 的 `brief` 改成另一個意思 | ❌ 靜音 |

以下指令都從這個 repo 的根目錄跑。

## 1. 兩個版本各自都是合法的

```bash
weaver registry check -r ironman-2026/day09/base-v1   # 0
weaver registry check -r ironman-2026/day09/base-v2   # 0
```

## 2. diff 只看得到前兩種

```bash
weaver registry diff -r ironman-2026/day09/base-v2 \
  --baseline-registry ironman-2026/day09/base-v1
echo $?   # 0，diff 從來不會因為變更而失敗
```

`--format json` 可以確認那不是渲染問題，資料模型裡就只有三筆變更。

## 3. 用 policy 把三個靜音的補回來

`comparison_after_resolution` 這個 package 只有在 `check` 帶 `--baseline-registry`
時才會跑。`input` 是新版，`data` 是 baseline。

```bash
weaver registry check -r ironman-2026/day09/base-v2 \
  --baseline-registry ironman-2026/day09/base-v1 \
  -p ironman-2026/day09/policies
# id=enum_member_removed,    attr=app.outcome: gateway_error
# id=attribute_type_changed, attr=biz.order.id
# id=brief_changed,          attr=biz.user.id
echo $?   # 1
```

## 4. `--future`：同一句診斷，兩種嚴重度

```bash
weaver registry check -r ironman-2026/day09/future-demo            # ⚠，exit 0
weaver registry check -r ironman-2026/day09/future-demo --future   # ×，exit 1
```

## 5. 下游完全不會被通知

`team-orders/` 依賴的是 base-v2，check 是綠的：

```bash
weaver registry check -r ironman-2026/day09/team-orders   # 0
```

但服務還在送 v1 時代的資料：

```bash
weaver registry live-check -r ironman-2026/day09/team-orders \
  --input-source ironman-2026/day09/live-check/samples.json
# violation: biz.order.id 型別是 string，應該是 int
# information: app.outcome = gateway_error 是未記載的值
```

只留 enum 那一筆的話，整份輸出只有一條 `information`，離開碼 0。**一個 breaking
change 從 registry 走到 runtime，沿路沒有任何一道門會擋它。**
