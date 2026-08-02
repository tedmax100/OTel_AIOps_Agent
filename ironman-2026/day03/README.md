# Day3 — OTel Operator：把「持續維護」從人身上搬到迴圈裡

對應文章：**Day3**（《賢者大叔的觀測結界》第三天）。

這個資料夾是 Day3 做完之後、整組 demo stack 的**完整快照**，不是 diff。完整的架構說明（五個服務、o11y stack、流量產生器）見 [STACK-README.md](./STACK-README.md)。

## 這一天改了什麼

| 路徑 | 變動 | 對應文章哪一節 |
|---|---|---|
| `k8s/13-otel-collector.yaml` | 手寫的 `Deployment`+`Service`+`ConfigMap` → `OpenTelemetryCollector` CR，外加一個手寫 NodePort | 〈把手寫的 Deployment 換成 CR〉 |
| `k8s/16-instrumentation.yaml` | 新增 `Instrumentation` CR（**宣告了但故意沒接到任何 Pod**） | 〈`Instrumentation` CR 宣告了，但今天故意不接上去〉 |
| `k8s/kustomization.yaml` | 新增，把「哪些檔案算數」宣告成一份可被單一指令解析的清單 | 〈收尾：讓這些 CR 進得了 GitOps〉 |
| `scripts/up.sh` | 逐檔案 `kubectl apply -f` → `kubectl kustomize k8s/ \| kubectl apply -f -` | 同上 |
| `GITOPS-REVIEW.md` | 新增，寫給 reviewer 的五條人肉 checklist | 〈PR 該看什麼〉 |

（另外順手修了 `shared/src/o11y_shared/flags.py` 裡一行 Python 2 的 `except` 語法，跟這一天的主題無關，文章沒寫。）

## 怎麼重現

以下指令都從**這個 repo 的根目錄**跑。

### 1. 裝 Operator

```bash
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm install opentelemetry-operator open-telemetry/opentelemetry-operator \
  --namespace opentelemetry-operator-system --create-namespace \
  --set admissionWebhooks.certManager.enabled=false \
  --set admissionWebhooks.autoGenerateCert.enabled=true

kubectl get crd | grep opentelemetry     # 應該有四個
```

`autoGenerateCert` 產的是 self-signed 憑證，一年後過期要手動處理。**正式環境請用 cert-manager**，這裡是 demo 的取捨。

### 2. 起 stack

```bash
./ironman-2026/day03/scripts/up.sh
```

`up.sh` 現在走的是 kustomize 單一入口，跟 Argo CD／Flux 指向 `k8s/` 時會做的事一致。

### 3. 看 Operator 幫你補了什麼

```bash
# 三個 Service，不是一個——headless 與 monitoring 是 Operator 補的
kubectl -n demo get otelcol,svc

# spec 裡分成「我寫的」跟「schema 幫我補的」（targetAllocator 那一整段我沒寫過）
kubectl -n demo get otelcol otel -o yaml

# 這一天最重要的欄位：observedGeneration 對不對得上 metadata.generation
kubectl -n demo get otelcol otel -o jsonpath='{.status.conditions}' | jq
```

### 4. 親眼看調和迴圈把東西補回來

```bash
kubectl -n demo delete deployment otel-collector
kubectl -n demo get deployment -w        # 幾秒內會被重建
```

一次性 apply 的錯誤會一直錯下去直到有人發現；調和迴圈的錯誤會在下一輪自動修正。

### 5. 看看 GitOps 那一步實際產出什麼

```bash
kubectl kustomize ironman-2026/day03/k8s | head -40      # 單一份 manifest
kubectl kustomize ironman-2026/day03/k8s | kubectl diff -f -   # 這個 PR 真的會動到什麼
```

## 兩個容易踩的地方

**CR 為什麼叫 `otel` 而不是 `otel-collector`。** Operator 建立 Service 的命名規則是 `<CR 名稱>-collector`。叫 `otel` 生出來的正好是 `otel-collector`，而五個 app 的 `OTEL_EXPORTER_OTLP_ENDPOINT` 本來就指向它——整個遷移，app 的 manifest 一行都不用改。

**手寫的 NodePort 綁在 Operator 的 label 上。** `otel-collector-nodeport` 的 selector 是 `app.kubernetes.io/instance: demo.otel`，這個值是 `<namespace>.<CR 名稱>` 組出來的。**CR 改名，這個 Service 會安靜地選不到任何 Pod——不報錯，只是沒有 endpoint。**

## 今天刻意沒做的事

- **沒有導入 Argo CD／Flux 本身**，只做到本地流程跟 GitOps controller 的行為對齊。
- **`Instrumentation` CR 沒有接到任何 Pod。** 五個服務的 Dockerfile 目前 `CMD` 還是 `opentelemetry-instrument uvicorn ...`，現在加 annotation 會變成兩套注入機制打架。這是下一天的實驗。
- **沒有加 `commonLabels`。** 它會蓋到 `23-api-gateway.yaml` 那個 `git_version` label 所依賴的 `fieldRef` 空間——不會讓 apply 失敗，只會讓 `service.version` 悄悄從新的 span 裡消失。理由寫在 `k8s/kustomization.yaml` 的註解裡。
