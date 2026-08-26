#!/usr/bin/env python3
"""Why AUTO has never fired — read every gate, not just the first one that says no.

The governance gate reports its *first* failure. For the whole life of this
system that first failure has been "N labeled run(s) < 20", which reads like a
paperwork problem: label more runs and autonomy opens. This walks all of the
conditions AUTO has to clear and prints the live value of each, which is a
different story — the label floor is the cheapest of them to fix and the least
of what is wrong.

It also prints the same curve over several freshness windows. That table is the
reason the fixture record now expires: pooling every label ever written makes
the agent look better calibrated than it currently is, because runs that predate
most of its code are still voting.

    # against the running cluster (reads /data/aiops.db inside the pod)
    python3 ironman-2026/day33/probe_autonomy_gates.py

    # against a local checkout instead of the cluster
    python3 ironman-2026/day33/probe_autonomy_gates.py --local

Read-only: it opens two SQLite files and one JSONL and computes. Nothing here
writes, and nothing here proposes or executes an action.
"""

from __future__ import annotations

import argparse
import subprocess
import sys

# Runs inside the pod (or the local venv) so it can import the service's own
# math rather than reimplementing it — a probe that computes the number a
# different way is measuring the probe.
PROBE = r"""
from datetime import UTC, datetime
from pathlib import Path

from app.calibration import (
    bin_evidence,
    compute_calibration,
    load_records,
    production_records,
)
from app.config import settings
from app.eval.record import load as load_fixture_record
from app.governance import _SELF_LABEL_SOURCES, _calibration_verdict, regression_verdict
from app import store

modes = tuple(settings.governance_calibration_modes)
S = settings


def line(ok, label, want, got):
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<34} want {want:<12} got {got}")


print("=" * 78)
print("the conditions AUTO has to clear")
print("=" * 78)

# Drills are excluded here for the same reason governance excludes them: six
# replays of one seeded fault are one piece of evidence, not six. Reading
# load_records() directly made this probe report 11 where the gate saw 5.
prod = compute_calibration(production_records(load_records()), modes=modes)
human = store.cal_count_by_source(
    exclude_sources=_SELF_LABEL_SOURCES, modes=modes, exclude_drills=True
)
ev = bin_evidence(prod, min_bin_count=S.governance_min_bin_count, band_lo=S.governance_conf_high)

print()
print("production curve  (labels from people, on live incidents)")
labeled = prod.get("labeled") or 0
line(labeled >= S.governance_min_labeled_runs, "labeled runs",
     f">= {S.governance_min_labeled_runs}", labeled)
line(human >= S.governance_min_human_labeled_runs, "human/grader labels",
     f">= {S.governance_min_human_labeled_runs}", human)
oc = prod.get("overconfidence")
line(oc is not None and oc <= S.governance_max_overconfidence, "mean overconfidence",
     f"<= {S.governance_max_overconfidence}", oc)
if ev["available"]:
    line(ev["band_n"] >= S.governance_min_bin_count,
         f"labeled runs at conf >= {S.governance_conf_high}",
         f">= {S.governance_min_bin_count}", ev["band_n"])
    line(ev["band_accuracy"] >= S.governance_min_band_accuracy,
         "accuracy in that band", f">= {S.governance_min_band_accuracy}", ev["band_accuracy"])
    line(ev["max_gap"] is not None and ev["max_gap"] <= S.governance_max_bin_gap,
         "worst bin off by", f"<= {S.governance_max_bin_gap}",
         f'{ev["max_gap"]} ({ev["max_gap_bin"]})')
print()
print("  gate says:", _calibration_verdict(prod, human_labeled=human)[1])

print()
print("fixture record  (the grader, on questions with known answers)")
v = regression_verdict()
for k in ("proven_good", "labeled", "overconfidence", "newest_age_days"):
    if k in v:
        print(f"    {k:<16} = {v[k]}")
print("  gate says:", v["note"])

print()
print("=" * 78)
print("the same fixture curve over different freshness windows")
print("=" * 78)
print()
recs = load_fixture_record(settings.fixture_record_path)
now = datetime.now(UTC)


def age_days(r):
    return (now - datetime.strptime(r.ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)).days


hdr = f"  {'window':>8}  {'labeled':>7}  {'overconf':>9}  {'band n':>6}  {'band acc':>8}"
print(hdr + "  worst bin")
for d in (7, 14, 30, 60, 99999):
    w = [r for r in recs if r.correct is not None and age_days(r) <= d]
    if not w:
        continue
    c = compute_calibration(w, modes=modes)
    e = bin_evidence(c, min_bin_count=S.governance_min_bin_count, band_lo=S.governance_conf_high)
    tag = "all" if d > 9999 else f"{d}d"
    print(f"  {tag:>8}  {c['labeled']:>7}  {c['overconfidence']:>9}  {e['band_n']:>6}  "
          f"{e['band_accuracy']:>8}  {e['max_gap']} ({e['max_gap_bin']})")
print()
print(f"  the gate's window is {S.governance_fixture_max_age_days}d.")
print("  a wider window reports a *better* number here, which is the point:")
print("  the pool was flattering, so expiring the record made this gate stricter.")
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
