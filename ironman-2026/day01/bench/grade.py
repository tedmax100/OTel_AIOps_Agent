"""Deterministic grading for the Day1 bench. No LLM judge.

Two reasons the judge is a plain Python function here. One, Day1's whole job is
to produce a number the rest of the series can be compared against, and a number
that moves because the judge model changed is worthless. Two, every failure this
bench is meant to expose — a wrong ratio, an ungrounded trace ID, an answer with
no query behind it — is mechanically checkable. A later day is where judging gets hard
enough to need an LLM, and that day also shows why the judge itself needs
gatekeeping.

Ground truth is resolved live: `truth.query` is executed against the same stack
the agent just queried. The telemetry is regenerated on every cluster boot, so a
hardcoded expected value would be stale immediately.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
LOKI_URL = os.getenv("LOKI_URL", "http://localhost:3100")
TEMPO_URL = os.getenv("TEMPO_URL", "http://localhost:3200")

# Trace IDs are 16-32 hex chars. Requiring a long run of hex avoids matching
# ordinary words and version strings.
TRACE_ID_RE = re.compile(r"\b[0-9a-f]{16,32}\b", re.IGNORECASE)
# Numbers with optional thousands separators and a trailing %. The lookarounds
# keep out digits welded to letters — `5xx`, `p99`, `v2.5.0`, HTTP `500` inside a
# word — which would otherwise donate a "number" the answer never actually
# claimed. `5xx` in particular appears in every one of these questions.
NUMBER_RE = re.compile(r"(?<![\w.])-?\d[\d,]*\.?\d*\s*%?(?![\w.])")


# ---- resolving ground truth -------------------------------------------------


@dataclass
class Truth:
    """One resolved fact: a value, and optionally the label value that carried
    it (the winning backend / the worst path)."""

    value: float | None
    label: str | None = None
    error: str | None = None


def _prom_value(query: str, label: str | None = None) -> Truth:
    """Instant query → the first series' value, plus the label value that
    carried it when the task grades a winner (topk(1) by job / by path)."""
    try:
        r = httpx.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": query}, timeout=30.0)
        r.raise_for_status()
        result = r.json()["data"]["result"]
    except Exception as e:
        return Truth(None, error=f"{type(e).__name__}: {e}")
    if not result:
        return Truth(None, error="empty result")
    top = result[0]
    return Truth(float(top["value"][1]), label=top["metric"].get(label) if label else None)


def _loki_value(query: str, label: str | None = None) -> Truth:
    """INSTANT query, not query_range.

    The tasks ask "how many in the last 6 hours", and the queries express that as
    `count_over_time(...[6h])`. Evaluated as a range query with a 60s step, Loki
    returns one such 6h count *per step* — 360 heavily overlapping windows. Summing
    them inflated the ground truth by ~160x here (60 warn lines became 9707), and
    every agent that answered correctly would have been graded wrong. Evaluated
    once at the end of the window, the same query gives the number the question
    actually asked for."""
    try:
        r = httpx.get(
            f"{LOKI_URL}/loki/api/v1/query",
            params={"query": query, "time": f"{int(time.time())}000000000"},
            timeout=60.0,
        )
        r.raise_for_status()
        result = r.json()["data"]["result"]
    except Exception as e:
        return Truth(None, error=f"{type(e).__name__}: {e}")
    if not result:
        return Truth(None, error="empty result")
    top = result[0]
    return Truth(float(top["value"][1]), label=top.get("metric", {}).get(label) if label else None)


def _tempo_has_results(query: str, hours: int = 24) -> Truth:
    """Traces are graded on grounding, not on a number — the truth here is just
    'this query returns something', so an empty stack fails loudly."""
    end = int(time.time())
    start = end - hours * 3600
    try:
        r = httpx.get(
            f"{TEMPO_URL}/api/search",
            params={"q": query, "start": start, "end": end, "limit": 20},
            timeout=30.0,
        )
        r.raise_for_status()
        traces = r.json().get("traces", [])
    except Exception as e:
        return Truth(None, error=f"{type(e).__name__}: {e}")
    return Truth(float(len(traces)))


def resolve_truth(task: dict[str, Any]) -> dict[str, Truth]:
    """Resolve the task's main truth plus any `also:` extras, keyed by name
    ('main' for the primary one)."""
    spec = task.get("truth", {})
    backend = spec.get("backend")
    label = spec.get("label")
    out: dict[str, Truth] = {}

    def one(query: str, want_label: str | None) -> Truth:
        if backend == "prometheus":
            return _prom_value(query, want_label)
        if backend == "loki":
            return _loki_value(query, want_label)
        return _tempo_has_results(query)

    out["main"] = one(spec["query"], label)
    for name, query in (spec.get("also") or {}).items():
        out[name] = one(query, None)

    scale = spec.get("scale")
    if scale:
        for t in out.values():
            if t.value is not None:
                t.value *= scale
    return out


# ---- checks -----------------------------------------------------------------


@dataclass
class CheckResult:
    type: str
    passed: bool
    detail: str


def _numbers_in(text: str) -> list[float]:
    out: list[float] = []
    for m in NUMBER_RE.finditer(text):
        raw = m.group().replace(",", "").replace("%", "").strip()
        try:
            out.append(float(raw))
        except ValueError:
            continue
    return out


def _number_check(answer: str, truth: Truth, tol: float, name: str) -> CheckResult:
    if truth.value is None:
        return CheckResult("number", False, f"ground truth unavailable ({truth.error})")
    candidates = _numbers_in(answer)
    if not candidates:
        return CheckResult("number", False, f"no number in the answer (truth {truth.value:.4g})")
    # Pure relative tolerance. An absolute floor sounds kinder but is not: on a
    # truth of 0.017 req/s a floor of 0.01 would pass almost any small number the
    # agent happened to print, which turns the check into decoration.
    window = abs(truth.value) * tol if truth.value else 1e-9
    hit = min(candidates, key=lambda c: abs(c - truth.value))
    ok = abs(hit - truth.value) <= window
    return CheckResult(
        "number",
        ok,
        f"{name}: closest stated {hit:.4g} vs truth {truth.value:.4g} (±{window:.4g})",
    )


def _contains_check(answer: str, any_of: list[str]) -> CheckResult:
    low = answer.lower()
    hit = next((s for s in any_of if s.lower() in low), None)
    return CheckResult(
        "contains",
        hit is not None,
        f"found {hit!r}" if hit else f"none of {any_of} in the answer",
    )


def _grounded_check(answer: str, tool_blob: str) -> CheckResult:
    """Every trace ID printed in the answer must appear in something a tool
    returned. This is the check that catches a fabricated trace ID — the failure
    mode that makes an otherwise reasonable-sounding report useless."""
    cited = {t.lower() for t in TRACE_ID_RE.findall(answer)}
    if not cited:
        return CheckResult("grounded", True, "no trace IDs cited (nothing to ground)")
    blob = tool_blob.lower()
    bad = sorted(t for t in cited if t not in blob)
    if bad:
        return CheckResult("grounded", False, f"trace ID not in any tool output: {bad[0]}")
    return CheckResult("grounded", True, f"all {len(cited)} cited trace ID(s) found in tool output")


def grade(
    task: dict[str, Any], answer: str, tool_calls: list, truths: dict[str, Truth]
) -> tuple[float, list[CheckResult]]:
    """Grade one run → (score, [CheckResult]). Score is 1.0 / 0.5 / 0.0."""
    results: list[CheckResult] = []
    ok_calls = [c for c in tool_calls if getattr(c, "ok", True)]

    for check in task.get("checks", []):
        kind = check["type"]
        if kind == "queried":
            need = int(check.get("min", 1))
            results.append(
                CheckResult(
                    "queried",
                    len(ok_calls) >= need,
                    f"{len(ok_calls)} successful tool call(s), needed {need}",
                )
            )
        elif kind == "contains":
            if check.get("from_label"):
                label = truths["main"].label
                if not label:
                    results.append(CheckResult("contains", False, "ground-truth label unavailable"))
                else:
                    results.append(_contains_check(answer, [label]))
            else:
                results.append(_contains_check(answer, check["any_of"]))
        elif kind == "number":
            key = check.get("of", "main")
            results.append(_number_check(answer, truths[key], float(check.get("tol", 0.15)), key))
        elif kind == "grounded":
            blob = "\n".join(getattr(c, "output", "") for c in tool_calls)
            results.append(_grounded_check(answer, blob))
        elif kind == "cites_trace":
            found = bool(TRACE_ID_RE.search(answer))
            results.append(
                CheckResult("cites_trace", found, "cited a trace ID" if found else "no trace ID")
            )

    if all(r.passed for r in results):
        return 1.0, results

    partial = set(task.get("partial_checks", []))
    if partial and all(r.passed for r in results if r.type in partial):
        return 0.5, results
    return 0.0, results
