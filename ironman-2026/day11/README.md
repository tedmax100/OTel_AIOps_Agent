# Day11：機器可讀的意圖，與 codegen

registry 到目前為止只描述了「這個欄位叫什麼」。這一天加兩件事：把「這個欄位為什麼
重要」也寫成機器讀得到的形式，然後把 registry 編譯成程式碼裡的常數與 enum。

驗證環境：weaver 0.25.1、Python 3.12（只用到標準函式庫加 `pyyaml`）。

```
day11/
├── registry/            # 兩個 metric，attribute 上掛了 annotations
├── intent/
│   ├── steady-state.yaml         # 正常的穩定狀態意圖
│   ├── steady-state-broken.yaml  # 兩個刻意的錯，對應 agent 犯過的兩種
│   └── change.yaml               # 變更意圖，unchanged 那段才是重點
├── compile_intent.py    # 拿 registry 驗證意圖，再編譯成 alert rule / 驗證查詢
├── templates/python/    # weaver codegen 的 jinja 樣板
└── generated/           # 生成物，要 commit 進版控（理由見下）
```

以下指令都從這個 repo 的根目錄跑。

## 1. 意圖編譯成 alert rule

```bash
python3 ironman-2026/day11/compile_intent.py ironman-2026/day11/intent/steady-state.yaml
echo $?   # 0
```

輸出是一份可以直接放進 Prometheus 的 rule group。意圖裡的 `why` 跟 `first_check`
會落在 alert 的 annotations 上，值班的人（或 agent）看到告警的同時就看到「為什麼
這條會叫醒你」跟「先看哪裡」。

## 2. 寫壞的意圖擋得住

```bash
python3 ironman-2026/day11/compile_intent.py ironman-2026/day11/intent/steady-state-broken.yaml
echo $?   # 1
```

```
- objective `checkout-success-rate`: `app.outcome` 沒有 `AUTHORIZED` 這個值。
  合法的是：authorized, declined, gateway_error
- objective `checkout-error-budget`: registry 裡沒有 metric `orders.errors`。
  有的是：orders.attempts, orders.duration
```

兩個錯誤各對應 Day1 那隻 agent 犯過的一種：值的大小寫猜錯，以及指向一個名字聽起來
很合理、但根本不存在的欄位。

## 3. 變更意圖

```bash
python3 ironman-2026/day11/compile_intent.py ironman-2026/day11/intent/change.yaml
```

編出來的是部署後要跑的驗證查詢，重點在 `unchanged` 那幾條：「這次改動不應該動到
的東西」。

## 4. codegen

```bash
weaver registry generate -r ironman-2026/day11/registry \
  --templates ironman-2026/day11/templates python ironman-2026/day11/generated
```

產出 `semconv_attrs.py`（欄位名常數、型別表、deprecated 清單）與
`semconv_enums.py`（`StrEnum`）。有了它，手打字串的錯誤會在建構的當下就爆掉：

```python
>>> from semconv_enums import AppOutcome
>>> AppOutcome("AUTHORIZED")
ValueError: 'AUTHORIZED' is not a valid AppOutcome
```

## 5. 為什麼生成物要 commit 進版控

Day9 量過：`registry diff` 對型別改變、enum member 移除、`brief` 改寫這三種變更
完全靜音。但只要那些資訊出現在生成物裡，它們就會出現在**生成物的 diff** 裡。

用 Day9 那兩份 registry 各生成一次再 diff：

```bash
weaver registry generate -r ironman-2026/day09/base-v1 \
  --templates ironman-2026/day11/templates python /tmp/g1
weaver registry generate -r ironman-2026/day09/base-v2 \
  --templates ironman-2026/day11/templates python /tmp/g2
diff -u /tmp/g1/semconv_attrs.py /tmp/g2/semconv_attrs.py
diff -u /tmp/g1/semconv_enums.py /tmp/g2/semconv_enums.py
```

```diff
-    "app.outcome": "enum[authorized|declined|gateway_error]",
+    "app.outcome": "enum[authorized|declined]",
-    "biz.order.id": "string",
+    "biz.order.id": "int",
-# 使用者識別碼
+# 使用者的 email，登入用
-    GATEWAY_ERROR = "gateway_error"    # 下游回錯
```

三種靜音的變更，在 PR 的 diff 上全部現形。
