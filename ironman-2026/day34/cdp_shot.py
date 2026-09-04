"""Screenshot a logged-in Grafana page with headless Chrome + CDP.

Putting `http://user:pass@host/...` in the URL does NOT work for the Grafana
app shell: its frontend builds fetch() requests from `window.location`, and
Chrome refuses to construct a fetch from a URL that carries credentials — the
page just shows "Failed to load dashboard". The fix is to log in for real
(POST /login, which returns a `grafana_session` cookie) and inject that
cookie into the headless tab via CDP's Network.setCookie before navigating.

    curl -s -c /tmp/gf_cookies.txt -X POST http://localhost:13001/login \\
      -H 'Content-Type: application/json' -d '{"user":"admin","password":"admin"}'
    export GRAFANA_SESSION_COOKIE=$(grep grafana_session /tmp/gf_cookies.txt | awk '{print $NF}')

    python cdp_shot.py <url> <out.png> [wait_seconds]
"""

import json
import os
import sys
import time

import requests
import websocket

CDP = "http://127.0.0.1:9222"
COOKIE = os.environ["GRAFANA_SESSION_COOKIE"]
URL = sys.argv[1]
OUT = sys.argv[2]
WAIT_S = float(sys.argv[3]) if len(sys.argv) > 3 else 8
CLIP = json.loads(sys.argv[4]) if len(sys.argv) > 4 else None


def new_tab():
    r = requests.put(f"{CDP}/json/new?about:blank")
    return r.json()


tab = new_tab()
ws_url = tab["webSocketDebuggerUrl"]
ws = websocket.create_connection(ws_url, timeout=30)
_id = 0


def send(method, params=None):
    global _id
    _id += 1
    ws.send(json.dumps({"id": _id, "method": method, "params": params or {}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == _id:
            return msg


send("Network.enable")
send(
    "Network.setCookie",
    {
        "name": "grafana_session",
        "value": COOKIE,
        "domain": "localhost",
        "path": "/",
        "httpOnly": True,
    },
)
send("Page.enable")
send("Emulation.setDeviceMetricsOverride", {"width": 1600, "height": 1400, "deviceScaleFactor": 1, "mobile": False})
send("Page.navigate", {"url": URL})
time.sleep(WAIT_S)

# grow the viewport to the real content height so the screenshot isn't cropped
metrics = send("Page.getLayoutMetrics")
height = int(metrics["result"]["cssContentSize"]["height"])
height = max(height, 1200)
send("Emulation.setDeviceMetricsOverride", {"width": 1600, "height": height, "deviceScaleFactor": 1, "mobile": False})
time.sleep(1.5)

params = {"format": "png"}
if CLIP:
    params["clip"] = {**CLIP, "scale": 1}
shot = send("Page.captureScreenshot", params)
data = shot["result"]["data"]
with open(OUT, "wb") as f:
    import base64
    f.write(base64.b64decode(data))
print("saved", OUT, "height", height)
send("Page.close")
ws.close()
