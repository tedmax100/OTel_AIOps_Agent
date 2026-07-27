# Day7 — 把 `weaver check` 接進 CI Gate

對應文章：Day7（2026 鐵人賽《AIOps with OpenTelemetry》）

> 資料夾的日號沿用文章重編之前的編號。這是文章合併前的原 Day11（CI gate 那半）。Day7 現在把 CI gate 跟 live-check 合成一篇。

不新增 registry 或 policy——沿用 [`../day10/`](../day10/) 那份刻意留著命名漂移的 registry 跟三條 naming policy，今天要做的是把它接成一道繞不過去的閘門。

實際的 workflow 在 repo 根目錄：[`.github/workflows/telemetry-schema.yml`](../.github/workflows/telemetry-schema.yml)。

## workflow 在做什麼

| 步驟 | 為什麼 |
|---|---|
| `on.pull_request.paths` | 只在動到 `day10/registry`、`day10/policies` 或 workflow 自己時才跑。治理閘門在無關 PR 上花時間，很快就會有人要求關掉 |
| 釘 `WEAVER_VERSION` | weaver 還在 0.x，內建規則會隨版本變嚴（見 Day9 的 0.23.0 踩坑）。浮動版本＝CI 隨時可能因為上游發版而在無關的地方變紅 |
| 用 musl 而非 gnu | gnu 版需要 GLIBC 2.38/2.39，舊一點的環境直接跑不起來 |
| `sha256sum -c` | 從 release 抓執行檔進 CI，官方有附校驗檔就順手驗。下載要用 `-O` 保持原檔名，校驗檔裡寫的是檔名 |
| **Probe：group 數 > 0** | Day5 那個 `-r .` 假綠燈的直接產物。路徑打錯時 weaver 會回報 0 groups 然後給綠燈——症狀是「一直都很順利」，沒有人會發現 |
| `--diagnostic-stdout=true` | **不能省**，見下方陷阱一 |
| `if: failure()` 補跑 ansi | 見下方陷阱三 |

## 三個實測出來的陷阱（weaver 0.24.1）

每一個都會讓 gate 安靜地失效——不是報錯，是看起來正常但沒有作用。

### 1. 診斷訊息預設走 stderr，GitHub 只讀 stdout

```bash
# 只看 stdout
weaver registry check -r day10/registry -p day10/policies \
  --diagnostic-format gh_workflow_command 2>/dev/null | grep -c "::error"
# → 0

# 只看 stderr
weaver registry check -r day10/registry -p day10/policies \
  --diagnostic-format gh_workflow_command 2>&1 >/dev/null | grep -c "::error"
# → 9
```

九行 `::error::` 全部走 stderr，而 Actions runner 只解析 stdout 上的 workflow command。預設設定下 annotation 完全不會出現，只會變成 log 裡看起來很像註解的紅字。job 仍然是紅的，所以這個失效很難察覺。

加上 `--diagnostic-stdout=true` 才會走 stdout（→ 9）。這兩個選項要一起用，`--diagnostic-format` 的說明裡沒提。

### 2. annotation 落不到程式碼的行上

```
::error file=registry, title=semconv_attribute::message=id=missing_namespace, category=naming, group=registry.order, attr=status
```

- `file=registry` 是 `-r` 傳進去的**目錄名**，不是實際出問題的 `model/drift.yaml`
- 完全沒有 `line=`
- `title` 永遠是 `semconv_attribute`（Day6 講的欄位錯位：Rego 裡的 `type` 變成 Finding 的頂層 `id`）

所以 annotation 不會內嵌在 PR diff 的那一行旁邊，只會出現在 PR 上方的摘要區，而且九條標題長得一模一樣。別指望它取代 log。

### 3. resolver 錯誤在 gh 格式下不會產生任何 annotation

拿一份 `ref` 指到不存在 attribute 的 registry：

```
$ weaver registry check -r <壞掉的 registry> --diagnostic-format gh_workflow_command

::group::Diagnostic report

::endgroup::

$ echo $?
1
```

完全空的 group。CI 會紅，但 PR 上什麼都沒有，連 log 都沒有——gh 格式把原本人看得懂的診斷替換掉了。同一份用預設 ansi 格式跑則訊息完整：

```
  × The following attribute reference is not resolved for the group
  │ Attribute reference: does.not.exist
```

`gh_workflow_command` 只實作了 policy Finding 的轉譯，沒有實作 resolver 錯誤的轉譯。所以 workflow 裡那個 `if: failure()` 的第二步不是多餘的：只在失敗時跑，成本是零，換來「任何一種失敗，log 裡都一定有人看得懂的說明」。

## 還有一步不在 YAML 裡

workflow 綠燈紅燈都正常之後，PR 上的 merge 按鈕**還是可以按**。要真的擋住，得去 Settings → Branches → branch protection rule，把 `registry-check` 這個 job 加進 **Require status checks to pass before merging**。

這是刻意的分工：「跑什麼」由 repo 內容決定，「什麼算必要」由 repo 管理者決定。否則任何有 write 權限的人都能在同一個 PR 裡把 gate 關掉再繞過它。但也因此這是最容易被忘記的一步——看起來大功告成，實際上還是一道推得開的門。

## 本機模擬

```bash
# 探針
groups=$(weaver registry stats -r day10/registry | grep -oE '[0-9]+ groups' | head -1 | cut -d' ' -f1)
echo "resolved ${groups} groups"     # → 2

# 檢查（會失敗，exit 1，9 個違規）
weaver registry check -r day10/registry -p day10/policies \
  --diagnostic-format gh_workflow_command --diagnostic-stdout=true
```
