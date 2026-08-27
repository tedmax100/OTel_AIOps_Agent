# Day27：提案是一列會自己走完的狀態，而演習決定那列數不數

文章 Day27 用到的東西，分兩半：把「建議」做成一列有狀態的資料，以及把整條路在一個
自己弄壞的系統上真的走一次。

| 檔案 | 內容 |
| --- | --- |
| `importgraph.py` | 讀出執行／治理平面的真實模組關係（`--focus` 一次讀一個平面） |
| `probe_governance.py` | 逐條讀那個授權判斷 |
| `probe_lifecycle.py` | 撞一次提案狀態機，包含 8 執行緒同時 approve 的 CAS |
| `regress_guards.py` | 把每一道護欄寫成回歸清單 |
| `gameday.py` | 第一次真的動手那輪演習（`plan` / `run --scenario a|b` / `cleanup`） |
| `close_the_loop.py` | 把第二個事故整圈跑完的驅動腳本，`run` 預設是排練，`--no-drill` 才會寫進案例記憶 |
| `k8s/` | 演習用的注入清單 |

`store-before-*` / `store-after-*` 是每一輪跑之前跟之後的資料庫快照，`snapshot-*` 是
gameday 那兩個劇本的，`drill-*` / `nodrill-*` 是當時的逐字輸出。留在 git 裡的那幾份是
文章引用到的；其餘每跑一輪就產生一對，被 `.gitignore` 擋掉（一次演習約 400KB，同一場
重跑五次不是五個發現）。

## 這一天是從哪幾天合併過來的

下面保留了合併之前每一份原始筆記，內容沒有改寫，所以裡面的日號指的是舊的編排。

- [`README.day28-drill.md`](README.day28-drill.md)（演習那半）
- [`README.day29.md`](README.day29.md)
- [`README.day30.md`](README.day30.md)
- [`README.day33.md`](README.day33.md)
- [`README.day36.md`](README.day36.md)
- [`README.day41.md`](README.day41.md)
