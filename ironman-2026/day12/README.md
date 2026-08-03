# Day12：不用 LLM 也能驗證治理資產

前面十一天做出了一堆會擋人的東西：命名 policy、CI gate、live-check、分層檢查、
breaking change 比對、意圖編譯器。這一天把它們收成一支回歸腳本。

**它斷言的不是「這些指令會不會通過」，是「該紅的還會不會紅」。**

```
day12/
├── regress.sh              # 29 條斷言，跑一次約 36 秒，零 LLM 呼叫
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
sed -i 's/^package after_resolution/package mypolicy/' ironman-2026/day07/policies/naming.rego
bash ironman-2026/day12/regress.sh
```

```
✗ day06 命名漂移擋得住                    exit=0（預期 1）
✗ day06 講得出是哪一條規則                沒找到「duplicate_concept」
✗ day07 產得出 GitHub annotation               沒找到「::error file=」
29 條斷言：26 通過，3 失敗
```

一個字都沒改的 registry，policy 靜悄悄不執行，三條斷言同時倒下。改回來就恢復綠燈。
