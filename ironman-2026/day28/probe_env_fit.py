#!/usr/bin/env python3
"""Does the knowledge I am carrying belong to the environment I am pointed at?

The series ends on a conclusion it never turned into a mechanism: governance is
a function of the environment. The same agent scores 3.5 on a stack its schema
catalog was not written for and 5.5 on one it was — but nothing anywhere asks,
before a run, whether the injected knowledge resolves against the stores the
agent is about to query.

This points the agent's own `app.signals.envfit` at two stacks that differ in
exactly one way. `demo` is home. `demo-twin` is the same services, the same
traffic and the same incident, fed by the same collector through a renaming
pipeline: `service.name` becomes `svc.name`, metrics get an `acme_` prefix. So
a score difference here cannot be blamed on missing tools or a different data
shape, the way the Day1-stack comparison could.

Three sections:

  1. the fit itself, per store, for each environment
  2. what the governance gate does with it — same proposal, same calibration,
     two environments, two answers
  3. the one-line comparison

Read-only. No LLM. Needs six port-forwards; see this day's README.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "aiops-agent" / "service"))

import app.signals.envfit as envfit_mod  # noqa: E402
from app.actions import ActionSpec  # noqa: E402
from app.config import settings  # noqa: E402
from app.governance import decide  # noqa: E402
from app.signals.dq import dq_verdict  # noqa: E402
from app.signals.envfit import compute_env_fit, fit_verdict  # noqa: E402

# Local port-forwards, so the same code can be pointed at either stack.
PRESETS = {
    "home": ("http://localhost:19090", "http://localhost:13100", "http://localhost:13200"),
    "twin": ("http://localhost:29090", "http://localhost:23100", "http://localhost:23200"),
}

# A deliberately synthetic proposal: reversible, not approval-gated, high
# confidence, and a calibration record that passes every gate. Everything that
# could withhold AUTO for another reason is neutralised, so what is left is the
# environment question on its own.
_SPEC = ActionSpec(
    name="k8s.probe_action", description="synthetic", reversible=True, requires_approval=False
)
_CALIB_OK = {"labeled": 50, "overconfidence": -0.02}
# The real store has 7 labels, so the calibration lock would fire first and hide
# the thing this script is about. Zeroing the floor is what isolates the
# variable — it is not a suggestion about how to run the gate for real.
settings.governance_min_human_labeled_runs = 0


def _point_at(prom: str, loki: str, tempo: str) -> None:
    settings.prometheus_url, settings.loki_url, settings.tempo_url = prom, loki, tempo
    envfit_mod._last = None  # each environment gets measured on its own


async def measure(label: str, urls: tuple[str, str, str], verbose: bool) -> dict:
    _point_at(*urls)
    print(f"[{label}] prom={urls[0]} loki={urls[1]} tempo={urls[2]}")
    fit = await compute_env_fit()
    for store, (hit, total) in fit.by_store.items():
        ratio = f"{hit / total:.2f}" if total else " n/a"
        print(f"  {store:<8} {hit:>2}/{total:<2} resolved   fit {ratio}")
    shown = fit.unresolved if verbose else fit.unresolved[:2]
    for u in shown:
        print(f"      ✗ {u}")
    if not verbose and len(fit.unresolved) > 2:
        print(f"      ✗ (+{len(fit.unresolved) - 2} more)")
    v = fit_verdict()
    print(f"  -> {json.dumps(v, ensure_ascii=False)}")

    # What the gate does with it. `decide()` takes a DQ verdict directly, so
    # this is the real policy path rather than a re-implementation of it.
    # Handing it the fit verdict alone keeps the other DQ dimensions (topology
    # freshness, schema alignment) out of the comparison; the composite verdict
    # is printed underneath so the wiring is visible too.
    d = decide(_SPEC, 0.95, _CALIB_OK, v)
    print(f"  -> gate (environment dimension only): {d.autonomy}  {d.reason}")
    print(f"     composite dq_verdict(): {dq_verdict()['note']}\n")
    return {"fit": v, "autonomy": str(d.autonomy)}


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--env", choices=[*PRESETS, "both"], default="both")
    ap.add_argument("-v", "--verbose", action="store_true", help="list every miss")
    a = ap.parse_args()

    out = {}
    for t in [*PRESETS] if a.env == "both" else [a.env]:
        out[t] = await measure(t, PRESETS[t], a.verbose)

    if len(out) == 2:
        h, w = out["home"], out["twin"]
        print(
            f"home fit {h['fit']['score']} -> {h['autonomy']}   vs   "
            f"twin fit {w['fit']['score']} -> {w['autonomy']}"
        )
        print("(same services, same traffic, same incident — only the names differ)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
