# Day34（番外）：活著，不等於答得對

這篇不算在鐵人賽三十三天裡，是收尾之後才補的。文章在
[`ironman-2026/day34.md`](../day34.md)。

這篇的核心案例來自一次真的探測：對 `/chat` 問了一句「order-service 最近的延遲是不是變高了」，
拿到的答案信心 0.9、引用了 `histogram_quantile(0.95, ...)` 算出來的 p95 ≈ 4.75 ms，而這條
PromQL 用的 histogram（`http_server_duration_milliseconds`）正是系列前面已經診斷過的
「auto-instrumentation 預設桶太粗，樣本全擠在同一格，`histogram_quantile` 吐出一個跟真實分
佈無關的常數」那個坑（`http_server_duration_bucket_artifact`）。寫這篇的過程中又在
`gen_ai.client.operation.duration` 這個 metric 上撞到同一個病灶的另一個實例。

## 重現步驟

前提：k3d 叢集已經跑著 `demo` namespace（`aiops-agent`／`prometheus`／`tempo`）。

```bash
kubectl -n demo port-forward svc/aiops-agent 18000:8000 &
kubectl -n demo port-forward svc/prometheus 19090:9090 &
kubectl -n demo port-forward svc/tempo 13200:3200 &

# 1. 送一個真的問題，讓它跑一次調查
curl -N -X POST localhost:18000/chat -H 'Content-Type: application/json' \
  -d '{"message":"order-service 最近的延遲是不是變高了？","thread_id":"day34-probe"}'

# 2. 等 metrics 匯出週期過一次（預設 60s），回頭看這筆案子有沒有被判定證據充分
sleep 60
curl -s localhost:18000/todo | python3 -m json.tool

# 3. 查 GenAI 延遲 histogram 的真實桶邊界（會看到 0,5,10,25,50,75,100,250,500,750,1000,2500,5000,7500,10000,+Inf）
curl -s 'localhost:19090/api/v1/query' \
  --data-urlencode 'query=gen_ai_client_operation_duration_seconds_bucket'

# 4. 對照 histogram_quantile 算出來的 p95，跟 Tempo 上每一個 ChatGoogleGenerativeAI.chat span 的真實時長
curl -s 'localhost:19090/api/v1/query' \
  --data-urlencode 'query=histogram_quantile(0.95, sum by (le) (gen_ai_client_operation_duration_seconds_bucket))'
```

## 這篇引用的真實數字是這樣量出來的

- `/todo` 裡那筆 `fp=day34-probe-1788529545` 的原始 JSON，是直接呼叫 `/todo` 拿到的，
  沒有改寫任何欄位（信心、`sufficiency.checks`、答案原文都是接口回傳的原樣）。
- `aiops.tool.calls` 的 disposition 拆分（`query_prometheus` observed=2/empty=2，
  `discover_metrics` observed=2）來自兩次獨立探測（`order-service`、`payment-service`
  各一次）疊加後的 Prometheus 查詢結果，查詢語法見 Day34 之前那版探針
  `chat_probe.py`（同一支腳本這篇繼續沿用）。
- `gen_ai_client_operation_duration_seconds` 的 12 個桶邊界、以及
  `histogram_quantile(0.95, ...) = 4.749999999999999` 是直接對 Prometheus 查出來的。
- 真實的 13 筆 `ChatGoogleGenerativeAI.chat` span 時長（`1.78 / 1.13 / 0.74 / ...`），
  是對兩次探測留下的兩個 trace ID 分別呼叫 Tempo 的 `/api/traces/{id}`，
  抓出所有名字帶 `ChatGoogleGenerativeAI` 的 span，用
  `(endTimeUnixNano - startTimeUnixNano) / 1e9` 算出來的，不是估的。
- `gen_ai_client_token_usage_sum`（input=56652, output=1073）是同一段時間內
  Prometheus 上的累積值，直接查詢得到。
- dashboard 截圖裡「一次調查的形狀」那排（調查次數 2、證據充足率 100%、p95 48.8s、
  平均 pivot 2.5、平均信心 0.45）來自另外兩次真的 headless 調查，見下一節。

驗證環境：`opentelemetry-sdk` 1.42.1、`opentelemetry-instrumentation` 自動版本 0.63b1
（這兩個版本號是從 Prometheus 上 `telemetry_sdk_version` / `telemetry_auto_version`
這兩個 label 讀出來的）。

## 兩次真的 headless 調查（讓左上那五格有數字）

`/chat` 那條路刻意不開 `aiops.investigation` span，所以只靠 `chat_probe.py` 拍出來的
dashboard，左上「一次調查的形狀」整排是 `No data`。為了讓截圖完整，另外對著同一個
pod 直接補跑了兩次告警觸發的 headless 調查（構造出來的 alert payload，不是真的事故，
這件事誠實寫在文章裡）：

```bash
POD=$(kubectl -n demo get pod -l app=aiops-agent -o jsonpath='{.items[0].metadata.name}')

kubectl -n demo exec "$POD" -- /app/.venv/bin/opentelemetry-instrument /app/.venv/bin/python -c "
import asyncio
from app.agent import run_headless

alert = {
    'status': 'firing',
    'labels': {'service_name': 'payment-service', 'alertname': 'day34-demo-alert'},
    'annotations': {'summary': 'payment-service error rate looks elevated'},
}

async def main():
    result = await run_headless(alert, 'day34-headless-otel-1')
    print('OK', result.get('sufficiency', {}).get('sufficient'))

asyncio.run(main())
"
```

兩個坑值得記一筆。**一定要用 `opentelemetry-instrument` 包著跑，不能直接 `python -c`。**
第一次圖省事直接用 `/app/.venv/bin/python -c "..."` 呼叫 `run_headless`，調查真的跑完了、
答案也是真的，但 Prometheus 上一個新 metric 都沒多出來，因為 `telemetry.py` 的
`tracer`/`meter` 是靠容器啟動時 `opentelemetry-instrument` 那層去配置真正的 SDK，
直接開一個新的 Python process 繞過了那層，`get_tracer()`/`get_meter()` 拿到的是
no-op 實作，span 跟 metric 全部安靜地不見了，`run_headless` 完全不知道，也不會報錯。
換成 `opentelemetry-instrument python -c "..."` 之後，因為容器裡 `OTEL_*` 那組環境變數
本來就在，直接就配好了同一套 exporter，metrics 才真的送到 Prometheus。**這跟文章正文
「/healthz 回 200 不代表這次調查是準的」是同一種安靜失效，只是這次失效的是遙測本身，
不是調查的答案。**

第二個坑是 `run_headless()` 只回傳結果字典，不會自動寫進 `/investigations` 那張表
（那是 `webhook.py` 裡 `_investigate_and_sink` 的責任，只有走 `/webhook/alert` 那條
路才會呼叫）。所以這兩筆調查在 Grafana 的 metrics/trace 上找得到，但不會出現在
`GET /investigations` 或 `/todo` 這兩個 API 裡，也不會被記進校準用的案例庫。

payment-service 那次真實跑出了 3 次 pivot：`k8s_change_provenance` 查出這次
rollout 沒動過 pod template 之後，rubric 判定攔下了「歸咎到 v2.5.0」這個答案兩次
（log 裡真的印著 `rubric: answer blames a version the cluster cleared — retrying`），
第三輪才改成「是掛載的 ConfigMap」，最終信心只有 0.30。order-service 那次跑了 2 次
pivot，信心 0.60。兩次平均下來就是截圖上的「平均 pivot 2.5」「平均信心 0.45」。

## dashboard 截圖是怎麼拍的

文章裡那張 `aiops-agent-perf` 的截圖（`weaver-demo/ironman-2026/img/day34-dashboard.png`）
是真的打開瀏覽器拍的，不是排版稿。這台機器上沒有裝 Playwright，用的是系統既有的
`google-chrome` headless 模式 + Chrome DevTools Protocol：

```bash
# 1. 先用 Grafana 的登入 API 換一顆真的 session cookie（admin:admin，見
#    aiops_grafana_local_test_setup 那份記憶）
curl -s -c /tmp/gf_cookies.txt -X POST http://localhost:13001/login \
  -H "Content-Type: application/json" -d '{"user":"admin","password":"admin"}'
# 這個 cookie 檔案裡同時有 grafana_session_expiry 跟 grafana_session 兩行，
# 單純 grep grafana_session 兩行都會中，要用第 6 欄的 cookie 名字精確比對
export GRAFANA_SESSION_COOKIE=$(awk -F'\t' '$6=="grafana_session"{print $7}' /tmp/gf_cookies.txt)

# 2. 啟動一個獨立 profile 的 headless chrome，開 CDP 連接埠
#    注意 --remote-allow-origins=* 這個引號在 zsh 下一定要加，不然被當成 glob 展開成
#    「no matches found」；另外用 shell 的 `&` 背景這個 process 在某些終端環境下會
#    被連帶砍掉，穩定的做法是用你的任務執行器的「背景執行」機制啟動它，不要單純 `&`
google-chrome --headless=new --disable-gpu --no-sandbox \
  --remote-debugging-port=9222 '--remote-allow-origins=*' \
  --window-size=1600,1200 --user-data-dir=/tmp/chrome-profile-day34 about:blank

# 3. 透過 CDP 的 Network.setCookie 把第 1 步拿到的 grafana_session 寫進這個 headless
#    分頁，再 Page.navigate 過去、等圖表真的畫完、抓 Page.getLayoutMetrics 把視窗撐到
#    整頁高度，最後 Page.captureScreenshot
python3 ironman-2026/day34/cdp_shot.py \
  "http://localhost:13001/d/aiops-agent-perf/aiops-agent-e28094-e8aabf-e69fa5-e8a1a8-e78fbe?orgId=1&from=now-6h&to=now&kiosk" \
  dashboard.png 10
```

**在 URL 裡直接寫 `http://admin:admin@host/...` 這條路走不通**：Grafana 前端自己會用
`window.location` 組 fetch request，新版 Chrome 對「URL 帶著帳密」的 fetch 直接拋
`Failed to execute 'fetch'`，畫面卡在 `Failed to load dashboard`。真正能用的路是先拿到
一顆合法的 session cookie，再用 CDP 把它注入瀏覽器分頁，等同於「先登入、再導覽」，跟人
手動點登入頁是同一件事，只是全部自動化。
