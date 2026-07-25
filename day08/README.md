# Day8 — Weaver 上手：第一次 `weaver registry check`

對應文章：Day8（2026 鐵人賽《AIOps with OpenTelemetry》）

沿用 [`../day06/`](../day06/) 的狀態，不新增/修改任何 stack 檔案——`../day06/weaver/` 底下的 registry（`registry/model/*.yaml`）跟自訂 policy（`policies/biz_policies.rego`）在 Day6 就已經建好，今天要做的事只有一件：第一次真的對它跑 `weaver registry check`，貼真實輸出。

## 跑法

```bash
cd ../day06
# 內建規則（naming/stability/…）
bash scripts/weaver.sh check
# 加上自訂的 biz.* 高基數 policy
bash scripts/weaver.sh check --policy

# 或者本機裝了 weaver CLI，直接跑：
weaver registry check -r weaver/registry
weaver registry check -r weaver/registry -p weaver/policies
```

## 真實輸出：目前是乾淨的

```
Weaver Registry Check
Checking registry `weaver/registry`
ℹ Found registry manifest: weaver/registry/manifest.yaml
✔ No `after_resolution` policy violation

Total execution time: 0.021600395s
```

`--policy` 加自訂的 `biz_policies.rego`（禁止 `biz.*` 高基數屬性被拿去當 metric label）結果一樣乾淨。這不是因為今天沒認真找碴，而是這份 registry 本來就是照著「目標命名」設計的（`app.*`/`biz.*` 這種 idiomatic、namespaced 的寫法），不是照搬 `demo-services` 現在實際送出的 flat key（`user_id`/`status`/`reason`…）。這個落差本身，`../day06/weaver/README.md` 的「Current flat key → Registry attribute」對照表已經整理過——`weaver registry check` 檢查的是 registry 定義本身自洽不自洽，不是拿它去對照真實服務的輸出；那是 Day12 `live-check` 要做的事。

## 兩個示範性的失敗（不會提交進 repo）

為了讓大家看到 Finding 真正長什麼樣子，在一份**丟棄式的複製**上刻意弄壞兩次——這兩步都只在本機 `/tmp` 操作，`day06/weaver/` 本身沒有被動過：

**示範一：resolver 階段的錯誤**（`ref` 指到不存在的 attribute）

```bash
cp -r ../day06/weaver /tmp/weaver-demo
# 在 /tmp/weaver-demo/registry/model/metrics.yaml 的
# metric.app.orders.count 裡加一行 `- ref: app.nonexistent_attr`
weaver registry check -r /tmp/weaver-demo/registry
```

```
Diagnostic report:

  × The following attribute reference is not resolved for the group
  │ 'metric.app.orders.count'.
  │ Attribute reference: app.nonexistent_attr
  │ Provenance: Some(Provenance { schema_url: SchemaUrl { url: "https://
  │ tedmax100.github.io/o11y-bench/demo-services/schemas/0.1.0", name_range:
  │ 8..60, version_range: 61..66 }, path: "registry/model/metrics.yaml" })
```

`weaver_resolver` 在展開 `ref` 這一步就中止了——完全沒有「Violation」字樣，也沒有 policy 的 `id`/`level`/`context` 結構，因為根本還沒輪到 `weaver_checker`。

**示範二：checker 階段的 Finding**（讓 metric 違反 `biz_policies.rego`）

```bash
# 在同一份複製的 metrics.yaml 裡，替 metric.app.orders.count
# 加一行 `- ref: biz.order.id`（高基數 business id 拿去當 metric label）
weaver registry check -r /tmp/weaver-demo/registry -p /tmp/weaver-demo/policies
```

```
✔ All `after_resolution` policies checked (1 violations found)

Violation: semconv_attribute
  - Message   : id=high_cardinality_metric_label, category=attribute, group=metric.app.orders.count, attr=biz.order.id
  - Level     : violation
  - Context   :
    - attr : biz.order.id
    - category : attribute
    - group : metric.app.orders.count
    - id : high_cardinality_metric_label
  - Provenance: registry
```

這正是 `policies/biz_policies.rego` 要擋的事——`biz.*` 是高基數的業務識別碼（user id、order id…），一旦被拿去當 metric label，等於让每個不同的 id 都變成一條新的時間序列。這條 policy 把 `o11y_shared/events.py` docstring 裡那句警告（「Never include dynamic ids... every addition widens the label space」）變成一個會在 CI 擋下來的自動化規則，而不是只停留在註解裡靠人記得。

## 對照 Day7 的 crate 分工

- 示範一的錯誤來自 `weaver_resolver`：`ref`/`extends` 展開失敗，管線走不到後面。
- 示範二的 Finding 來自 `weaver_checker`：resolved schema 進了 Rego runtime，`after_resolution` package 裡的規則判斷出違規。
- 兩種錯誤的資料結構完全不同（一個是純文字診斷，一個有 `id`/`level`/`context`），這也是為什麼 Day10-11 要花兩天，把 Finding 的完整結構跟「怎麼把離開碼接進 CI Gate」分開講。
