# Day12：不用 LLM 也能驗證治理資產

前面十一天做出了一堆會擋人的東西：命名 policy、CI gate、live-check、分層檢查、
breaking change 比對、意圖編譯器。這一天把它們收成一支回歸腳本。

**它斷言的不是「這些指令會不會通過」，是「該紅的還會不會紅」。**

```
day12/
├── regress.sh              # 29 條斷言，跑一次約 40 秒，零 LLM 呼叫
├── fixtures/               # 兩份「本來就該被抓到」的樣本
└── mcp_layered_probe.py    # 把 Day10 那個分層查不到的行為釘成一條斷言
```

## 跑

```bash
bash ironman-2026/day12/regress.sh
echo $?    # 全過是 0，任何一條沒守住就是 1
```

輸出分五段：

| 段落 | 條數 | 在驗什麼 |
| --- | --- | --- |
| 探針 | 6 | 每份 registry 真的被讀進來了（Day5 那個 `-r .` 假綠燈的教訓） |
| 該綠的還是綠的 | 6 | 正常的東西沒有被誤擋 |
| 該紅的還會紅嗎 | 8 | 每一條 gate 都還擋得住它當初要擋的東西 |
| 訊息本身 | 4 | 被擋的人拿得到能自己修好的資訊 |
| 已知的缺口 | 4 | 這些現在就是不會擋，寫下來才不會誤以為有人在守 |

外加一條：`generated/` 跟 registry 有沒有走散。

## 為什麼「已知的缺口」也要寫成斷言

`registry diff` 對型別改變靜音、live-check 對被移除的 enum 值只給 information、
MCP 對分層 registry 查不到 base 的屬性。這三件事今天都是預期行為，所以斷言寫的是
「它現在就是不擋」。

這樣做有兩個好處：一是不會有人半年後誤以為那裡有防護，二是上游哪天修好了，這幾條
會變紅，而那個紅燈的意思是「可以把自己補的那層拆掉了」。

## 自我驗證

一條永遠不會失敗的斷言等於沒有斷言。把 Day6 那個「package 名字打錯」的坑重現一次：

```bash
sed -i 's/^package after_resolution/package mypolicy/' ironman-2026/day12/policies/naming.rego
bash ironman-2026/day12/regress.sh
```

```
✗ day06 命名漂移擋得住                    exit=0（預期 1）
✗ day06 講得出是哪一條規則                沒找到「duplicate_concept」
✗ day07 產得出 GitHub annotation               沒找到「::error file=」
29 條斷言：26 通過，3 失敗
```

一個字都沒改的 registry，policy 靜悄悄不執行，三條斷言同時倒下。改回來就恢復綠燈。

---

## 新服務上線 checklist

`verify_onboarding.py` 是這一階段的收尾：13 項檢查，每一項都真的執行一次工具，
每一項失敗都印出下一步。它不問「你有沒有做」，它自己去看。

驗證環境：weaver 0.25.1。

```
day12/
├── verify_onboarding.py
├── shipping-v0/     # 照抄一半的新服務：registry check 是綠的，但 7/13
└── shipping-v1/     # 補完之後：13/13
```

以下指令都從這個 repo 的根目錄跑（`registry_path` 綁 cwd，見 Day8）。

## 跑

```bash
python3 ironman-2026/day12/verify_onboarding.py ironman-2026/day12/shipping-v0   # 7/13，exit 1
python3 ironman-2026/day12/verify_onboarding.py ironman-2026/day12/shipping-v1   # 13/13，exit 0
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
weaver registry check -r ironman-2026/day12/shipping-v0/registry \
  -p ironman-2026/day12/policies --include-unreferenced
# × The attribute id `biz.user.id` is declared multiple times ...
# 但同時也會噴出 aws.dynamodb.table_names、client.port 這些上游自己的同名定義
```

兩個洞都是跑壞掉的服務才顯現出來的。**壞掉的服務是測試資料，不是教材。**

## 這支腳本在 CI 裡

`regress.sh` 不是只有手動跑。[`.github/workflows/telemetry-schema.yml`](../../.github/workflows/telemetry-schema.yml)
的 `regress-ironman` job 會在每個動到 `ironman-2026/**` 的 PR 跟推上 main 時跑它：

```yaml
- uses: ./.github/actions/setup-weaver
  with:
    version: ${{ env.WEAVER_VERSION }}   # v0.25.1，釘死
- run: pip install --quiet pyyaml
- uses: actions/cache@v4                  # ~/.weaver/vdir_cache
- run: bash ironman-2026/day12/regress.sh
```

幾件值得抄的事：

- **CI 跑的是這支腳本，不是 `weaver registry check`。** 這個 repo 裡有一半的
  registry 是故意寫壞的教材，直接跑 check 會讓 gate 永遠紅燈。斷言寫死預期離開碼，
  才有辦法讓「該紅的」跟「該綠的」在同一個 job 裡共存。
- **快取 `~/.weaver/vdir_cache`。** day08/day09 那幾份 registry 依賴官方
  semantic-conventions，沒有快取每跑一次都要 clone，而且 GitHub 抽風時會變成假紅燈。
  cache key 掛在 `ironman-2026/**/manifest.yaml` 上，依賴的版本改了才重抓。
- **path filter 是 workflow 級的，不是 job 級的**，所以動到 `ironman-2026/` 也會把
  Series 1 那個 job 一起帶起來。這是刻意的：升 weaver 版本正是那種會同時打到兩套
  資產的改動，只跑被改到的那一套等於讓跨系列的破壞沒人看得到。

還沒進 CI 的是 `verify_onboarding.py`。它前六項是機械的、可以直接當 required
check，後面幾項（有沒有寫意圖）不適合用擋的，所以要先決定拆成兩個 job 還是只跑
前半段。
