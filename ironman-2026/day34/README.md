# Day34：換一座只改了名字的環境，量「我的知識屬不屬於這裡」

Series 1 最後一天量到「治理是環境的函數」，但那個比較是被混淆的：demo 叢集對上 Day1 那座 stack image，同時換掉了命名、Kubernetes API 的有無、以及資料形狀。這一天把變因收成一個。

## 孿生環境：同一批遙測，只有名字不一樣

同一支 collector 多開三條 pipeline，改名之後送到 `demo-twin` 那套 Prometheus/Loki/Tempo。服務、流量、事故、拓撲全部相同。

改名規則（模仿一個從來沒導入 semconv 的團隊）：

| | 家裡 | 孿生 |
| --- | --- | --- |
| resource 屬性 | `service.name` | `svc.name`（`service.name` 被刪掉） |
| metric 名字 | `payment_charges_total` | `acme_payment_charges_count_total` |
| Loki 可索引標籤 | `service_name="payment-service"` | `service_name="unknown_service"` |
| Tempo | `resource.service.name` 六個值 | 零個值 |

改動在主 repo（`o11y-bench`）的 `demo-services/`：

- `k8s/13-otel-collector.yaml` — `resource/twin` 與 `transform/twin` 兩個 processor，加三條 `*/twin` pipeline
- `k8s/30-twin-stores.yaml` — `demo-twin` namespace 與三個 store，由那三份原始 manifest 換 namespace 產生

```bash
kubectl apply -f demo-services/k8s/30-twin-stores.yaml
kubectl apply -f demo-services/k8s/13-otel-collector.yaml
kubectl -n demo rollout restart deploy/otel-collector
./demo-services/scripts/load.sh 8 90        # 讓兩邊都有資料
```

## 契合度腳本

```bash
# 六個 port-forward（家裡 1xxxx、孿生 2xxxx）
kubectl -n demo      port-forward svc/prometheus 19090:9090 &
kubectl -n demo      port-forward svc/loki       13100:3100 &
kubectl -n demo      port-forward svc/tempo      13200:3200 &
kubectl -n demo-twin port-forward svc/prometheus 29090:9090 &
kubectl -n demo-twin port-forward svc/loki       23100:3100 &
kubectl -n demo-twin port-forward svc/tempo      23200:3200 &

# 從範例 repo 的根目錄跑
python3 ironman-2026/day34/probe_env_fit.py --env both
python3 ironman-2026/day34/probe_env_fit.py --env twin -v   # 列出每一條沒對上的
```

```
[home] prom=http://localhost:19090 loki=http://localhost:13100 tempo=http://localhost:13200
  metrics   6/6  resolved   fit 1.00
  logs      5/5  resolved   fit 1.00
  traces    5/5  resolved   fit 1.00
  -> {"proven_good": true, "score": 1.0, "note": "injected knowledge resolves here (16/16)"}
  -> gate (environment dimension only): auto  high confidence, reversible, calibration + data-quality proven-good
     composite dq_verdict(): topology not reconciled against live traces; DQ unproven

[twin] prom=http://localhost:29090 loki=http://localhost:23100 tempo=http://localhost:23200
  metrics   0/6  resolved   fit 0.00
  logs      0/5  resolved   fit 0.00
  traces    0/5  resolved   fit 0.00
      ✗ metric order_create_duration_seconds (order-service)
      ✗ metric orders_total (order-service)
      ✗ (+14 more)
  -> {"proven_good": false, "score": 0.0, "note": "only 0/16 of the injected knowledge resolves against these stores (metric order_create_duration_seconds (order-service)); the catalog may belong to another environment"}
  -> gate (environment dimension only): propose  high confidence but data-quality (DQ) not proven-good
     composite dq_verdict(): only 0/16 of the injected knowledge resolves against these stores (metric order_create_duration_seconds (order-service)); the catalog may belong to another environment

home fit 1.0 -> auto   vs   twin fit 0.0 -> propose
(same services, same traffic, same incident — only the names differ)
```

兩件事值得看：

**孿生那邊的 Prometheus 一樣有 34 個指標名**（兩邊都用 `/api/v1/label/__name__/values` 數的）**。** 它不是一座空環境，是一座名字不同的環境，所以 0.00 不是「沒資料」，是「我背的名字在這裡一個都叫不動」。

**Loki 那格是只檢查 key 會漏掉的那一種。** `service_name` 在孿生上仍然是可索引標籤（Loki 在 resource 屬性缺席時會自己填 `unknown_service`），所以只問「這個 key 存在嗎」會拿到綠燈。要問到對的答案，key 跟 value 都得檢查。

## 接進治理平面

契合度不是一支獨立腳本就算完，它要走到會改變行為的地方。新的 `app/signals/envfit.py` 做三件事：

- `compute_env_fit()` 對三個 store 各問一次，結果進 module 快取（跟 reconcile 的 drift 同一個模式）
- `fit_verdict()` 收成 `{proven_good, score, note}`，也就是治理平面讀 DQ 的那個形狀
- `dq_verdict()` 把它排在**最前面**問。理由很簡單：如果 catalog 屬於另一座環境，後面那些維度量的是另一個系統

agent 那側在 `_refresh_env_fit()` 觸發，位置跟依賴健康度同一段（唯讀、不吃 agent 預算、best-effort），而且有 TTL，沒過期就不重量。

`app/signals/contract.py` 的 `validate_against_live()` 早就在做這件事的三分之一（metric 那側），而它除了自己的 dev CLI 之外**沒有任何呼叫端**。這個形狀在這系列出現第四次了。

```bash
# 直接跑那支模組（吃 PROMETHEUS_URL / LOKI_URL / TEMPO_URL）
PROMETHEUS_URL=http://localhost:29090 LOKI_URL=http://localhost:23100 \
  TEMPO_URL=http://localhost:23200 python -m app.signals.envfit
```

## 治理判決：同一組提案，兩個答案

`probe_env_fit.py` 最後會拿一個合成提案（可逆、不需核准、信心 0.95、校準紀錄乾淨）去問真的 `decide()`，只把環境這一維餵給它，其他維度不參與比較：

```
[home]  -> gate (environment dimension only): auto     high confidence, reversible,
                                              calibration + data-quality proven-good
[twin]  -> gate (environment dimension only): propose  high confidence but
                                              data-quality (DQ) not proven-good

home fit 1.0 -> auto   vs   twin fit 0.0 -> propose
(same services, same traffic, same incident — only the names differ)
```

那個合成提案把校準門檻歸零是**為了隔離變因**，不是建議這樣跑正式環境（真實 store 只有 7 筆標註，校準那道鎖本來就會先擋）。

## 測試

`tests/test_envfit.py` 七條，全部是純的（三個 store 都是假的）：沒量過是 unproven、全對是 proven-good、全錯要指名第一個沒對上的東西、**某個 store 不回答要算「沒有證據」而不是 fit 0.0**、量測過期不算數，以及那條 key 存在但 value 對不上的。`tests/test_dq.py` 多三條，包含「環境這一維排在 schema 跟拓撲前面」。全套 393 條通過。

## 還沒做

- **低契合度的時候，catalog 還是照樣注入。** 現在只有治理平面會因此收回自主權，agent 拿到的提示沒有變成「這裡的名字你不認識，先 discover」。
- **沒有量 2×2 分數。** 家裡／孿生 × 帶 catalog／不帶 catalog 那四格還沒跑，那要花 LLM 呼叫。
- **孿生沒有自己的告警規則。** 那邊的 alert rule 名字沒改，所以 runbook 比對那條路在孿生上還沒被測過。
- **fit 沒有歷史。** 跟拓撲對帳一樣，只有「這一次量到什麼」，沒有「連續幾次掉下來」。
