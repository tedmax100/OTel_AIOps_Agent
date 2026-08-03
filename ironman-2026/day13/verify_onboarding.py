#!/usr/bin/env python3
"""新服務上線 checklist：每一項都真的執行一次工具，不是問你「有沒有做」。

用法（從 repo 根目錄跑）：

    python3 ironman-2026/day13/verify_onboarding.py ironman-2026/day13/shipping-v0

參數是一個服務目錄，底下要有 `registry/`，可以有 `intent/`。
每一項失敗都會印出下一步該做什麼，這是這支腳本存在的重點：
被擋下來的人不用來問平台團隊。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

DAY07_POLICIES = "ironman-2026/day07/policies"
DAY08_POLICIES = "ironman-2026/day08/policies"
COMPILE_INTENT = "ironman-2026/day11/compile_intent.py"


class Report:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0

    def ok(self, label: str, detail: str = "") -> None:
        print(f"  ✓ {label}" + (f"  {detail}" if detail else ""))
        self.passed += 1

    def no(self, label: str, why: str, next_step: str) -> None:
        print(f"  ✗ {label}")
        print(f"      問題：{why}")
        print(f"      下一步：{next_step}")
        self.failed += 1


ANSI = re.compile(r"\x1b\[[0-9;]*m|\x1b\]8;;[^\x1b]*\x1b\\")


def run(*args: str) -> tuple[int, str]:
    """回傳 (離開碼, 去掉顏色碼的 stdout+stderr)。"""
    result = subprocess.run(args, capture_output=True, text=True)
    return result.returncode, ANSI.sub("", result.stdout + result.stderr)


def run_json(*args: str) -> tuple[int, str]:
    """只要 stdout，因為 weaver 的訊息走 stderr（Day7 那個坑的另一面）。"""
    result = subprocess.run(args, capture_output=True, text=True)
    return result.returncode, result.stdout


def resolved_groups(registry: str) -> list[dict[str, Any]]:
    code, out = run_json("weaver", "registry", "resolve", "-r", registry, "--format", "json")
    if code != 0:
        return []
    data = json.loads(out)
    return data.get("registry", data).get("groups", [])


def attributes_of(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for group in groups:
        for attr in group.get("attributes", []):
            seen.setdefault(attr["name"], attr)
    return list(seen.values())


def is_enum(attr: dict[str, Any]) -> bool:
    return isinstance(attr.get("type"), dict) and "members" in attr["type"]


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2

    service_dir = Path(sys.argv[1])
    registry = str(service_dir / "registry")
    intent_dir = service_dir / "intent"
    report = Report()

    print(f"# {service_dir.name} 上線檢查\n")

    # --- 1-3：這份 registry 存在、讀得到、而且合法 ---------------------------
    print("## 基本")

    manifest = Path(registry) / "manifest.yaml"
    if manifest.is_file():
        report.ok("1. registry/manifest.yaml 存在")
    else:
        report.no(
            "1. registry/manifest.yaml 存在",
            f"找不到 {manifest}",
            "從 ironman-2026/day08/base/manifest.yaml 抄一份改名字跟 schema_url",
        )
        return 1

    code, out = run("weaver", "registry", "stats", "-r", registry)
    count = 0
    for token in out.split():
        if token.isdigit():
            count = int(token)
            break
    if count >= 1:
        report.ok("2. registry 真的被讀進來", f"{count} 個 group")
    else:
        report.no(
            "2. registry 真的被讀進來",
            "解析出 0 個 group，後面每一項檢查都會是假的綠燈",
            "確認 -r 指到有 manifest.yaml 的那一層，而不是 model/ 那一層",
        )
        return 1

    code, out = run("weaver", "registry", "check", "-r", registry)
    if code == 0:
        report.ok("3. registry check 通過")
    else:
        report.no("3. registry check 通過", out.strip().splitlines()[-1], "照上面的診斷訊息修")

    # --- 4-5：命名與分層 ----------------------------------------------------
    print("\n## 命名與分層")

    code, out = run("weaver", "registry", "check", "-r", registry, "-p", DAY07_POLICIES)
    if code == 0:
        report.ok("4. 命名規則通過（camelCase／namespace／同概念兩個名字）")
    else:
        offenders = [line.split("attr=")[-1].strip() for line in out.splitlines() if "attr=" in line]
        report.no(
            "4. 命名規則通過",
            "違規的欄位：" + ", ".join(sorted(set(offenders))),
            "改成 snake_case、補上 namespace（例如 shipping.status）",
        )

    manifest_text = manifest.read_text()
    if "dependencies:" in manifest_text:
        report.ok("5. 有宣告 base registry 的 dependency")
    else:
        report.no(
            "5. 有宣告 base registry 的 dependency",
            "manifest.yaml 裡沒有 dependencies",
            "加上 ironman-2026/day08/base，然後把共用欄位改成 ref",
        )

    code, out = run("weaver", "registry", "check", "-r", registry, "-p", DAY08_POLICIES)
    if code == 0:
        report.ok("6. 沒有跟別人衝突的重複定義")
    else:
        offenders = [line.split("attr=")[-1].strip() for line in out.splitlines() if "attr=" in line]
        report.no(
            "6. 沒有跟別人衝突的重複定義",
            "同名而定義不同：" + ", ".join(sorted(set(offenders))),
            "刪掉自己這份，改用 ref 引用 base 的定義",
        )

    # --- 7-10：這份 schema 對 agent 有多少價值 ------------------------------
    print("\n## 對 agent 的可用性")

    groups = resolved_groups(registry)
    attrs = attributes_of(groups)

    missing_brief = [a["name"] for a in attrs if not a.get("brief")]
    if not missing_brief:
        report.ok("7. 每個 attribute 都有 brief", f"{len(attrs)} 個")
    else:
        report.no(
            "7. 每個 attribute 都有 brief",
            "沒有 brief：" + ", ".join(missing_brief),
            "brief 是 agent 唯一能知道這個欄位代表什麼的地方，補一句話就好",
        )

    # 值域：名字看起來像狀態欄位的，應該是 enum
    status_like = [a for a in attrs if a["name"].split(".")[-1] in {"status", "outcome", "state", "result"}]
    not_enum = [a["name"] for a in status_like if not is_enum(a)]
    if not not_enum:
        enum_names = [a["name"] for a in attrs if is_enum(a)]
        report.ok("8. 狀態類欄位都把值域寫進 schema", f"enum：{', '.join(enum_names) or '（沒有）'}")
    else:
        report.no(
            "8. 狀態類欄位都把值域寫進 schema",
            "還是 string：" + ", ".join(not_enum),
            "改成 type.members，這是 agent 唯一能事先知道有哪幾種值的來源",
        )

    metrics = [g for g in groups if g.get("metric_name")]
    bad_unit = [g["metric_name"] for g in metrics if g.get("unit") in (None, "", "1")]
    if metrics and not bad_unit:
        report.ok("9. 每個 metric 都有語意單位", f"{len(metrics)} 個")
    elif not metrics:
        report.no("9. 每個 metric 都有語意單位", "這份 registry 沒有定義任何 metric", "至少定義一個服務的核心 metric")
    else:
        report.no(
            "9. 每個 metric 都有語意單位",
            "單位是空的或 1：" + ", ".join(bad_unit),
            "用 UCUM 的計數單位，例如 {shipment}，agent 才知道這個數字在數什麼",
        )

    no_owner = [
        g["metric_name"]
        for g in metrics
        if not (g.get("annotations") or {}).get("intent", {}).get("owner")
    ]
    if metrics and not no_owner:
        report.ok("10. 每個 metric 都標了 owner")
    else:
        report.no(
            "10. 每個 metric 都標了 owner",
            "沒有 annotations.intent.owner：" + (", ".join(no_owner) or "（沒有 metric）"),
            "在 metric group 上加 annotations.intent.owner，告警才知道要找誰",
        )

    # --- 11-13：意圖與產出 --------------------------------------------------
    print("\n## 意圖與產出")

    intents = sorted(intent_dir.glob("*.yaml")) if intent_dir.is_dir() else []
    if intents:
        report.ok("11. 有寫下這個服務的穩定狀態意圖", f"{len(intents)} 份")
    else:
        report.no(
            "11. 有寫下這個服務的穩定狀態意圖",
            f"{intent_dir} 底下沒有任何 YAML",
            "從 ironman-2026/day11/intent/steady-state.yaml 抄一份，寫下什麼叫做正常",
        )

    if intents:
        broken = []
        for path in intents:
            code, out = run("python3", COMPILE_INTENT, str(path))
            if code != 0:
                broken.append(f"{path.name}: {out.strip().splitlines()[-1] if out.strip() else '編譯失敗'}")
        if not broken:
            report.ok("12. 意圖編得出 alert rule")
        else:
            report.no("12. 意圖編得出 alert rule", "；".join(broken), "照錯誤訊息裡列出的合法值改")
    else:
        report.no("12. 意圖編得出 alert rule", "沒有意圖可以編", "先做完第 11 項")

    code, out = run(
        "weaver", "registry", "generate", "-r", registry,
        "--templates", "ironman-2026/day11/templates", "python", "/tmp/onboarding-gen",
    )
    if code == 0:
        report.ok("13. 生得出型別安全的常數與 enum")
    else:
        report.no("13. 生得出型別安全的常數與 enum", out.strip().splitlines()[-1], "看樣板跟 registry 哪一邊對不上")

    total = report.passed + report.failed
    print(f"\n{'─' * 60}")
    print(f"{report.passed}/{total} 通過")
    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
