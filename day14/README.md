# Day9 — breaking change：三層驗證模型與 registry diff

對應文章：Day9（2026 鐵人賽《AIOps with OpenTelemetry》）

不動 demo stack。這裡是四個版本的同一份 base registry 加一個下游團隊，示範
「什麼樣的變更 `diff` 看得到、什麼樣的看不到」以及「怎麼用 policy 把看不到的補起來」。

環境：weaver `0.25.1`。版本對照那一節另外需要一份 `0.23.0` 的 binary。

```
day14/
  base-v1/           0.1.0 基準版：4 個 attribute（含一個 enum、一個 int）＋ 1 個 event
  base-v2/           0.2.0 五種變更全湊滿：added / renamed / obsoleted / removed ＋ 新 event
  base-v3/           0.3.0 只改性質不動名字：type int→string、brief、requirement_level
  base-v4/           0.4.0 只做一件事：enum 拿掉 declined member
  breaking/          重現第一層 hard error：metric_requirement_level（規格有、weaver 不收）
  future/            第二層：三個 --future 才會從 ⚠ 變成 × 的違規
  team-on-v2/        下游團隊，dependencies → base-v2，但還在 ref 被改名／淘汰的欄位
  policies/
    breaking.rego          comparison_after_resolution：removed / type changed / enum 縮小
    deprecated_usage.rego  after_resolution：下游還在用 deprecated 的 attribute
```

## 跑法

**所有指令都從這個 repo 的根目錄跑** —— `registry_path` 是相對於工作目錄的（Day8 陷阱一）。

### 第一層：hard error

```bash
weaver registry check -r day14/breaking          # exit 1，兩個版本、加不加 --future 都一樣
```

### 第二層：`--future`

`day14/future/` 一份 registry 裡放了三個違規：`deprecated` 寫成字串、缺 `stability`、
string 型別缺 `examples`。

```bash
weaver registry check -r day14/future            # 三個 ⚠、exit 0
weaver registry check -r day14/future --future   # 同樣三句話變成 ×、exit 1
```

### 工具升版：0.23.0 在多依賴上 panic

```bash
weaver-0.23.0 registry check -r day13/squad       # exit 134（SIGABRT）
weaver          registry check -r day13/squad     # exit 0
```

### registry diff：看得到的五種

```bash
weaver registry diff -r day14/base-v2 --baseline-registry day14/base-v1
weaver registry diff -r day14/base-v2 --baseline-registry day14/base-v1 --format markdown
```

### registry diff：看不到的三種（兩份都輸出空白報告）

```bash
weaver registry diff -r day14/base-v3 --baseline-registry day14/base-v1   # type / brief / requirement_level
weaver registry diff -r day14/base-v4 --baseline-registry day14/base-v1   # enum member 被拿掉
weaver registry diff -r day14/base-v3 --baseline-registry day14/base-v1 --format json
```

### 第三層：用 policy 把三種補起來（每一個都 exit 1）

```bash
weaver registry check -r day14/base-v2 --baseline-registry day14/base-v1 -p day14/policies
weaver registry check -r day14/base-v3 --baseline-registry day14/base-v1 -p day14/policies
weaver registry check -r day14/base-v4 --baseline-registry day14/base-v1 -p day14/policies
```

### 下游團隊：預設綠燈，policy 才擋

```bash
weaver registry check -r day14/team-on-v2                                       # exit 0
weaver registry check -r day14/team-on-v2 --future                              # exit 0
weaver registry check -r day14/team-on-v2 -p day14/policies/deprecated_usage.rego   # exit 1，2 violations
```

注意最後一行只指定單一 policy 檔而不是整個 `day14/policies/` 目錄：`breaking.rego` 是
`comparison_after_resolution` package，沒有 `--baseline-registry` 時不會被評估。

## regorus 語法備忘

`day14/policies/breaking.rego` 裡兩個註解對應文章講的兩個坑：

- partial object rule（`head_attrs[a.name] := a`）必須限定 `g.type == "attribute_group"`，
  否則 ref 展開的副本會讓同一個 key 有多個 value → `rules must not produce multiple outputs`。
- 函式主體裡的 set comprehension 不能配 `if` 守衛（`enum_values(a) := {...} if is_object(...)`）
  → `statements not scheduled in query`。改成把 comprehension 寫在 `deny` body 裡。

`comparison_after_resolution` package 的 input：**`input` 是新版、`data` 是 baseline**，
兩邊都是 resolved schema（attribute 的鍵是 `name`）。
