# testability — 治理資產的回歸測試（無 LLM）

對應文章：Day12（2026 鐵人賽《AIOps with OpenTelemetry》）

這個資料夾沒有跟著任何一天的快照走，它是**橫跨 Day5–Day13 所有 fixture 的回歸測試**。
一次 LLM 呼叫都沒有，跑完不到十秒。

```
testability/
  regress.sh    21 條斷言（其中 12 條預期 exit 1），表格驅動
```

## 跑法

從這個 repo 的根目錄跑：

```bash
./testability/regress.sh
WEAVER=~/.local/bin/weaver ./testability/regress.sh     # weaver 不在 PATH 時
```

需要 `pyyaml`（`compile_intent.py`）與 `opentelemetry-api`／`opentelemetry-sdk`
（`run_and_extract.py`）。不需要 cluster、不需要 API key、不需要網路——**這是刻意的約束：
一份需要環境才能跑的測試，會變成一份沒有人在本機跑的測試。**

## 為什麼 12 條預期 exit 1

治理資產壞掉的方式不是報錯，是**放行**。所以這組測試主要在測「它還會不會擋」，
而不是「它會不會通過」——一組全部預期 exit 0 的測試，對 policy／gate／checklist
幾乎沒有價值，因為所有「安靜失效」的壞法都會讓它繼續全綠。

## 涵蓋的 fixture 與它們故意壞在哪

| fixture | 故意壞在哪 | 該擋住的是 |
|---|---|---|
| `day17/services/shipping-v0` | camelCase、缺 stability、inline 定義、沒有意圖 | 命名／分層 policy、checklist |
| `day14/breaking` | 規格有、weaver 不收的欄位 | 第一層 hard error |
| `day14/future` | 缺 stability／examples、字串式 deprecated | 第二層 `--future` |
| `day14/base-v2` | attribute 直接消失 | 第三層 comparison policy |
| `day14/base-v3` | 型別 `int` → `string` | 第三層（`registry diff` 對此靜音） |
| `day14/base-v4` | enum 少一個 member | 第三層（`diff` 也靜音） |
| `day14/team-on-v2` | 下游還在 ref 被改名的欄位 | `deprecated_usage.rego` |
| `day16/intent/steady-state-broken.yaml` | 指到不存在的維度 | 意圖編譯器 |
| `day16/intent/steady-state-broken2.yaml` | enum 值大小寫不符 | 意圖編譯器 |
| `day15/samples/payment_handler_before.py` | 四個過時／不合規的欄位 | live-check |
| `day15/samples/payment_handler_after.py` | 把欄位搬到 span event（＝新增） | live-check |

最後兩個 fixture 是靠 `day15/run_and_extract.py` 從**真實送出的 span** 抽樣本，不是手打的。
理由見文章：手打的樣本只涵蓋你記得的那部分，而你會忘記的正是你剛剛動過的地方。

## 新增規則時的工作習慣

**加一條規則，就在對應的 fixture 裡種一個違規。** 一條從來沒有紅過的規則，等於一條沒有被
測試過的規則。`day17/services/shipping-v0` 已經因此抓到過一次真的——Day13 那個
enum 檢查漏掉 `shippingStatus` 的洞。
