#!/usr/bin/env python3
"""What the calibration pool is actually made of.

Day42 read every gate and found the one that matters: accuracy in the band where
AUTO would be granted, 0.2. That reads like "the model is wrong when it is
confident", which is a statement about the agent. This reads the rows behind the
number instead, and they say something else — the pool is small, old, and most
of the decision band comes from one re-investigation chain in June.

Three things it prints:

  1. the labeled pool by month, and how much of it is a rehearsal;
  2. the rows in the decision band, grouped by run_id — before Day38 run_id WAS
     the fingerprint, so one id can cover a whole chain of runs;
  3. what the curve looks like with the rehearsals excluded.

    # against the running cluster (reads /data/aiops.db inside the pod)
    python3 ironman-2026/day43/probe_label_pool.py

    # against a local checkout instead of the cluster
    python3 ironman-2026/day43/probe_label_pool.py --local

Read-only: it opens one SQLite file and computes. Nothing here writes.
"""

from __future__ import annotations

import argparse
import subprocess
import sys

# Runs inside the pod (or the local venv) so it uses the service's own math
# rather than a second implementation of it.
PROBE = r"""
from app.calibration import bin_evidence, compute_calibration, load_records, production_records
from app.config import settings
from app import store

modes = tuple(settings.governance_calibration_modes)
S = settings
recs = [r for r in load_records() if r.correct is not None]

print("=" * 78)
print("the labeled pool, by month")
print("=" * 78)
print()
print(f"  {'month':>8}  {'labeled':>7}  {'drills':>6}  {'correct':>7}")
for month in sorted({r.ts[:7] for r in recs}):
    rows = [r for r in recs if r.ts[:7] == month]
    drills = [r for r in rows if r.drill]
    print(f"  {month:>8}  {len(rows):>7}  {len(drills):>6}  {sum(1 for r in rows if r.correct):>7}")
print()
print(f"  total labeled: {len(recs)}   unlabeled: {len(load_records()) - len(recs)}")

print()
print("=" * 78)
print(f"the decision band (confidence >= {S.governance_conf_high}), grouped by run_id")
print("=" * 78)
print()
band = [r for r in production_records(recs) if r.confidence >= S.governance_conf_high]
by_run = {}
for r in band:
    by_run.setdefault(r.run_id, []).append(r)
for run_id, rows in sorted(by_run.items(), key=lambda kv: kv[1][0].ts):
    print(f"  run_id={run_id}  rows={len(rows)}")
    for r in sorted(rows, key=lambda r: r.ts):
        verdict = "correct" if r.correct else "WRONG  "
        print(f"    {r.ts}  conf={r.confidence:<5} {verdict}  {r.summary[:52]}")
        if r.correction_note:
            print(f"      note: {r.correction_note[:70]}")
print()
print(f"  {len(band)} row(s) in the band, from {len(by_run)} run id(s).")
print("  A run id covering several rows is a pre-Day38 chain: back then run_id was")
print("  the fingerprint, so every re-investigation of one alert shared it.")

print()
print("=" * 78)
print("the curve, with and without rehearsals")
print("=" * 78)
print()
for tag, rows in (("everything", recs), ("production only", production_records(recs))):
    c = compute_calibration(rows, modes=modes)
    e = bin_evidence(c, min_bin_count=S.governance_min_bin_count, band_lo=S.governance_conf_high)
    print(f"  {tag:<16} labeled={c['labeled']:<3} overconf={c['overconfidence']:<8} "
          f"band n={e['band_n']:<3} band acc={e['band_accuracy']}")
print()
print("  Today the two lines agree: no rehearsal has ever been labeled. That is")
print("  the point of doing this before labelling the backlog, not after — there")
print("  are 8 unlabeled drill runs sitting at confidence 0.95, all right about the")
print("  same seeded fault, and they would have walked into the band together.")
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--local", action="store_true", help="run against the checkout, not the pod")
    ap.add_argument("--namespace", default="demo")
    args = ap.parse_args()

    if args.local:
        cmd = ["python3", "-c", PROBE]
        cwd = "aiops-agent/service"
    else:
        cmd = [
            "kubectl",
            "exec",
            "-n",
            args.namespace,
            "deploy/aiops-agent",
            "--",
            "python3",
            "-c",
            PROBE,
        ]
        cwd = None
    return subprocess.call(cmd, cwd=cwd)


if __name__ == "__main__":
    sys.exit(main())
