# Day8：分層與所有權

兩層 registry：平台團隊擁有的 `base/`，跟訂單團隊擁有的 `team-orders/`。
用來回答「哪一層統一、哪一層放手」，以及示範四個安靜的坑。

驗證環境：weaver 0.25.1、semantic-conventions v1.43.0。

```
day08/
├── base/                     # 平台團隊：依賴官方 semconv，定義全公司共用的 biz.* / app.*
├── team-orders/              # 產品團隊：依賴 base，加自己的 biz.order.channel
│   └── model/orders.yaml     #   裡面刻意留著一份重複定義的 biz.user.id
├── policies/                 # 正式那條：conflicting_definition（after_resolution）
└── policies-prefix-ban/      # 太寬的那條：用 namespace 前綴禁止定義（before_resolution）
```

以下指令都從這個 repo 的根目錄跑。**`registry_path` 是相對於你在哪裡跑，不是相對
於 manifest 的位置**，所以換一個工作目錄會直接找不到 base。

## 1. 兩層都是綠的

```bash
weaver registry check -r ironman-2026/day08/base          # 0
weaver registry check -r ironman-2026/day08/team-orders   # 0
```

第二句會多花兩秒，因為它會把 base 跟 base 依賴的官方 semconv 一起拉下來
（第一次會 clone 到 `~/.weaver/vdir_cache/`）。

## 2. 依賴不遞移

在 `team-orders/model/orders.yaml` 的 span 裡加一行：

```yaml
      - ref: service.name
```

`service.name` 是官方 semconv 的屬性，base 有宣告那個 dependency，但 team-orders
看不到它：

```
× The following attribute reference is not resolved for the group
  'span.orders.create'.
  Attribute reference: service.name
```

要用就得自己也列一次那個 dependency。兩個都列在 0.25.1 上可以跑（`check` 綠燈），
代價是 semconv 被載入兩次，時間從 2.2 秒變成 4.3 秒。

## 3. 重複定義不是覆寫，是製造孤兒

`registry.orders.local` 裡那份 `biz.user.id` 跟 base 的同名。預設 check 是綠的：

```bash
weaver registry check -r ironman-2026/day08/team-orders   # 0
```

但 resolve 出來會看到兩份定義並存，而 span 引用到的是 base 那份：

```bash
weaver registry resolve -r ironman-2026/day08/team-orders --format json \
  | grep -A3 'biz.user.id'
```

把 base 的 group 一起拉進視野就會現形（注意這個 flag 在 0.25.1 已標為 deprecated）：

```bash
weaver registry check -r ironman-2026/day08/team-orders --include-unreferenced
# × The attribute id `biz.user.id` is declared multiple times in the following
#   groups: ["registry.acme.biz", "registry.orders.local"]
```

## 4. 兩條 policy

正式那條，抓「同一個名字有兩份不一樣的定義」：

```bash
weaver registry check -r ironman-2026/day08/team-orders -p ironman-2026/day08/policies
# id=conflicting_definition, group=(registry-wide), attr=biz.user.id
```

太寬那條，禁止團隊在 `biz.*` / `app.*` 底下定義任何東西：

```bash
weaver registry check -r ironman-2026/day08/team-orders -p ironman-2026/day08/policies-prefix-ban
# id=redefines_platform_attribute, ... attr=biz.order.channel   ← 誤傷
# id=redefines_platform_attribute, ... attr=biz.user.id         ← 真的該擋
```

`biz.order.channel` 是訂單團隊自己的新概念，不該被擋。這條規則問錯了問題：它問
「這個名字歸誰管」，該問的是「這個定義跟別人衝不衝突」。

跑 `policies-prefix-ban` 的時候摘要行仍然印 `✔ No after_resolution policy
violation`，因為那句話只講 after_resolution 那一階段。離開碼是 1，別看那行綠燈。
