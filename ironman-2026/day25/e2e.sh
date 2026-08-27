#!/usr/bin/env bash
# One run of the whole chain, in the order it was built:
#
#   1. governance      a new service passes (or fails) the onboarding checklist
#   2. intent          the declared steady state compiles into alert rules
#   3. signal plane    service-owned declarations compile; nothing leaks the answer
#   4. investigation   an alert goes in, a diagnosis + proposal comes out
#   5. evaluation      the same agent is scored against fixed data
#
# Stages 1-4 run against the live k3d cluster; stage 5 boots the prebuilt stack
# image, which publishes 9090/3100/3200 itself and therefore cannot coexist with
# the port-forwards the earlier stages need. That is why they are in this order,
# and why stage 5 shuts the forwards down first.
#
# Usage (from the OTel_AIOps_Agent repo root):
#   AGENT_URL=http://localhost:8090 WEBHOOK_SECRET=… ./ironman-2026/day25/e2e.sh
set -uo pipefail

AGENT_DIR="${AGENT_DIR:-../o11y-bench/aiops-agent/service}"
AGENT_URL="${AGENT_URL:-http://localhost:8090}"
WEBHOOK_SECRET="${WEBHOOK_SECRET:-}"
SERVICE="${SERVICE:-payment-service}"

pass=0
fail=0
declare -a SUMMARY

stage() {  # stage <name> <command...>
  local name="$1"; shift
  printf '\n\033[1m── %s ──\033[0m\n' "$name"
  if "$@"; then
    pass=$((pass + 1)); SUMMARY+=("ok   $name")
  else
    fail=$((fail + 1)); SUMMARY+=("FAIL $name")
  fi
}

# --- 1. governance ----------------------------------------------------------
s1_governance() {
  python3 ironman-2026/day12/verify_onboarding.py ironman-2026/day12/shipping-v1 | tail -3
}

# --- 2. intent --------------------------------------------------------------
s2_intent() {
  python3 ironman-2026/day11/compile_intent.py ironman-2026/day11/intent/steady-state.yaml \
    | grep -E '^  - alert:|^    expr:' | head -6
}

# --- 3. signal plane --------------------------------------------------------
s3_signal_plane() {
  (cd "$AGENT_DIR" && uv run python -m app.signals.compile) || return 1
  # The ruler has to be clean before any score means anything (Day22).
  (cd "$AGENT_DIR" && uv run python "$OLDPWD/ironman-2026/day21/leakcheck.py" | tail -2)
}

# --- 4. investigation -------------------------------------------------------
s4_investigate() {
  [ -n "$WEBHOOK_SECRET" ] || { echo "WEBHOOK_SECRET not set"; return 1; }
  local now
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  curl -sS -X POST "$AGENT_URL/webhook/alert" \
    -H 'content-type: application/json' -H "x-webhook-secret: $WEBHOOK_SECRET" \
    -d "{\"alerts\":[{\"labels\":{\"alertname\":\"payment-decline-rate-high\",\"service_name\":\"$SERVICE\",\"severity\":\"critical\"},\"annotations\":{\"summary\":\"$SERVICE declined rate above objective\"},\"startsAt\":\"$now\"}]}" \
    || return 1
  echo
  # The webhook returns immediately; the investigation runs in the background.
  for _ in $(seq 1 60); do
    sleep 5
    if curl -sS "$AGENT_URL/investigations?limit=1" | grep -q '"summary": *"[^"]'; then
      break
    fi
  done
  python3 ironman-2026/day25/report.py investigation "$AGENT_URL"
}

s4b_proposal() {
  python3 ironman-2026/day25/report.py proposal "$AGENT_URL"
}

# --- 5. evaluation ----------------------------------------------------------
s5_evaluate() {
  pkill -f "port-forward svc/prometheus" 2>/dev/null
  pkill -f "port-forward svc/loki" 2>/dev/null
  pkill -f "port-forward svc/tempo" 2>/dev/null
  sleep 2
  (cd "$AGENT_DIR" && uv run python -m app.eval run --stack -n 1) | tail -12
}

stage "1. governance: shipping-v1 onboarding checklist" s1_governance
stage "2. intent: steady state -> alert rules" s2_intent
stage "3. signal plane: compile + leak check" s3_signal_plane
stage "4. investigation: alert -> diagnosis" s4_investigate
stage "4b. next step: the proposal and its footprint" s4b_proposal
stage "5. evaluation: scored against fixed data" s5_evaluate

printf '\n\033[1m── end to end ──\033[0m\n'
for line in "${SUMMARY[@]}"; do echo "  $line"; done
printf '\n%d ok, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
