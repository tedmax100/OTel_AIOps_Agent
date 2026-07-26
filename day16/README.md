# Day11 — 機器可讀的意圖 ＋ 從 schema 生出型別安全的常數

對應文章：Day11（2026 鐵人賽《AIOps with OpenTelemetry》）

不動 demo stack。這裡是四份意圖 YAML（兩份正確、兩份故意寫壞）、一支把意圖編譯成
PromQL／alert rule 的腳本，以及一組把 registry 生成程式碼的 Jinja template。

環境：weaver `0.24.1`，python 需要 `pyyaml`（`compile_intent.py`）。

```
day16/
  registry/                  疊在 day14/base-v2 之上，補兩個 metric（counter ＋ histogram）
  intent/
    steady-state.yaml        穩定狀態意圖：兩條 objective（成功率、p99）
    change.yaml              變更意圖：expected ＋ unchanged ＋ rollback_if
    steady-state-broken.yaml 故意寫錯維度名（payment.status）
    steady-state-broken2.yaml 故意寫錯 enum 值大小寫（AUTHORIZED）
  compile_intent.py          拿 registry 驗證意圖，然後編譯成 alert rule / 驗證查詢
  templates/python/
    weaver.yaml              三個 template 的 filter 與 application_mode
    semconv_attrs.py.j2      欄位名常數 ＋ ALL_ATTRIBUTES / ATTRIBUTE_TYPES / DEPRECATED_ATTRIBUTES
    semconv_enums.py.j2      enum members → StrEnum
    registry.json.j2         {{ ctx | tojson(2) }}，整份 resolved schema
  generated/                 上面那組 template 的產出（commit 進版控是刻意的，見文章）
```

## 跑法

**所有指令都從這個 repo 的根目錄跑。**

### 1. 生成（意圖編譯器依賴 `generated/registry.json`）

```bash
weaver registry check -r day16/registry
weaver registry generate -r day16/registry --templates day16/templates \
  python day16/generated --include-unreferenced true
```

漏掉 `--include-unreferenced true` 的話，繼承自 `base-v2` 的 attribute 不會進生成物
（這個預設值在 Day8 咬過 `stats`、Day10 咬過 MCP，這裡是第三次）。

### 2. 生成物真的能用

```bash
cd day16/generated && python3 -c "
from semconv_enums import PaymentOutcome
from semconv_attrs import PAYMENT_OUTCOME, DEPRECATED_ATTRIBUTES, ALL_ATTRIBUTES
print('legal:', [m.value for m in PaymentOutcome])
print('ok:', PaymentOutcome('declined'))
try: PaymentOutcome('DECLINED')
except ValueError as e: print('raises:', e)
print('payment.status in registry?', 'payment.status' in ALL_ATTRIBUTES)"
```

### 3. 編譯意圖（兩份成功、兩份 exit 1）

```bash
python3 day16/compile_intent.py day16/intent/steady-state.yaml    # alert rule，exit 0
python3 day16/compile_intent.py day16/intent/change.yaml           # 驗證查詢，exit 0
python3 day16/compile_intent.py day16/intent/steady-state-broken.yaml   # 維度不存在，exit 1
python3 day16/compile_intent.py day16/intent/steady-state-broken2.yaml  # enum 值大小寫，exit 1
```

### 4. 生成物的 diff 補上 Day9 的靜音區

`weaver registry diff` 對型別改變、`brief` 改動、enum member 移除全部靜音（Day9）。
把同一組 template 套到 Day9 那幾份 registry 上，那些變更就會出現在生成物的 diff 裡：

```bash
for v in base-v1 base-v3 base-v4; do
  weaver registry generate -r day14/$v --templates day16/templates python /tmp/gen-$v
done
diff /tmp/gen-base-v1/semconv_attrs.py /tmp/gen-base-v3/semconv_attrs.py   # int → string、brief
diff /tmp/gen-base-v1/semconv_enums.py /tmp/gen-base-v4/semconv_enums.py   # DECLINED member 消失
```

## 意圖檔案的欄位

`compile_intent.py` 目前認得的欄位（沒有 JSON Schema，見文章「今天沒做的事」）：

| 欄位 | 用途 |
|---|---|
| `metadata.registry` | 這份意圖的欄位名以哪一份 registry 為準 |
| `signal.metric` | 必須是 registry 裡的 `metric_name` |
| `signal.dimension` | 必須是那個 metric 的 attribute 之一 |
| `signal.good_values` / `signal.values` | 必須落在該 attribute 的 enum members 裡 |
| `objective.ratio_min` / `quantile`＋`max_seconds` | 決定編譯成比率查詢還是 quantile 查詢 |
| `why` / `on_violation.first_check` | 原封不動搬進 alert 的 annotations |
| `unchanged[].tolerance_ratio` | 變更意圖：超出就是回滾條件 |
