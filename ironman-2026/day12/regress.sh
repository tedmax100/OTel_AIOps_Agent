#!/usr/bin/env bash
# Day12：把前面十一天的治理資產跑一遍，確認它們「還擋得住」。
#
# 這支腳本不呼叫任何 LLM。它斷言的全部是離開碼跟輸出字串，所以跑得快、
# 結果穩定、可以進 CI。
#
# 重點不是「這些指令會不會通過」，是**該紅的還會不會紅**。所以底下有一半
# 以上的斷言，預期的離開碼是 1。
#
# 用法（從 repo 根目錄跑）：
#     bash ironman-2026/day12/regress.sh

set -uo pipefail

PASS=0
FAIL=0
EXPECT_ZERO=0
EXPECT_NONZERO=0

# expect_exit <預期離開碼> <說明> <指令...>
expect_exit() {
  local want="$1" label="$2"
  shift 2
  local out got
  out=$("$@" 2>&1)
  got=$?
  if [ "$want" -eq 0 ]; then EXPECT_ZERO=$((EXPECT_ZERO + 1)); else EXPECT_NONZERO=$((EXPECT_NONZERO + 1)); fi
  if [ "$got" -eq "$want" ]; then
    printf '  ✓ %-58s exit=%s\n' "$label" "$got"
    PASS=$((PASS + 1))
  else
    printf '  ✗ %-58s exit=%s（預期 %s）\n' "$label" "$got" "$want"
    printf '%s\n' "$out" | tail -3 | sed 's/^/      /'
    FAIL=$((FAIL + 1))
  fi
}

# expect_output <預期出現的字串> <說明> <指令...>
expect_output() {
  local needle="$1" label="$2"
  shift 2
  local out
  out=$("$@" 2>&1)
  if printf '%s' "$out" | grep -qF -- "$needle"; then
    printf '  ✓ %-58s 找到 %s\n' "$label" "「${needle:0:28}」"
    PASS=$((PASS + 1))
  else
    printf '  ✗ %-58s 沒找到 %s\n' "$label" "「${needle:0:28}」"
    printf '%s\n' "$out" | tail -3 | sed 's/^/      /'
    FAIL=$((FAIL + 1))
  fi
}

# 探針：registry 真的被讀進來了嗎（Day5 那個 -r . 假綠燈的教訓）
group_count() {
  weaver registry stats -r "$1" 2>/dev/null | grep -oE '[0-9]+ groups' | head -1 | cut -d' ' -f1
}

expect_groups() {
  local registry="$1" label="$2"
  local n
  n=$(group_count "$registry")
  n=${n:-0}
  if [ "$n" -ge 1 ]; then
    printf '  ✓ %-58s %s groups\n' "$label" "$n"
    PASS=$((PASS + 1))
  else
    printf '  ✗ %-58s 讀到 0 個 group，這道檢查什麼都沒在檢查\n' "$label"
    FAIL=$((FAIL + 1))
  fi
}

echo "== 探針：這些檢查真的讀得到東西"
expect_groups ironman-2026/day06/registry      "day06 drift registry"
expect_groups ironman-2026/day07/registry      "day07 收斂後的 registry"
expect_groups ironman-2026/day08/base          "day08 base"
expect_groups ironman-2026/day08/team-orders   "day08 team-orders（含分層）"
expect_groups ironman-2026/day09/base-v2       "day09 base-v2"
expect_groups ironman-2026/day11/registry      "day11 registry"

echo
echo "== 該綠的還是綠的"
expect_exit 0 "day07 registry ＋ 命名 policy" \
  weaver registry check -r ironman-2026/day07/registry -p ironman-2026/day07/policies
expect_exit 0 "day08 分層解析得開" \
  weaver registry check -r ironman-2026/day08/team-orders
expect_exit 0 "day09 兩個版本各自都合法" \
  weaver registry check -r ironman-2026/day09/base-v2
expect_exit 0 "day11 意圖編得出 alert rule" \
  python3 ironman-2026/day11/compile_intent.py ironman-2026/day11/intent/steady-state.yaml
expect_exit 0 "day11 變更意圖編得出驗證查詢" \
  python3 ironman-2026/day11/compile_intent.py ironman-2026/day11/intent/change.yaml
expect_exit 0 "day10 MCP server 答得出東西" \
  python3 ironman-2026/day10/mcp_probe.py ironman-2026/day09/base-v2

echo
echo "== 該紅的還會紅嗎（這一段才是重點）"
expect_exit 1 "day06 命名漂移擋得住" \
  weaver registry check -r ironman-2026/day06/registry -p ironman-2026/day07/policies
expect_exit 1 "day08 同名兩份定義擋得住" \
  weaver registry check -r ironman-2026/day08/team-orders -p ironman-2026/day08/policies
expect_exit 1 "day08 孤兒在 include-unreferenced 下現形" \
  weaver registry check -r ironman-2026/day08/team-orders --include-unreferenced
expect_exit 1 "day09 三種靜音變更被 policy 抓到" \
  weaver registry check -r ironman-2026/day09/base-v2 \
    --baseline-registry ironman-2026/day09/base-v1 -p ironman-2026/day09/policies
expect_exit 1 "day09 --future 把警告變成錯誤" \
  weaver registry check -r ironman-2026/day09/future-demo --future
expect_exit 1 "day11 意圖裡的大小寫錯誤擋得住" \
  python3 ironman-2026/day11/compile_intent.py ironman-2026/day11/intent/steady-state-broken.yaml
expect_exit 1 "day07 live-check 抓得到型別對不上" \
  weaver registry live-check -r ironman-2026/day09/team-orders \
    --input-source ironman-2026/day09/live-check/samples.json
expect_exit 1 "day07 live-check 抓得到還在送的舊欄位" \
  weaver registry live-check -r ironman-2026/day07/registry \
    --input-source ironman-2026/day07/live-check/samples.json

echo
echo "== 訊息本身也要能讓人自己修好"
expect_output "duplicate_concept" "day06 講得出是哪一條規則" \
  weaver registry check -r ironman-2026/day06/registry -p ironman-2026/day07/policies
expect_output "registry.acme.biz" "day08 講得出跟誰衝突" \
  weaver registry check -r ironman-2026/day08/team-orders --include-unreferenced
expect_output "合法的是：authorized, declined, gateway_error" "day11 講得出合法值有哪些" \
  python3 ironman-2026/day11/compile_intent.py ironman-2026/day11/intent/steady-state-broken.yaml
expect_output "::error file=" "day07 產得出 GitHub annotation" \
  weaver registry check -r ironman-2026/day06/registry -p ironman-2026/day07/policies \
    --diagnostic-format gh_workflow_command --diagnostic-stdout

echo
echo "== 已知的缺口：這些現在就是不會擋，寫下來才不會誤以為有人在守"
expect_exit 0 "registry diff 對型別／值域／語意改變靜音" \
  weaver registry diff -r ironman-2026/day09/base-v2 --baseline-registry ironman-2026/day09/base-v1
expect_exit 0 "live-check 對被移除的 enum 值只給 information" \
  weaver registry live-check -r ironman-2026/day09/team-orders \
    --input-source ironman-2026/day12/fixtures/removed-enum-value.json
expect_exit 0 "live-check 不管 span 名字是不是亂編的" \
  weaver registry live-check -r ironman-2026/day07/registry \
    --input-source ironman-2026/day12/fixtures/made-up-span.json
expect_output "not found in registry" "MCP 對分層 registry 查不到 base 的屬性" \
  python3 ironman-2026/day12/mcp_layered_probe.py

echo
echo "== 生成物跟 registry 有沒有走散"
GEN_TMP=$(mktemp -d)
weaver registry generate -r ironman-2026/day11/registry \
  --templates ironman-2026/day11/templates python "$GEN_TMP" >/dev/null 2>&1
expect_exit 0 "day11 generated/ 是最新的" \
  diff -r -x __pycache__ ironman-2026/day11/generated "$GEN_TMP"
rm -rf "$GEN_TMP"

echo
echo "────────────────────────────────────────────────────────────"
printf '%s 條斷言：%s 通過，%s 失敗\n' "$((PASS + FAIL))" "$PASS" "$FAIL"
printf '其中預期離開碼非 0 的有 %s 條，預期 0 的有 %s 條\n' "$EXPECT_NONZERO" "$EXPECT_ZERO"
[ "$FAIL" -eq 0 ] || exit 1
