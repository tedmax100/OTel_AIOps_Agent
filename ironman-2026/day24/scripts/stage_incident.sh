#!/usr/bin/env bash
# Stage the payment-decline incident so an eval run has a real before/after in
# the data: a healthy v2.4.1 window, then the flag flip + v2.5.0 rollout, then a
# decline spike. Everything stays inside one hour because Tempo's
# block_retention is 1h — a wider staging window makes the trace step of the
# investigation impossible, not just slow.
#
# Prereqs: k3d demo stack running, and these port-forwards live:
#   kubectl -n demo port-forward svc/webapp 8002:8000
#   kubectl -n demo port-forward svc/payment-service 8001:8000
#
# Usage: ./stage_incident.sh [healthy_minutes] [incident_minutes]
set -euo pipefail

HEALTHY_MIN="${1:-8}"
INCIDENT_MIN="${2:-12}"
NS=demo
PAY="${PAYMENT_URL:-http://localhost:8001}"
# demo-services lives in the o11y-bench repo, not this one — point LOAD at its
# scripts/load.sh (default assumes both repos are checked out side by side).
LOAD="${LOAD:-$(cd "$(dirname "$0")" && pwd)/../../../../o11y-bench/demo-services/scripts/load.sh}"

flag() {  # flag <true|false>
  kubectl -n "$NS" create configmap payment-flags \
    --from-literal=flags.json="{\"payment_use_new_validator\": $1}" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
}

version() {  # version <git_version>
  kubectl -n "$NS" patch deployment payment-service --type=merge \
    -p "{\"spec\":{\"template\":{\"metadata\":{\"labels\":{\"git_version\":\"$1\"}}}}}" >/dev/null
  kubectl -n "$NS" rollout status deployment/payment-service --timeout=120s
}

echo "[stage] healthy window: v2.4.1, validator off"
flag false
version v2.4.1

bash "$LOAD" 5 $((HEALTHY_MIN * 60)) &
LOAD_PID=$!
sleep $((HEALTHY_MIN * 60))
wait "$LOAD_PID" 2>/dev/null || true

echo "[stage] bad deploy: v2.5.0, validator on"
flag true
version v2.5.0

bash "$LOAD" 5 $((INCIDENT_MIN * 60)) &
LOAD_PID=$!

# The load script only ever produces even amounts, so it can never trip the
# odd-cents branch. Drive the declines directly at payment-service.
END=$(( $(date +%s) + INCIDENT_MIN * 60 ))
while [ "$(date +%s)" -lt "$END" ]; do
  curl -sS -o /dev/null -X POST "$PAY/charge" -H 'content-type: application/json' \
    -d "{\"order_id\":\"o-$RANDOM\",\"user_id\":\"u-$((RANDOM % 5 + 1))\",\"amount_cents\":$((RANDOM % 5000 * 2 + 1))}" || true
  sleep 1
done
wait "$LOAD_PID" 2>/dev/null || true

echo "[stage] done — incident is in the data as of $(date -u +%Y-%m-%dT%H:%M:%SZ)"
