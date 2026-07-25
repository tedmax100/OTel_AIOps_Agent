# Day7 — Weaver 基礎知識：`group` 的五種 `type`，實際跑給你看

對應文章：Day7（2026 鐵人賽《AIOps with OpenTelemetry》）

這天原本規劃是純概念日、不碰程式碼，但文章裡示範 `group` 的五種 `type`（`span`/`metric`/`attribute_group`/`event`/`entity`）時，把每個範例都真的丟給 `weaver registry check` 跑過一次，抓到兩個原本沒發現的真實坑（`stability` 缺了只警告、`brief` 缺了直接判失敗）。這些範例因此值得留下來，不是「無程式碼異動」。

demo stack 本身沿用 [`../day06/`](../day06/) 的狀態不變；這裡新增的 `examples/` 只是六份獨立、最小可執行的 registry，純粹用來驗證 `group` 的語法，跟 `demo-services` 的正式 registry（`../day06/weaver/`）無關。

## 六份範例

```
examples/
  span-only/            # type: span，乾淨通過
  metric-dangling-ref/  # type: metric，故意 ref 一個不存在的 attribute → resolver 錯誤
  attribute-group/      # type: attribute_group，乾淨通過
  event/                # type: event，乾淨通過
  entity/               # type: entity，乾淨通過
  combined/             # order.yaml + common.yaml 兩個檔案合成一份 registry，ref 解析成功
```

跑法（本機需要 `weaver` CLI）：

```bash
cd examples
weaver registry check -r span-only
weaver registry check -r attribute-group
weaver registry check -r event
weaver registry check -r entity
weaver registry check -r combined

# 故意會失敗的那份（resolver 錯誤，離開碼 1）
weaver registry check -r metric-dangling-ref
```

## 真實結果

`span-only`、`attribute-group`、`event`、`entity`、`combined` 五份全部乾淨通過：

```
Weaver Registry Check
Checking registry `<dir>`
ℹ Found registry manifest: <dir>/manifest.yaml
✔ No `after_resolution` policy violation
```

`metric-dangling-ref` 因為 `metric.yaml` 裡 `ref: app.outcome` 指到一個整份 registry都沒定義的 attribute，會在 `weaver_resolver` 這一步就中止（離開碼 1），不會有 policy Finding：

```
Diagnostic report:

  × The following attribute reference is not resolved for the group
  │ 'metric.app.orders.count'.
  │ Attribute reference: app.outcome
  │ Provenance: ...
```

`combined/` 就是拿同一個 `app.outcome` 去補這個坑——`order.yaml` 的 `ref: app.outcome` 這次在 `common.yaml` 裡找得到定義，兩個檔案合起來才是一份能通過的 registry，證明 `weaver_semconv` 解析的單位是整份 `groups:` 的總和，不限於單一檔案。

## 兩個順便抓到的驗證規則

寫這幾份範例的過程中，第一版分別漏了 `stability`（`span-only`）跟 `brief`（`event`/`entity` 的 attribute），跑出來的結果不一樣：

- **漏 `stability`**：只印警告（`Invalid stability on group ... does not contain a stability field`），離開碼還是 `0`。
- **漏 attribute 的 `brief`**：直接判失敗（`This attribute is not deprecated and does not contain a brief field`），離開碼 `1`。

這兩條都是 weaver 內建的驗證規則，不需要額外寫 Rego policy 就會生效——跟 Day8 的自訂 policy（`biz_policies.rego`）是兩層不同的檢查。目前 repo 裡的六份範例都已經是修正過、乾淨通過的版本。
