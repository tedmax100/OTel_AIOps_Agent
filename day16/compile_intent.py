#!/usr/bin/env python3
"""把意圖 YAML 編譯成可執行的查詢，並且拿 registry 當事實來源驗證它。

這支腳本的重點不是「產生 PromQL」，是**意圖裡的每一個欄位名與值都要在 registry 裡存在**。
一份意圖如果指向不存在的 metric、不存在的 dimension、或不在 enum members 裡的值，
它就不是機器可讀的意圖，只是一段看起來很像 YAML 的散文。

用法（從這個 repo 的根目錄跑）：

    weaver registry generate -r day16/registry --templates day16/templates \\
      python day16/generated --include-unreferenced=true
    python3 day16/compile_intent.py day16/intent/steady-state.yaml
    python3 day16/compile_intent.py day16/intent/change.yaml
    python3 day16/compile_intent.py day16/intent/steady-state-broken.yaml   # exit 1

registry.json 是上面那道 generate 產出的 resolved registry（`--filter .` 的那個 template）。
"""

import json
import sys

import yaml

REGISTRY_JSON = "day16/generated/registry.json"   # 可用第二個參數覆蓋（Day13 的 checklist 會用到）


def load_registry(path: str) -> tuple[dict, dict]:
    """回傳 (metrics, enums)：metric_name → 維度集合、attribute name → 合法值集合。"""
    data = json.load(open(path))
    metrics: dict[str, set[str]] = {}
    enums: dict[str, set[str]] = {}
    for group in data["groups"]:
        for attr in group.get("attributes", []):
            attr_type = attr.get("type")
            if isinstance(attr_type, dict) and "members" in attr_type:
                enums[attr["name"]] = {m["value"] for m in attr_type["members"]}
        if group.get("type") == "metric":
            metrics[group["metric_name"]] = {a["name"] for a in group.get("attributes", [])}
    return metrics, enums


def prom_name(name: str) -> str:
    """OTel 名稱 → Prometheus 名稱（點換底線）。"""
    return name.replace(".", "_")


class IntentError(Exception):
    pass


def check_signal(signal: dict, metrics: dict, enums: dict, where: str) -> None:
    metric = signal.get("metric")
    if metric not in metrics:
        raise IntentError(
            f"{where}: metric '{metric}' 不存在於 registry"
            f"（有的是：{', '.join(sorted(metrics))}）"
        )
    dimension = signal.get("dimension")
    if dimension and dimension not in metrics[metric]:
        raise IntentError(
            f"{where}: '{metric}' 沒有 '{dimension}' 這個維度"
            f"（有的是：{', '.join(sorted(metrics[metric]))}）"
        )
    for key in ("good_values", "values"):
        for value in signal.get(key, []):
            legal = enums.get(dimension, set())
            if value not in legal:
                raise IntentError(
                    f"{where}: '{dimension}' 沒有 '{value}' 這個值"
                    f"（enum members：{', '.join(sorted(legal))}）"
                )


def ratio_query(signal: dict, values: list[str], window: str) -> str:
    metric = prom_name(signal["metric"]) + "_total"
    dimension = prom_name(signal["dimension"])
    selector = f'{dimension}=~"{"|".join(values)}"'
    return (
        f"sum(rate({metric}{{{selector}}}[{window}]))\n"
        f"  / sum(rate({metric}[{window}]))"
    )


def quantile_query(signal: dict, quantile: float, window: str) -> str:
    metric = prom_name(signal["metric"]) + "_bucket"
    return f"histogram_quantile({quantile}, sum by (le) (rate({metric}[{window}])))"


def compile_steady_state(doc: dict, metrics: dict, enums: dict) -> list[str]:
    out = []
    for obj in doc["spec"]["objectives"]:
        check_signal(obj["signal"], metrics, enums, f"objectives[{obj['id']}]")
        spec, sig = obj["objective"], obj["signal"]
        window = spec["window"]
        if "ratio_min" in spec:
            expr = ratio_query(sig, sig["good_values"], window)
            condition = f"({expr}) < {spec['ratio_min']}"
        else:
            expr = quantile_query(sig, spec["quantile"], window)
            condition = f"({expr}) > {spec['max_seconds']}"
        out.append(
            f"# {obj['id']}: {obj['statement']}\n"
            f"- alert: {obj['id']}\n"
            f"  expr: |\n    " + condition.replace("\n", "\n    ") + "\n"
            f"  for: {window}\n"
            f"  labels:\n"
            f"    severity: {obj['on_violation']['severity']}\n"
            f"  annotations:\n"
            f"    intent: \"{obj['statement']}\"\n"
            f"    why: \"{' '.join(obj['why'].split())}\"\n"
            f"    first_check: \"{obj['on_violation']['first_check']}\""
        )
    return out


def compile_change(doc: dict, metrics: dict, enums: dict) -> list[str]:
    out = []
    for kind in ("expected", "unchanged"):
        for item in doc["spec"].get(kind, []):
            check_signal(item["signal"], metrics, enums, f"{kind}[{item['id']}]")
            sig, window = item["signal"], item["window"]
            if kind == "expected":
                expr = quantile_query(sig, 0.99, window)
                verdict = f"# 期望方向：{item['direction']}（跟部署前的同一條查詢比）"
            else:
                expr = ratio_query(sig, sig["values"], window)
                verdict = f"# 容忍變化：±{item['tolerance_ratio'] * 100:.0f}%（超過就回滾）"
            out.append(f"# {kind}[{item['id']}]: {item['statement']}\n{verdict}\n{expr}")
    return out


def main() -> int:
    path = sys.argv[1]
    registry_json = sys.argv[2] if len(sys.argv) > 2 else REGISTRY_JSON
    doc = yaml.safe_load(open(path))
    metrics, enums = load_registry(registry_json)
    kind = doc["kind"]
    print(f"# {kind} ← {path}")
    print(f"# registry: {doc['metadata']['registry']}（{len(metrics)} metrics、{len(enums)} enums）\n")
    try:
        blocks = (
            compile_steady_state(doc, metrics, enums)
            if kind == "SteadyStateIntent"
            else compile_change(doc, metrics, enums)
        )
    except IntentError as err:
        print(f"✗ 意圖與 registry 不一致：{err}", file=sys.stderr)
        return 1
    print("\n\n".join(blocks))
    print(f"\n# ✔ {len(blocks)} 條意圖全部對得上 registry")
    return 0


if __name__ == "__main__":
    sys.exit(main())
