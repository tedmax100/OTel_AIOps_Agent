#!/usr/bin/env python3
"""What the gate reads, and what it was throwing away.

Day31 printed a reliability diagram and then said the quiet part: the governance
gate reads exactly one number out of it, `overconfidence`, and that number is a
signed mean. Two opposite errors cancel. The bins that show where the agent is
actually wrong were computed on every single run and read by nobody.

This probe runs the gate over three datasets and prints what changed:

  1. the store the gate would read right now — whichever file that turns out
     to be (see `describe`, and the surprise in view 0)
  2. Day31's 35 rows, rebuilt from the reliability diagram that day published,
     because the dev store those rows lived in has since been emptied. The
     rebuild is exact: each bin had a single stated confidence, so counts +
     accuracies pin every row. The check is that it reproduces -0.0029.
  3. the 7 real human labels in the cluster snapshot — the only labels in this
     repo that a person actually clicked.

Read-only. No cluster, no LLM.

    python3 ironman-2026/day29/gate_probe.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SERVICE = ROOT / "aiops-agent" / "service"
sys.path.insert(0, str(SERVICE))

from app import store  # noqa: E402
from app.actions import ActionSpec  # noqa: E402
from app.calibration import (  # noqa: E402
    CalibrationRecord,
    bin_evidence,
    compute_calibration,
    load_records,
)
from app.config import settings  # noqa: E402
from app.governance import _calibration_verdict  # noqa: E402

# Next to this script, so it resolves whatever the checkout directory is called.
SNAPSHOT = Path(__file__).resolve().parent / "cluster-snapshot.db"

# The candidate stores. Day31's report script reads the first one; the service
# writes the second in host-side dev; the pod writes the third. Same filename,
# same schema, same code.
CANDIDATES = [
    ("what day31's script reads", ROOT / "aiops.db"),
    ("what the service writes", SERVICE / "aiops.db"),
    ("the pod's volume (snapshot)", SNAPSHOT),
]

# Day31 [2], verbatim: (stated confidence, n, n_correct). One stated value per
# bin, so this is a lossless rebuild rather than an approximation.
DAY31_DIAGRAM = [
    (0.0, 2, 2),
    (0.1, 4, 0),
    (0.3, 2, 0),
    (0.6, 12, 7),
    (0.7, 6, 5),
    (0.8, 6, 3),
    (0.9, 3, 3),
]

SPEC = ActionSpec(
    name="k8s.rollout_undo", description="d", reversible=True, requires_approval=False
)


def _records(groups: list[tuple[float, int, int]]) -> list[CalibrationRecord]:
    out = []
    for conf, n, n_ok in groups:
        for i in range(n):
            out.append(
                CalibrationRecord(
                    run_id=f"r{len(out)}",
                    ts="2026-01-01T00:00:00Z",
                    confidence=conf,
                    correct=i < n_ok,
                    grading_mode="culprit",
                )
            )
    return out


def _snapshot_records() -> list[CalibrationRecord]:
    """The snapshot predates the `grading_mode` column, so read it directly and
    mark the rows `culprit` — Day37 established that the 7 UI labels are all
    verdicts about blame."""
    import sqlite3

    # read-only URI: this snapshot is evidence for another day's article, and
    # a probe that migrates the thing it is reading destroys what it proves.
    conn = sqlite3.connect(f"file:{SNAPSHOT}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT run_id, confidence, correct FROM calibration WHERE correct IS NOT NULL"
    ).fetchall()
    conn.close()
    return [
        CalibrationRecord(
            run_id=r[0],
            ts="2026-06-22T00:00:00Z",
            confidence=r[1],
            correct=bool(r[2]),
            grading_mode="culprit",
        )
        for r in rows
    ]


def _old_verdict(calib: dict) -> tuple[bool, str]:
    """What `_calibration_verdict` did before today: the labeled-run floor, then
    one comparison against the signed mean."""
    labeled = calib.get("labeled") or 0
    if labeled < settings.governance_min_labeled_runs:
        return False, f"calibration unproven ({labeled} labeled run(s)); autonomy withheld"
    overconf = calib.get("overconfidence")
    if overconf is None:
        return False, "calibration unavailable; autonomy withheld"
    if overconf > settings.governance_max_overconfidence:
        return False, f"overconfident by {overconf:+}; autonomy narrowed"
    return True, f"calibration ok (overconfidence {overconf:+}, {labeled} runs)"


def view0_which_store() -> None:
    print("[0] three files named aiops.db, and which one has anything in it")
    for label, path in CANDIDATES:
        d = store.describe(path)
        if not d["exists"]:
            print(f"  {label:<28} {path.name:<20} does not exist")
            continue
        t = d["tables"]
        print(
            f"  {label:<28} {path.name:<20} "
            f"cal={t['calibration']} inv={t['investigations']} "
            f"ar={t['action_requests']} exec={t['executions']}"
        )
    print()


def _bins(calib: dict, min_count: int, band_lo: float) -> None:
    print("  band        n    stated  actual  gap     read as")
    for b in calib["bins"]:
        if not b["count"]:
            continue
        thin = b["count"] < min_count
        in_band = b["lo"] >= band_lo - 1e-9
        tag = "too thin to count" if thin else ("DECISION BAND" if in_band else "counted")
        print(
            f"  [{b['lo']:.1f},{b['hi']:.1f})  {b['count']:<4} "
            f"{b['avg_confidence']:<7.4} {b['accuracy']:<7.4} {b['gap']:<7.4} {tag}"
        )


def view(title: str, records: list[CalibrationRecord]) -> None:
    calib = compute_calibration(records)
    ev = bin_evidence(
        calib,
        min_bin_count=settings.governance_min_bin_count,
        band_lo=settings.governance_conf_high,
    )
    print(title)
    if not calib.get("labeled"):
        old_ok, old_note = _old_verdict(calib)
        new_ok, new_note = _calibration_verdict(calib)
        print(f"  nothing labeled here — {calib.get('count', 0)} row(s) recorded")
        print(f"  before  -> {'AUTO   ' if old_ok else 'PROPOSE'}  {old_note}")
        print(f"  after   -> {'AUTO   ' if new_ok else 'PROPOSE'}  {new_note}\n")
        return
    print(
        f"  labeled={calib['labeled']}  overconfidence={calib['overconfidence']:+}  "
        f"ece={calib['ece']}  mce={calib['mce']}"
    )
    _bins(calib, settings.governance_min_bin_count, settings.governance_conf_high)
    print(
        f"  evidence: worst counted bin {ev['max_gap']} at {ev['max_gap_bin']}; "
        f"decision band n={ev['band_n']} accuracy={ev['band_accuracy']}; "
        f"{ev['thin_bins']} bin(s)/{ev['thin_runs']} run(s) dropped as thin"
    )
    old_ok, old_note = _old_verdict(calib)
    new_ok, new_note = _calibration_verdict(calib)
    print(f"  before  -> {'AUTO   ' if old_ok else 'PROPOSE'}  {old_note}")
    print(f"  after   -> {'AUTO   ' if new_ok else 'PROPOSE'}  {new_note}")
    print()


def main() -> int:
    print(
        f"thresholds: conf_high={settings.governance_conf_high} "
        f"max_overconfidence={settings.governance_max_overconfidence} "
        f"max_bin_gap={settings.governance_max_bin_gap} "
        f"min_bin_count={settings.governance_min_bin_count} "
        f"min_band_accuracy={settings.governance_min_band_accuracy}\n"
    )
    view0_which_store()

    live = load_records()
    view(f"[1] whatever is in the configured store ({settings.store_path})", live)
    view("[2] day31's 35 rows, rebuilt from the diagram it published", _records(DAY31_DIAGRAM))
    view("[3] the 7 labels a human actually clicked (cluster snapshot)", _snapshot_records())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
