# Day13：新服務上線 checklist

`verify_onboarding.py` 是這一階段的收尾：13 項檢查，每一項都真的執行一次工具，
每一項失敗都印出下一步。它不問「你有沒有做」，它自己去看。

驗證環境：weaver 0.25.1。

```
day13/
├── verify_onboarding.py
├── shipping-v0/     # 照抄一半的新服務：registry check 是綠的，但 7/13
└── shipping-v1/     # 補完之後：13/13
```

以下指令都從這個 repo 的根目錄跑（`registry_path` 綁 cwd，見 Day8）。

## 跑

```bash
python3 ironman-2026/day13/verify_onboarding.py ironman-2026/day13/shipping-v0   # 7/13，exit 1
python3 ironman-2026/day13/verify_onboarding.py ironman-2026/day13/shipping-v1   # 13/13，exit 0
```

13 項分三段：

| 段落 | 項次 | 在問什麼 |
| --- | --- | --- |
| 基本 | 1-3 | manifest 在不在、registry 真的讀得到、check 過不過 |
| 命名與分層 | 4-6 | 命名規則、有沒有接上 base、有沒有跟別人衝突的重複定義 |
| 對 agent 的可用性 | 7-10 | 每個 attribute 有 brief、狀態欄位是 enum、metric 有語意單位跟 owner |
| 意圖與產出 | 11-13 | 有沒有寫下什麼叫正常、編不編得出 alert rule、生不生得出常數 |

## 這份 checklist 自己有兩個洞

跑 `shipping-v0` 的時候，有兩項是綠的，而它們**不該是綠的**。

**第 8 項（狀態欄位要有值域）放過了 `shippingStatus`。** 那個檢查看的是名字最後一段
是不是 `status` / `outcome` / `state` / `result`，而 `shippingStatus` 沒有點、
整個名字就是一段，所以匹配不到。它因為**同時違反了命名規則**，反而躲過了值域檢查。

**第 6 項（不准跟 base 重複定義）也放過了 `biz.user.id`。** v0 沒有宣告 dependency，
所以 base 的定義根本沒進到 resolved schema，沒有東西可以跟它衝突。手動補上 dependency
之後它還是綠的，因為未被 `ref` 的屬性不會進 resolved schema（Day8、Day10 那個行為）。
只有加上 `--include-unreferenced` 才抓得到：

```bash
weaver registry check -r ironman-2026/day13/shipping-v0/registry \
  -p ironman-2026/day08/policies --include-unreferenced
# × The attribute id `biz.user.id` is declared multiple times ...
# 但同時也會噴出 aws.dynamodb.table_names、client.port 這些上游自己的同名定義
```

兩個洞都是跑壞掉的服務才顯現出來的。**壞掉的服務是測試資料，不是教材。**
