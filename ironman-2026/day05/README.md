# Day5 — Weaver 上手：schema 是團隊共識

對應文章：**Day5**（《AIOps with OpenTelemetry》第五天）。

這一天不碰 k8s，所有東西都是純檔案加一支 CLI。內容是文章合併前的原 Day7＋Day8＋Day9 三篇的材料收在一起。

| 路徑 | 是什麼 |
|---|---|
| `registry/` | 本篇主角。`manifest.yaml` ＋ `model/` 底下五個檔案，共 34 個 group |
| `policies/biz_policies.rego` | 只比對名字前綴的那版規則（文章裡示範它為什麼不夠） |
| `policies/biz_policies.fixed.rego` | 改成「值域必須有界」之後的版本 |
| `examples/` | 七份最小可執行的獨立 registry，各示範一種 `group` 的 `type` |

## 環境

```bash
weaver --version     # 本篇用 0.25.0
```

這個工具還在快速演進，不同版本的輸出可能不一樣。下面的數字是 0.25.0 實跑的。

## 先量一個基準

在跑任何檢查之前先確認「這個檢查真的有讀到東西」。

```bash
weaver registry stats -r ironman-2026/day05/registry
```

```
ℹ Found registry manifest: .../registry/manifest.yaml
Registry
  - 34 groups
    - 5 AttributeGroups   (30 attributes)
    - 1 Entitys           (2 attributes)
    - 15 Events           (28 attributes)
    ...
```

**34 這個數字就是基準。** 之後任何一次 check 綠燈，都要先確認它是在這 34 個 group 上綠的。

## 第一次 check

```bash
weaver registry check -r ironman-2026/day05/registry
echo $?     # 0
```

綠燈只證明「這份定義自己內部一致」，完全不保證跑起來的服務有照它送資料。

## 三個一定要自己踩一次的坑

### 1. `-r` 指錯層 → 假綠燈

```bash
weaver registry check -r ironman-2026/day05/registry/model   # 34 groups，但沒有 manifest
weaver registry check -r .                                   # 0 groups
echo $?                                                      # 兩者都是 0
```

0.25.0 會印 `ℹ No registry manifest found`，但那是 info 等級，**不影響離開碼**。CI 上看到的還是綠的。

### 2. 放一份不是 registry 的 YAML → 硬錯誤（這種很好）

```bash
cp /path/to/some-configmap.yaml ironman-2026/day05/registry/model/
weaver registry check -r ironman-2026/day05/registry
```

```
× Object contains unexpected properties: apiVersion, data, kind, metadata.
  These properties are not defined in the schema.
```

exit 1。話講得很清楚，不可能誤會。

### 3. 放一份合法、但不該在這裡的 YAML → 完全沒有聲音

模擬一份忘了刪的實驗備份：

```yaml
# registry/model/oops-backup.yaml
groups:
  - id: registry.leftover
    type: attribute_group
    brief: "一份忘了刪的實驗備份"
    attributes:
      - id: leftover.attr
        type: string
        brief: "沒有人記得這個欄位"
        stability: development
```

```bash
weaver registry stats -r ironman-2026/day05/registry | grep groups
#   - 35 groups          ← 從 34 變 35

weaver registry check -r ironman-2026/day05/registry; echo $?
# 0                      ← 綠燈

weaver registry resolve -r ironman-2026/day05/registry | grep -c leftover
# 2                      ← 它真的進了 resolved schema
```

**第二種是「你用錯了」，工具有能力知道；第三種是「你放錯了」，工具沒有依據判斷。** 而第三種的東西會一路流進 policy 檢查、生成的程式碼、以及之後 MCP server 給 agent 的回答裡。

實務建議：registry 目錄裡不要放任何不是 registry 的東西。備份交給 git，臨時實驗丟 `/tmp`。

## policy

```bash
# 只比對名字前綴的版本
weaver registry check -r ironman-2026/day05/registry \
  --policy ironman-2026/day05/policies/biz_policies.rego

# 改成「值域必須有界」之後
weaver registry check -r ironman-2026/day05/registry \
  --policy ironman-2026/day05/policies/biz_policies.fixed.rego
```

## `examples/`

七份獨立的最小 registry，每份只有一兩個 group，用來單獨看一種 `group` 的 `type` 長什麼樣：

```bash
for d in ironman-2026/day05/examples/*/; do
  echo "== $d"
  weaver registry check -r "$d"; echo "exit=$?"
done
```

`metric-dangling-ref/` 是刻意寫壞的，用來看 resolver 階段的錯誤訊息長什麼樣。

## `infer`：從真實流量反推草稿

`weaver registry infer` **不是讀檔案，它是一個 OTLP gRPC 接收器**。要把服務跑起來、把流量打進去。

```bash
weaver registry infer --otlp-grpc-port 14317 --registry-path /tmp/inferred
```

port 刻意不用預設的 4317，避免收到本機其他 OTLP 來源的東西。

往返實驗（`emit` 發出去、`infer` 收回來、比對兩份 YAML）的結論：

| 資訊 | 往返之後 |
|---|---|
| group 的存在與名字 | 保住 |
| metric 的 `instrument` / `unit` | 保住 |
| attribute 名字與基本型別 | 保住 |
| `examples` | 只剩剛好流過去的那個值 |
| `brief` / `note` | 全空 |
| `requirement_level` | 一律變 `recommended` |
| `enum` 的 `members` | 退化成 `string` |

**觀察只能給你名字跟型別。語意、承諾、值域必須有人坐下來決定。**
