# Day3（GitOps 收尾那一節）— Operator 設定進 GitOps

對應文章：Day3 的最後一節「收尾：讓這些 CR 進得了 GitOps」（2026 鐵人賽《AIOps with OpenTelemetry》）

這個資料夾是那一節做完之後、整組 demo stack 的完整快照，不是後續變動的 diff。
完整跑法／架構說明見 [STACK-README.md](./STACK-README.md)。

## 這天的變動（相對 [`../day05/`](../day05/)）

- `k8s/kustomization.yaml`：新增，把「哪些檔案算數」宣告成一份可被單一指令解析的清單。
- `scripts/up.sh`：從逐檔案 `kubectl apply -f` 改成 `kubectl kustomize k8s/ | kubectl apply -f -`，
  跟 Argo CD／Flux 指向這個目錄時會做的事一致。
- `GITOPS-REVIEW.md`：新增，寫給 reviewer 的五條人肉 checklist（文章裡誠實說明它還不是自動防護）。

沒有加 `commonLabels`——`23-api-gateway.yaml` 的 Pod 有一個 `git_version` label 透過 Downward API
餵進 `OTEL_RESOURCE_ATTRIBUTES`，`commonLabels` 會蓋到這個 `fieldRef` 依賴的空間。
