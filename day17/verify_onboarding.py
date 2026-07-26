#!/usr/bin/env python3
"""新服務上線 checklist——可執行的版本。

每一項都對應 Day3–Day11 的一個結論，而且都是**跑出來的**，不是勾一個框。
任何一項失敗就 exit 1，訊息裡直接寫「下一步該做什麼」（Day9 的教訓：
一道擋人的 gate 如果不能讓被擋的人自己走出去，維護成本會隨團隊數線性成長）。

用法（從這個 repo 的根目錄跑）：

    python3 day17/verify_onboarding.py day17/services/shipping-v1
    python3 day17/verify_onboarding.py day17/services/shipping-v0    # exit 1
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ANSI = re.compile(r"\x1b\[[0-9;]*m")

WEAVER = os.environ.get("WEAVER", "weaver")
SERVICE_DIR = sys.argv[1].rstrip("/")
REGISTRY = f"{SERVICE_DIR}/registry"

PASS, FAIL, results = "✔", "✗", []


def record(ok: bool, day: str, item: str, detail: str = "", fix: str = "") -> bool:
    results.append((ok, day, item, detail, fix))
    return ok


def run(*args: str) -> tuple[int, str]:
    proc = subprocess.run(args, capture_output=True, text=True)
    return proc.returncode, ANSI.sub("", proc.stdout + proc.stderr)


def check_registry_exists() -> bool:
    ok = os.path.isfile(f"{REGISTRY}/manifest.yaml")
    return record(
        ok, "Day8", "registry 存在（manifest.yaml）",
        REGISTRY if ok else f"找不到 {REGISTRY}/manifest.yaml",
        fix="複製 day17/starter/registry/ 過去，把 <service> 換掉",
    )


def check_schema_url_versioned() -> bool:
    text = open(f"{REGISTRY}/manifest.yaml").read()
    url = next((ln.split(":", 1)[1].strip() for ln in text.splitlines()
                if ln.startswith("schema_url:")), "")
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    ok = bool(url) and any(c.isdigit() for c in tail) and "." in tail
    return record(
        ok, "Day9/10", "schema_url 帶版本號", url or "（沒有 schema_url）",
        fix="結尾補上版本，例如 .../shipping-telemetry/0.1.0——"
            "diff 拿它當版本標籤，MCP 的 provenance.source 也是它",
    )


def check_registry_check() -> bool:
    code, out = run(WEAVER, "registry", "check", "-r", REGISTRY)
    return record(code == 0, "Day5", "registry check 通過", f"exit={code}",
                  fix=out.strip().splitlines()[-1] if code else "")


def check_future() -> bool:
    code, out = run(WEAVER, "registry", "check", "-r", REGISTRY, "--future")
    warnings = [ln.strip() for ln in out.splitlines() if "⚠" in ln or "×" in ln]
    return record(
        code == 0, "Day9", "registry check --future 通過（未來會變嚴的規則）",
        f"exit={code}，{len(warnings)} 條診斷",
        fix="通常是缺 stability、string 缺 examples、或 deprecated 寫成字串",
    )


def check_policies() -> bool:
    ok = True
    for label, policies in (("命名（Day6）", "day10/policies"), ("分層（Day8）", "day13/policies")):
        code, out = run(WEAVER, "registry", "check", "-r", REGISTRY, "-p", policies)
        msgs = [ln.split("Message   : ")[1].strip() for ln in out.splitlines() if "Message   :" in ln]
        ok &= record(
            code == 0, "Day6/8", f"policy 通過：{label}", f"exit={code}",
            fix="；".join(msgs) if msgs else "",
        )
    return ok


def check_group_count() -> bool:
    code, out = run(WEAVER, "registry", "stats", "-r", REGISTRY, "--include-unreferenced", "true")
    count = 0
    for line in out.splitlines():
        if "groups" in line:
            count = int("".join(c for c in line.split("groups")[0] if c.isdigit()) or 0)
            break
    return record(count > 0, "Day5/7", "假綠燈探針：group 數 > 0", f"{count} groups",
                  fix="registry check 綠燈但 group 是 0，通常是 -r 指到錯的目錄")


def check_enum_members() -> bool:
    """每個「看起來是狀態」的欄位都該是 enum：agent 唯一的值域來源。"""
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(WEAVER, "registry", "generate", "-r", REGISTRY,
                        "--templates", "day16/templates", "python", tmp,
                        "--include-unreferenced", "true")
        if code != 0:
            return record(False, "Day11", "生成物產得出來", f"exit={code}", fix=out.strip()[-200:])
        data = json.load(open(f"{tmp}/registry.json"))
    suspects, enums = [], []
    for group in data["groups"]:
        for attr in group.get("attributes", []):
            name, attr_type = attr["name"], attr.get("type")
            if isinstance(attr_type, dict):
                enums.append(name)
            # 正規化之後再比對字尾，否則 shippingStatus 這種寫法會躲過這一項
            # （第一版就是這樣漏掉的，見文章）
            elif any(
                re.sub(r"[._]", "", name).lower().endswith(w)
                for w in ("status", "state", "outcome", "result", "kind", "type")
            ):
                suspects.append(name)
    return record(
        not suspects, "Day5/10", "狀態類欄位都宣告了 enum members",
        f"{len(enums)} 個 enum" + (f"，可疑：{', '.join(suspects)}" if suspects else ""),
        fix="把它改成 type.members，那是 LLM 唯一能事先知道值域的來源",
    )


def check_intent() -> bool:
    path = f"{SERVICE_DIR}/intent/steady-state.yaml"
    if not os.path.isfile(path):
        return record(False, "Day11", "有宣告穩定狀態意圖", "找不到 intent/steady-state.yaml",
                      fix="複製 day17/starter/intent/ 過去；why 跟 first_check 不要留空")
    with tempfile.TemporaryDirectory() as tmp:
        run(WEAVER, "registry", "generate", "-r", REGISTRY, "--templates", "day16/templates",
            "python", tmp, "--include-unreferenced", "true")
        code, out = run(sys.executable, "day16/compile_intent.py", path, f"{tmp}/registry.json")
    detail = next((ln for ln in out.splitlines() if ln.startswith("✗")), f"exit={code}")
    return record(code == 0, "Day11", "意圖編譯得過（欄位名對得上 registry）", detail,
                  fix="意圖裡的 metric／dimension／值必須存在於 registry")


def check_intent_has_why() -> bool:
    path = f"{SERVICE_DIR}/intent/steady-state.yaml"
    if not os.path.isfile(path):
        return record(False, "Day11", "意圖的 why / first_check 有填", "（沒有意圖檔案）")
    text = open(path).read()
    placeholders = [p for p in ("寫清楚：", "因為這很重要", "<service>", "<team>") if p in text]
    return record(
        not placeholders, "Day11", "意圖的 why / first_check 有填（不是範本佔位字）",
        f"殘留佔位字：{', '.join(placeholders)}" if placeholders else "已填寫",
        fix="why 要寫「誰會痛、數字怎麼來的」，first_check 要寫「第一個該打開什麼」",
    )


def check_mcp_config() -> bool:
    path = f"{SERVICE_DIR}/.mcp.json"
    if not os.path.isfile(path):
        return record(False, "Day10", "有 .mcp.json（registry 可被 agent 查）", "找不到 .mcp.json",
                      fix="複製 day17/starter/.mcp.json 過去")
    conf = json.load(open(path))
    args = conf.get("mcpServers", {}).get("semconv", {}).get("args", [])
    has_flag = "--include-unreferenced" in args and "true" in args
    points_here = REGISTRY in args
    return record(
        has_flag and points_here, "Day10", "有 .mcp.json 且設定正確",
        f"registry={'✔' if points_here else '✗'} include-unreferenced={'✔' if has_flag else '✗'}",
        fix="漏了 --include-unreferenced true 的話，agent 查繼承來的欄位會得到「不存在」",
    )


def check_mcp_answers() -> bool:
    """真的把 MCP server 叫起來問一個問題——設定對不代表答得出來。"""
    if not shutil.which("python3"):
        return record(False, "Day10", "MCP 真的答得出來", "找不到 python3")
    query = '[{"name":"browse_namespace","arguments":{}}]'
    code, out = run(sys.executable, "day15/mcp_probe.py", REGISTRY, query,
                    "--include-unreferenced", "true")
    total = 0
    for line in out.splitlines():
        if "total_attribute_count" in line:
            total = int("".join(c for c in line.split("total_attribute_count")[1][:12] if c.isdigit()) or 0)
            break
    return record(total > 0, "Day10", "MCP 真的答得出來（browse 有東西）",
                  f"total_attribute_count={total}",
                  fix="0 個的話先確認 --include-unreferenced true 有沒有帶上")


def check_ci_workflow() -> bool:
    candidates = [f"{SERVICE_DIR}/ci/semconv-gate.yml", ".github/workflows/semconv-gate.yml"]
    path = next((p for p in candidates if os.path.isfile(p)), None)
    if not path:
        return record(False, "Day7", "有 CI gate workflow", "找不到 semconv-gate.yml",
                      fix="複製 day17/starter/ci/semconv-gate.yml")
    text = open(path).read()
    required = {
        "版本釘死": "WEAVER_VERSION" in text,
        "sha256 驗證": "sha256sum" in text,
        "--diagnostic-stdout": "--diagnostic-stdout" in text,
        "group 數探針": "stats" in text,
        "failure() 補印": "if: failure()" in text,
    }
    missing = [k for k, v in required.items() if not v]
    return record(not missing, "Day7", "CI gate 包含四個必要元素",
                  f"缺：{', '.join(missing)}" if missing else "齊全",
                  fix="這四項都是踩過的坑，少一項 gate 會安靜失效")


CHECKS = [
    check_registry_exists, check_schema_url_versioned, check_registry_check, check_future,
    check_policies, check_group_count, check_enum_members,
    check_intent, check_intent_has_why, check_mcp_config, check_mcp_answers, check_ci_workflow,
]


def main() -> int:
    print(f"新服務上線 checklist：{SERVICE_DIR}\n")
    if not check_registry_exists():
        print(f"{FAIL} 連 registry 都沒有，後面不用跑了")
        return 1
    for check in CHECKS[1:]:
        check()

    width = max(len(item) for _, _, item, _, _ in results)
    for ok, day, item, detail, _ in results:
        print(f"  {PASS if ok else FAIL} [{day:<9}] {item:<{width}}  {detail}")
    failed = [(item, fix) for ok, _, item, _, fix in results if not ok]
    print()
    if failed:
        print(f"{FAIL} {len(failed)}/{len(results)} 項未通過，下一步：")
        for item, fix in failed:
            print(f"  - {item}\n      → {fix}")
        return 1
    print(f"{PASS} {len(results)}/{len(results)} 項全部通過，這個服務可以上線了")
    return 0


if __name__ == "__main__":
    sys.exit(main())
