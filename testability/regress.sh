#!/usr/bin/env bash
# 治理資產的回歸測試：把前面每一天踩過的坑，變成一組「預期離開碼」的斷言。
#
# 這裡面一次 LLM 呼叫都沒有——全部是確定性的檢查。目的是讓「agent 表現不好」
# 這件事能被歸因：如果這 21 條全綠，agent 還是答錯，那問題在 agent 或 prompt，
# 不在治理資產。
#
# 用法（從這個 repo 的根目錄跑）：
#   ./testability/regress.sh
#   WEAVER=~/.local/bin/weaver ./testability/regress.sh
#
# 每一行的格式：expected_exit <TAB> 說明 <TAB> 指令

set -uo pipefail
WEAVER="${WEAVER:-weaver}"
PY="${PY:-python3}"
pass=0
fail=0

run_case() {
  local expected="$1" desc="$2" cmd="$3"
  local actual
  eval "$cmd" >/dev/null 2>&1
  actual=$?
  if [ "$actual" = "$expected" ]; then
    printf '  \033[32m✔\033[0m %-58s exit=%s\n' "$desc" "$actual"
    pass=$((pass + 1))
  else
    printf '  \033[31m✗\033[0m %-58s exit=%s（預期 %s）\n' "$desc" "$actual" "$expected"
    fail=$((fail + 1))
  fi
}

echo "治理資產回歸測試（無 LLM）"
echo
echo "── 規範本身：定義層的規則還擋得住嗎（Day5-6）"
run_case 1 "命名 policy 抓到 camelCase／缺 namespace" \
  "$WEAVER registry check -r day17/services/shipping-v0/registry -p day10/policies"
run_case 0 "命名 policy 對乾淨的 registry 放行" \
  "$WEAVER registry check -r day17/services/shipping-v1/registry -p day10/policies"
run_case 1 "分層 policy 抓到 signal group 裡 inline 定義的 attribute" \
  "$WEAVER registry check -r day17/services/shipping-v0/registry -p day13/policies"

echo
echo "── 三層驗證模型：每一層都還在它該在的位置（Day9）"
run_case 1 "第一層 hard error：metric_requirement_level 進不去" \
  "$WEAVER registry check -r day14/breaking"
run_case 0 "第二層預設不擋（三個 ⚠、exit 0）" \
  "$WEAVER registry check -r day14/future"
run_case 1 "第二層加 --future 就擋" \
  "$WEAVER registry check -r day14/future --future"
run_case 1 "第三層：attribute 直接消失（v1→v2）" \
  "$WEAVER registry check -r day14/base-v2 --baseline-registry day14/base-v1 -p day14/policies"
run_case 1 "第三層：型別 int→string（diff 靜音的那一格）" \
  "$WEAVER registry check -r day14/base-v3 --baseline-registry day14/base-v1 -p day14/policies"
run_case 1 "第三層：enum member 被拿掉（diff 也靜音）" \
  "$WEAVER registry check -r day14/base-v4 --baseline-registry day14/base-v1 -p day14/policies"
run_case 1 "下游還在用 deprecated 欄位" \
  "$WEAVER registry check -r day14/team-on-v2 -p day14/policies/deprecated_usage.rego"

echo
echo "── 消費端：agent 查得到、意圖編得過（Day10-11）"
run_case 0 "MCP 對分層 registry 答得出東西（total_attribute_count > 0）" \
  "$PY day15/mcp_probe.py day13/team '[{\"name\":\"browse_namespace\",\"arguments\":{}}]' --include-unreferenced=true | grep -qE 'total_attribute_count[^0-9]+[1-9]'"
run_case 0 "生成物產得出來（含繼承的定義）" \
  "$WEAVER registry generate -r day16/registry --templates day16/templates python day16/generated --include-unreferenced=true"
run_case 0 "穩定狀態意圖編得過" \
  "$PY day16/compile_intent.py day16/intent/steady-state.yaml"
run_case 0 "變更意圖編得過" \
  "$PY day16/compile_intent.py day16/intent/change.yaml"
run_case 1 "意圖指到不存在的維度 → 擋" \
  "$PY day16/compile_intent.py day16/intent/steady-state-broken.yaml"
run_case 1 "意圖用了 enum 裡沒有的值（大小寫）→ 擋" \
  "$PY day16/compile_intent.py day16/intent/steady-state-broken2.yaml"

echo
echo "── 真實遙測：程式碼實際送出的東西（Day10）"
run_case 1 "before 的四個欄位有 violation" \
  "$PY day15/run_and_extract.py before --samples | $WEAVER registry live-check -r day14/base-v2 --input-source stdin"
run_case 1 "after 仍有 violation：retry.count 是新增，不是搬移" \
  "$PY day15/run_and_extract.py after --samples | $WEAVER registry live-check -r day14/base-v2 --input-source stdin"
run_case 0 "把 retry.count 定義出來之後才乾淨" \
  "$PY day15/run_and_extract.py after --samples | $WEAVER registry live-check -r day15/team-retry --input-source stdin --include-unreferenced=true"

echo
echo "── checklist 自己（Day13）"
run_case 1 "照抄一半的服務要被擋" \
  "$PY day17/verify_onboarding.py day17/services/shipping-v0"
run_case 0 "補完的服務要放行" \
  "$PY day17/verify_onboarding.py day17/services/shipping-v1"

echo
if [ "$fail" -eq 0 ]; then
  printf '\033[32m✔\033[0m %d/%d 全部符合預期\n' "$pass" "$((pass + fail))"
  exit 0
fi
printf '\033[31m✗\033[0m %d 條不符合預期（共 %d 條）\n' "$fail" "$((pass + fail))"
exit 1
