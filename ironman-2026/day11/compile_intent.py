#!/usr/bin/env python3
"""把機器可讀的意圖，拿 registry 驗證過之後編譯成真的會跑的東西。

輸入是 intent/ 底下的 YAML，輸出是 Prometheus 的 alert rule（穩定狀態意圖）
或部署後的驗證查詢（變更意圖）。registry 在中間扮演的角色是型別檢查器：
意圖裡提到的每一個 metric、每一個 dimension、每一個值，都必須在 registry
裡真的存在，而且大小寫要一模一樣。

用法（從 repo 根目錄跑）：

    python3 ironman-2026/day11/compile_intent.py ironman-2026/day11/intent/steady-state.yaml

驗證失敗時離開碼是 1，而且會把每一條錯誤指到是哪個 objective 的哪個欄位。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


# --- registry 側 -------------------------------------------------------------


def resolve_registry(registry: str) -> dict[str, Any]:
    """跑 `weaver registry resolve`，拿到攤平之後的 schema。"""
    result = subprocess.run(
        ["weaver", "registry", "resolve", "-r", registry, "--format", "json"],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def index_metrics(resolved: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """metric_name -> {dimension 名稱 -> 那個 attribute 的定義}。"""
    groups = resolved.get("registry", resolved).get("groups", [])
    metrics: dict[str, dict[str, Any]] = {}
    for group in groups:
        name = group.get("metric_name")
        if not name:
            continue
        metrics[name] = {
            "group_id": group["id"],
            "instrument": group.get("instrument"),
            "unit": group.get("unit"),
            "annotations": group.get("annotations") or {},
            "dimensions": {a["name"]: a for a in group.get("attributes", [])},
        }
    return metrics


def enum_values(attribute: dict[str, Any]) -> list[str] | None:
    """enum 的合法值域；不是 enum 就回 None。"""
    attr_type = attribute.get("type")
    if isinstance(attr_type, dict) and "members" in attr_type:
        return [m["value"] for m in attr_type["members"]]
    return None


# --- 驗證 --------------------------------------------------------------------


def validate_signal(signal: dict[str, Any], metrics: dict[str, dict[str, Any]], where: str) -> list[str]:
    errors: list[str] = []
    metric_name = signal.get("metric")
    metric = metrics.get(metric_name)
    if metric is None:
        known = ", ".join(sorted(metrics)) or "(這份 registry 沒有任何 metric)"
        errors.append(f"{where}: registry 裡沒有 metric `{metric_name}`。有的是：{known}")
        return errors

    dimension_name = signal.get("dimension")
    if dimension_name is None:
        return errors

    dimension = metric["dimensions"].get(dimension_name)
    if dimension is None:
        known = ", ".join(sorted(metric["dimensions"])) or "(這個 metric 沒有任何 dimension)"
        errors.append(
            f"{where}: metric `{metric_name}` 上沒有 dimension `{dimension_name}`。有的是：{known}"
        )
        return errors

    members = enum_values(dimension)
    for key in ("good_values", "values"):
        for value in signal.get(key, []):
            if members is None:
                errors.append(
                    f"{where}: `{dimension_name}` 不是 enum，沒有值域可以檢查 `{value}`"
                )
            elif value not in members:
                errors.append(
                    f"{where}: `{dimension_name}` 沒有 `{value}` 這個值。"
                    f"合法的是：{', '.join(members)}"
                )
    return errors


# --- 編譯 --------------------------------------------------------------------


def prom_name(metric_name: str, instrument: str | None) -> str:
    """OTel 的 metric 名字換成 Prometheus 那邊的樣子。"""
    base = metric_name.replace(".", "_")
    return f"{base}_total" if instrument == "counter" else base


def prom_label(attribute_name: str) -> str:
    return attribute_name.replace(".", "_")


def compile_objective(objective: dict[str, Any], metrics: dict[str, dict[str, Any]]) -> dict[str, Any]:
    signal = objective["signal"]
    threshold = objective.get("threshold", {})
    metric = metrics[signal["metric"]]
    series = prom_name(signal["metric"], metric["instrument"])
    window = threshold.get("window", "30m")

    if "ratio_min" in threshold:
        label = prom_label(signal["dimension"])
        good = "|".join(signal["good_values"])
        expr = (
            f'sum(rate({series}{{{label}=~"{good}"}}[{window}]))'
            f" / sum(rate({series}[{window}]))"
        )
        condition = f"{expr} < {threshold['ratio_min']}"
    elif "max_seconds" in threshold:
        quantile = threshold.get("quantile", 0.99)
        expr = (
            f"histogram_quantile({quantile},"
            f" sum by (le) (rate({series}_bucket[{window}])))"
        )
        condition = f"{expr} > {threshold['max_seconds']}"
    else:
        raise ValueError(f"{objective['id']}: threshold 看不懂，要有 ratio_min 或 max_seconds")

    owner = metric["annotations"].get("intent", {}).get("owner", "unknown")
    return {
        "alert": objective["id"],
        "expr": condition,
        "for": window,
        "labels": {"severity": "page", "owner": owner},
        "annotations": {
            "summary": objective["statement"],
            # 這兩段是這支腳本存在的理由：意圖裡的散文直接變成告警上的欄位，
            # 值班的人（或 agent）看到告警的同時就看到「為什麼」跟「先看哪裡」。
            "why": " ".join(objective["why"].split()),
            "first_check": " ".join(objective["first_check"].split()),
        },
    }


def compile_change(spec: dict[str, Any], metrics: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = []
    for item in spec.get("unchanged", []):
        signal = item["signal"]
        metric = metrics[signal["metric"]]
        series = prom_name(signal["metric"], metric["instrument"])
        window = item.get("window", "30m")
        label = prom_label(signal["dimension"])
        values = "|".join(signal.get("values", []))
        expr = (
            f'sum(rate({series}{{{label}=~"{values}"}}[{window}]))'
            f" / sum(rate({series}[{window}]))"
        )
        queries.append(
            {
                "id": item["id"],
                "kind": "unchanged",
                "statement": item["statement"],
                "expr": expr,
                "tolerance_ratio": item.get("tolerance_ratio"),
            }
        )
    return queries


# --- 主流程 ------------------------------------------------------------------


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2

    intent_path = Path(sys.argv[1])
    intent = yaml.safe_load(intent_path.read_text())
    registry = intent["metadata"]["registry"]
    metrics = index_metrics(resolve_registry(registry))

    kind = intent["kind"]
    spec = intent["spec"]
    errors: list[str] = []

    if kind == "SteadyStateIntent":
        items = spec["objectives"]
        for objective in items:
            errors += validate_signal(objective["signal"], metrics, f"objective `{objective['id']}`")
    elif kind == "ChangeIntent":
        items = spec.get("expected", []) + spec.get("unchanged", [])
        for item in items:
            errors += validate_signal(item["signal"], metrics, f"`{item['id']}`")
    else:
        print(f"不認得的 kind: {kind}")
        return 2

    print(f"# {intent_path.name}: {kind}，{len(items)} 條，registry = {registry}")

    if errors:
        print(f"\n✗ 驗證失敗，{len(errors)} 個問題：\n")
        for error in errors:
            print(f"  - {error}")
        return 1

    print("✔ 每一個 metric、dimension、值都在 registry 裡對得上\n")

    if kind == "SteadyStateIntent":
        rules = [compile_objective(objective, metrics) for objective in spec["objectives"]]
        print(yaml.safe_dump({"groups": [{"name": intent["metadata"]["service"], "rules": rules}]},
                             allow_unicode=True, sort_keys=False, width=100))
    else:
        for query in compile_change(spec, metrics):
            print(f"# {query['id']}: {query['statement']}")
            print(f"#   容忍範圍 ±{query['tolerance_ratio']:.0%}")
            print(query["expr"])
            print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
