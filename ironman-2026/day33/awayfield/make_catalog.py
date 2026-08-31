"""Generate a schema catalog for whatever stack is in front of us, by asking it.

Day33 measured three of the four cells in the home/away x with/without-catalog
table. The missing one is "the catalog describes THIS stack" on the away
cluster, and the reason it was missing is that `schema_catalog.md` is
hand-written: doing it by hand for every new environment costs a person a day,
and the experiment would then be measuring how well that person writes rather
than what a correct catalog is worth.

So this writes one from discovery instead. Everything below comes off the live
APIs -- metric names, the labels each one actually carries and their values, log
stream labels, the JSON fields inside the log lines, Tempo's tag names and the
services present. Nothing is typed in by hand, which is what makes the resulting
arm honest: no bench question is answered here, and no query recipe is offered.
That last part is deliberate. The home-field arm lost a whole task to a rule
that told the model HOW to call a tool; this file only says what is in the
stack.

    python3 make_catalog.py --prom http://localhost:9090 \
        --loki http://localhost:3100 --tempo http://localhost:3200 \
        --out catalog.away.md
"""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

# Instrumentation of the runtime itself, not of the application. It is in every
# stack, it answers no question anyone asks, and listing it makes the inventory
# harder to read.
_RUNTIME_PREFIXES = ("go_", "process_", "promhttp_", "python_", "otelcol_")
_RUNTIME_NAMES = {"up", "scrape_duration_seconds", "scrape_samples_scraped"}


def _get(url: str, params: dict[str, object] | None = None) -> dict:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.load(resp)


def _is_runtime(name: str) -> bool:
    return name.startswith(_RUNTIME_PREFIXES) or name in _RUNTIME_NAMES


def discover_prometheus(base: str) -> str:
    names = _get(f"{base}/api/v1/label/__name__/values")["data"]
    app_names = [n for n in names if not _is_runtime(n)]

    lines = [
        "## Metrics (Prometheus)",
        "",
        f"{len(app_names)} application metric names are present "
        f"({len(names) - len(app_names)} runtime/scrape metrics are omitted). "
        "For each one, the labels it actually carries and the values seen:",
        "",
    ]
    for name in sorted(app_names):
        series = _get(f"{base}/api/v1/series", {"match[]": name})["data"]
        by_label: dict[str, set[str]] = defaultdict(set)
        for s in series:
            for k, v in s.items():
                if k != "__name__":
                    by_label[k].add(v)
        lines.append(f"- `{name}` — {len(series)} series")
        for label in sorted(by_label):
            values = sorted(by_label[label])
            # `le` on a histogram is bucket boundaries and `instance` is
            # host:port; enumerating either is noise, so summarise instead.
            if label == "le":
                lines.append(f"  - `le`: histogram buckets, {len(values)} boundaries")
            elif len(values) > 8:
                shown = ", ".join(f"`{v}`" for v in values[:8])
                lines.append(f"  - `{label}`: {shown}, … ({len(values)} values)")
            else:
                lines.append(f"  - `{label}`: " + ", ".join(f"`{v}`" for v in values))
    lines.append("")
    return "\n".join(lines)


def discover_loki(base: str, hours: int) -> str:
    now = datetime.now(timezone.utc)
    start = int((now - timedelta(hours=hours)).timestamp() * 1e9)
    end = int(now.timestamp() * 1e9)
    window = {"start": start, "end": end}

    labels = _get(f"{base}/loki/api/v1/labels", window)["data"]
    lines = ["## Logs (Loki)", "", "Stream labels and their values:", ""]
    for label in sorted(labels):
        values = _get(f"{base}/loki/api/v1/label/{label}/values", window)["data"]
        shown = ", ".join(f"`{v}`" for v in sorted(values)[:12])
        more = f", … ({len(values)} values)" if len(values) > 12 else ""
        lines.append(f"- `{label}`: {shown}{more}")

    # The line body decides whether a question is answerable with a stream
    # selector or needs a parser, so sample it rather than assuming.
    sample = _get(
        f"{base}/loki/api/v1/query_range",
        {"query": '{job=~".+"}', "limit": 25, **window},
    )["data"]["result"]
    fields: dict[str, set[str]] = defaultdict(set)
    parsed = 0
    for stream in sample:
        for _ts, line in stream["values"]:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            parsed += 1
            for k, v in obj.items():
                fields[k].add(type(v).__name__)
    if parsed:
        lines += [
            "",
            f"Line bodies are JSON ({parsed}/{sum(len(s['values']) for s in sample)} "
            "sampled lines parsed). Fields inside the body, with their JSON types "
            "— these are not stream labels, so reaching them needs a parser stage:",
            "",
        ]
        for k in sorted(fields):
            lines.append(f"- `{k}`: {'/'.join(sorted(fields[k]))}")
    lines.append("")
    return "\n".join(lines)


def discover_tempo(base: str, hours: int) -> str:
    now = datetime.now(timezone.utc)
    window = {"start": int((now - timedelta(hours=hours)).timestamp()), "end": int(now.timestamp())}

    tags = _get(f"{base}/api/search/tags", window).get("tagNames", [])
    traces = _get(f"{base}/api/search", {**window, "limit": 50}).get("traces", [])
    services = sorted({t.get("rootServiceName", "") for t in traces} - {""})
    names = sorted({t.get("rootTraceName", "") for t in traces} - {""})

    lines = ["## Traces (Tempo)", ""]
    lines.append("Searchable tag names: " + (", ".join(f"`{t}`" for t in sorted(tags)) or "none"))
    lines.append("")
    if services:
        lines.append("Root services seen in a recent search: " + ", ".join(f"`{s}`" for s in services))
    if names:
        shown = ", ".join(f"`{n}`" for n in names[:10])
        lines.append(f"Root span names seen: {shown}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prom", default="http://localhost:9090")
    ap.add_argument("--loki", default="http://localhost:3100")
    ap.add_argument("--tempo", default="http://localhost:3200")
    ap.add_argument("--hours", type=int, default=6)
    ap.add_argument("--out", default="-")
    args = ap.parse_args()

    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    doc = "\n".join(
        [
            "# Telemetry Schema Catalog",
            "",
            f"Generated from the live stack at {generated} by "
            "`day33/awayfield/make_catalog.py`. It is an inventory of what this "
            "environment contains — nothing here is an instruction about how to "
            "call a tool, and no value below was typed in by hand.",
            "",
            discover_prometheus(args.prom),
            discover_loki(args.loki, args.hours),
            discover_tempo(args.tempo, args.hours),
        ]
    )
    if args.out == "-":
        print(doc)
    else:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(doc)
        print(f"wrote {args.out} ({len(doc)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
