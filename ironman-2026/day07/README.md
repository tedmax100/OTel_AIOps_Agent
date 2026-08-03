# Day7：治理成為門——CI gate 與 live-check

Day6 那三條 Rego 規則已經跑得出 9 個違規、離開碼 1，但沒有任何東西保證它會被跑到。
這一天把它接成兩道守在不同時間點的門：

- **PR 的那一刻**：`workflows/weaver-gate.yml`，擋的是「別把壞的定義寫進 registry」。
- **服務跑起來之後**：`weaver registry live-check`，抓的是「程式碼實際送出去的東西
  有沒有照規範」。

驗證環境：weaver 0.25.1。

```
day07/
├── registry/           # Day6 那份漂移收斂之後的版本（CI 的綠燈基準、live-check 的比對基準）
├── policies/naming.rego# Day6 的三條命名規則，一字未改
├── workflows/          # CI gate 的快照，要用請複製到 repo 根目錄的 .github/workflows/
└── live-check/
    ├── samples.json      # 六筆樣本，形狀照著 demo 服務真的在送的東西寫
    ├── pii-samples.json  # 給自訂 advice 用的兩筆
    └── advice/pii.rego   # 自訂 advice policy（注意：--advice-policies 是覆蓋不是疊加）
```

以下指令都從這個 repo 的根目錄跑。

## 1. registry 本身是綠的

```bash
weaver registry check -r ironman-2026/day07/registry -p ironman-2026/day07/policies
echo $?   # 0
```

拿昨天那份沒收斂的當對照組，同一組 policy 會噴 9 個違規、離開碼 1：

```bash
weaver registry check -r ironman-2026/day06/registry -p ironman-2026/day07/policies
echo $?   # 1
```

## 2. 探針：確認這道 gate 真的讀到東西

`-r` 指錯路徑時 weaver 會讀到 0 個 group，然後回報「沒有違規」、離開碼 0。

```bash
weaver registry stats -r ironman-2026/day07/registry | grep -oE '[0-9]+ groups'   # 2 groups
weaver registry stats -r . | grep -oE '[0-9]+ groups'                             # 0 groups
```

workflow 裡的 `Probe` step 就是這一句加上一個 `-lt 1` 的判斷。

## 3. 產出 GitHub annotation

```bash
weaver registry check -r ironman-2026/day06/registry -p ironman-2026/day07/policies \
  --diagnostic-format gh_workflow_command --diagnostic-stdout
```

沒有 `--diagnostic-stdout` 的話，這些 `::error` 會走 stderr。

## 4. live-check：對真實流量的形狀做檢查

```bash
weaver registry live-check -r ironman-2026/day07/registry \
  --input-source ironman-2026/day07/live-check/samples.json
echo $?   # 1（預設 --fail-on violation）
```

`--input-source` 也吃 `stdin` 跟 `otlp`（預設是 `otlp`，會起一個 listener）。
用 OTLP 模式時記得指定 `--otlp-grpc-port`，預設的 4317 很容易吃到本機其他 OTel
程序的遙測。

自訂 advice：

```bash
weaver registry live-check -r ironman-2026/day07/registry \
  --input-source ironman-2026/day07/live-check/pii-samples.json \
  --advice-policies ironman-2026/day07/live-check/advice
```

注意 `--advice-policies` 會**覆蓋**內建的 Rego advice（`missing_namespace`、
`invalid_format` 會消失），Rust 側的 registry 比對與 `not_stable` 不受影響。
