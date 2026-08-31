"""Render a schema catalog from the Weaver registry, reconciled with the live stack.

The other generator in this series (`day33/awayfield/make_catalog.py`) asks the
running stack what exists. That is the only option on someone else's cluster,
but on our own it throws away the thing governance spent the season building: a
registry knows what an attribute MEANS, which values are legal, and which are
required -- none of which is recoverable from a label dump, and none of which
goes missing when the traffic generator happens to be off.

It cannot be used raw, though. This registry is written in the target idiom
(`app.payment.charges.count`) while the services still emit Prometheus-flavoured
names (`payment_charges_total`), and the mapping between the two lives in a
human-readable `note:` string. Handing the model the idiomatic names alone would
give it a document that is entirely correct and entirely unqueryable -- the same
shape as the Day1 prompt that scoped every query to a label this stack does not
have, and the same punishment: an empty array with no error on it.

So this does three things:

  1. resolves the registry through `weaver registry resolve` (refs and enum
     members expanded -- not a hand-rolled YAML parse),
  2. recovers the emitted name from each group's `note:` / flat-key annotation,
  3. asks Prometheus and Loki what is actually there, and prints every group in
     one of three states: agreed, in the registry but missing from the stack, or
     live but unconventioned.

That third state is the point. A catalog that quietly lists only the names that
resolved would hide exactly the drift the registry exists to catch.

    python3 make_catalog_from_registry.py -r ../../../../demo-services/weaver/registry \
        --prom http://localhost:19090 --loki http://localhost:13100 --out catalog.registry.md
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# `Current code metric: \`payment_charges_total\`.` / `Flat key in current code: \`event\`.`
_EMITTED = re.compile(r"(?:Current code metric|Flat key in current code|Current code)\s*:\s*`([^`]+)`")
_RUNTIME_PREFIXES = ("go_", "process_", "promhttp_", "python_", "otelcol_", "target_", "scrape_")


def _get(url: str, params: dict[str, object] | None = None) -> dict:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.load(resp)


def resolve_registry(registry: Path) -> list[dict]:
    """Run the registry through weaver rather than reading the YAML ourselves.

    Refs, enum members and requirement levels are inherited across files; a
    hand parse gets that subtly wrong and the catalog would then be authored by
    the bug rather than by the registry.
    """
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as fh:
        out = Path(fh.name)
    proc = subprocess.run(
        ["weaver", "registry", "resolve", "-r", str(registry), "--format", "json", "-o", str(out)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        raise SystemExit(f"weaver registry resolve failed ({proc.returncode})")
    return json.loads(out.read_text())["groups"]


def emitted_name(group: dict, fallback_key: str) -> str | None:
    """The name this group actually appears under in the stack, per its note."""
    match = _EMITTED.search(group.get("note") or "")
    return match.group(1) if match else group.get(fallback_key)


def live_metric_names(prom: str) -> set[str]:
    names = _get(f"{prom}/api/v1/label/__name__/values")["data"]
    return {n for n in names if not n.startswith(_RUNTIME_PREFIXES)}


def live_event_values(loki: str, hours: int) -> set[str]:
    """The `event` values Loki has actually seen.

    Not `/label/event/values` -- `event` is structured metadata, not a stream
    label, so that endpoint answers with a cheerful empty success and every
    event would get marked "not seen". Aggregating by it is the query that
    returns the truth.
    """
    query = f'sum by (event) (count_over_time({{deployment_environment="demo"}} | event=~".+" [{hours}h]))'
    try:
        data = _get(
            f"{loki}/loki/api/v1/query",
            {"query": query, "time": int(datetime.now(timezone.utc).timestamp())},
        )
        return {r["metric"]["event"] for r in data["data"]["result"] if r["metric"].get("event")}
    except Exception:
        return set()


def _is_live(name: str | None, instrument: str | None, live: set[str]) -> bool:
    """Is this metric in Prometheus?

    A histogram never appears under its own name -- it is exported as
    `_bucket` / `_sum` / `_count`. Checking the bare name marks every histogram
    in the registry as missing, and the catalog would then tell the model that a
    metric it can actually query does not exist. That is a worse lie than
    saying nothing.
    """
    if not name:
        return False
    if name in live:
        return True
    return instrument == "histogram" and f"{name}_bucket" in live


def _attr_lines(group: dict) -> list[str]:
    out = []
    for attr in group.get("attributes", []):
        name = attr.get("name")
        flat = _EMITTED.search(attr.get("note") or "")
        emitted = flat.group(1) if flat else name
        level = attr.get("requirement_level")
        level = level if isinstance(level, str) else "conditionally required"
        type_ = attr.get("type")
        if isinstance(type_, dict) and type_.get("members"):
            values = ", ".join(f"`{m['value']}`" for m in type_["members"])
            shape = f"one of {values}"
        else:
            shape = f"`{type_}`" if isinstance(type_, str) else "value"
        label = f"`{emitted}`" if emitted == name else f"`{emitted}` (registry: `{name}`)"
        out.append(f"  - {label} — {level}, {shape}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-r", "--registry", type=Path, required=True)
    ap.add_argument("--prom", default="http://localhost:9090")
    ap.add_argument("--loki", default="http://localhost:3100")
    ap.add_argument("--hours", type=int, default=1)
    ap.add_argument("--out", default="-")
    args = ap.parse_args()

    groups = resolve_registry(args.registry)
    metrics = [g for g in groups if g["type"] == "metric"]
    events = [g for g in groups if g["type"] == "event"]
    spans = [g for g in groups if g["type"] == "span"]

    live_metrics = live_metric_names(args.prom)
    live_events = live_event_values(args.loki, args.hours)

    doc: list[str] = [
        "# Telemetry Schema Catalog",
        "",
        f"Generated at {datetime.now(timezone.utc).isoformat(timespec='seconds')} from the "
        "`demo-services-biz` Weaver registry, reconciled against the live stack. The registry "
        "says what each signal MEANS and which values are legal; the stack says what is "
        "actually there right now. Names below are the ones the code emits — where the "
        "registry's idiomatic name differs, it is shown in brackets. Nothing here says how to "
        "call a tool.",
        "",
        "## Metrics",
        "",
    ]

    missing_metrics, present_metrics = [], []
    for g in metrics:
        name = emitted_name(g, "metric_name")
        target = present_metrics if _is_live(name, g.get("instrument"), live_metrics) else missing_metrics
        target.append((name, g))

    for name, g in sorted(present_metrics):
        idiom = g.get("metric_name")
        title = f"- `{name}`" + (f" (registry: `{idiom}`)" if idiom != name else "")
        doc.append(f"{title} — {g.get('instrument')}, unit `{g.get('unit')}`. {g.get('brief','').strip()}")
        doc += _attr_lines(g)
    doc.append("")

    if missing_metrics:
        doc += [
            "**In the registry but NOT in Prometheus right now.** Treat these as conventions "
            "the code has not adopted yet — querying them returns an empty result, which is "
            "not evidence that the thing they describe did not happen:",
            "",
        ]
        doc += [f"- `{n}` — {g.get('brief','').strip()}" for n, g in sorted(missing_metrics)]
        doc.append("")

    accounted: set[str] = set()
    for n, g in present_metrics:
        accounted.add(n)
        if g.get("instrument") == "histogram":
            accounted |= {f"{n}_bucket", f"{n}_sum", f"{n}_count"}
    unconventioned = sorted(live_metrics - accounted)
    if unconventioned:
        doc += [
            "**In Prometheus but not in the registry** (auto-instrumentation and anything the "
            "conventions have not caught up with) — usable, but nothing here defines what its "
            "labels mean:",
            "",
            ", ".join(f"`{n}`" for n in unconventioned),
            "",
        ]

    doc += ["## Events (business logs)", ""]
    for g in sorted(events, key=lambda g: g.get("name") or g["id"]):
        name = g.get("name")
        seen = "" if not live_events else (" — seen live" if name in live_events else " — not seen in this window")
        doc.append(f"- `{name}`{seen}. {g.get('brief','').strip()}")
        doc += _attr_lines(g)
    doc.append("")

    doc += ["## Spans", ""]
    for g in sorted(spans, key=lambda g: g["id"]):
        doc.append(f"- `{g['id']}` — kind `{g.get('span_kind')}`. {g.get('brief','').strip()}")
        doc += _attr_lines(g)
    doc.append("")

    out = "\n".join(doc)
    if args.out == "-":
        print(out)
    else:
        Path(args.out).write_text(out, encoding="utf-8")
        print(
            f"wrote {args.out} ({len(out)} chars) — "
            f"{len(present_metrics)} metrics agreed, {len(missing_metrics)} registry-only, "
            f"{len(unconventioned)} live-only"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
