#!/usr/bin/env python3
"""The first reliability diagram, and what the gate reads instead of it.

Day38 promoted 35 graded runs into the store, so `compute_calibration` finally
has something to compute. `_calibration_verdict()` reads exactly one number out
of it — `overconfidence`, the mean stated confidence minus the mean accuracy —
and this script asks whether that one number says what the gate thinks it says.

Four views of the same 35 rows:

  1. what the gate sees: the aggregate, and its verdict
  2. the reliability diagram those aggregates came from
  3. per fixture — three scenarios, three different behaviours
  4. split by grading mode: `culprit` fixtures score "was the blame right",
     `inconclusive` ones score "did it hedge". Both write into the same
     `correct` column, and ECE assumes they mean the same thing.

Read-only. No cluster, no LLM.

    python3 ironman-2026/day37/calibration_report.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
SERVICE = ROOT / "aiops-agent" / "service"
sys.path.insert(0, str(SERVICE))

from app.actions import registry  # noqa: E402
from app.calibration import (  # noqa: E402
    CULPRIT,
    INCONCLUSIVE,
    CalibrationRecord,
    compute_calibration,
    filter_by_mode,
    hedging_rate,
    load_records,
)
from app.config import settings  # noqa: E402
from app.governance import decide  # noqa: E402

FIXTURES = SERVICE / "app" / "eval" / "fixtures.yaml"
DB = ROOT / "aiops.db"
RUN_ID = re.compile(r"^eval-(.+?)-seed\d+-\d+$")


def fixture_of(run_id: str) -> str:
    m = RUN_ID.match(run_id)
    return m.group(1) if m else "(not an eval run)"


def expect_modes() -> dict[str, str]:
    docs = yaml.safe_load(FIXTURES.read_text())
    return {f["id"]: f.get("expect", "culprit") for f in docs}


def line(records: list[CalibrationRecord], label: str) -> None:
    c = compute_calibration(records)
    if not c["labeled"]:
        print(f"  {label:<38} (no labeled records)")
        return
    print(
        f"  {label:<38} n={c['labeled']:<3} conf={c['overall_confidence']:<6} "
        f"acc={c['overall_accuracy']:<6} overconf={c['overconfidence']:<+8} ece={c['ece']}"
    )


def diagram(c: dict) -> None:
    print("  band        n    stated  actual  gap")
    for b in c["bins"]:
        if not b["count"]:
            continue
        arrow = (
            "  "
            if abs(b["gap"]) < 0.05
            else ("<-" if b["avg_confidence"] > b["accuracy"] else "->")
        )
        print(
            f"  [{b['lo']:.1f},{b['hi']:.1f})  {b['count']:<4} "
            f"{b['avg_confidence']:<7} {b['accuracy']:<7} {b['gap']:<6} {arrow}"
        )
    print("  (<- stated above actual = overconfident;  -> stated below actual = underconfident)")


def gate(records: list[CalibrationRecord], label: str) -> None:
    c = compute_calibration(records)
    spec = registry.get(registry.names()[0]).model_copy(update={"requires_approval": False})
    d = decide(spec, 0.9, c, path=DB)
    print(f"  {label:<38} -> {d.autonomy.value:<8} {d.calibration_note}")


def main() -> None:
    records = load_records(DB)
    modes = expect_modes()
    overall = compute_calibration(records)

    print("[1] the aggregate over every row, which is what the gate used to read")
    print(
        f"  labeled={overall['labeled']}  overconfidence={overall['overconfidence']:+}  "
        f"tolerance={settings.governance_max_overconfidence}"
    )
    print(f"  ece={overall['ece']}  mce={overall['mce']}  brier={overall['brier']}")
    gate(records, "handed the whole-store curve")
    print()

    print("[2] the reliability diagram behind that one number")
    diagram(overall)
    print()

    print("[3] the same rows, per fixture")
    by_fix: dict[str, list[CalibrationRecord]] = {}
    for r in records:
        by_fix.setdefault(fixture_of(r.run_id), []).append(r)
    for fix, rs in sorted(by_fix.items(), key=lambda kv: -len(kv[1])):
        line(rs, f"{fix} ({modes.get(fix, '?')})")
    print()

    print("[4] split by grading mode")
    culprit = filter_by_mode(records, (CULPRIT,))
    inconclusive = filter_by_mode(records, (INCONCLUSIVE,))
    line(culprit, "culprit ('blame was right')")
    line(inconclusive, "inconclusive ('it hedged')")
    print()
    gate(culprit, "culprit only (what the gate does now)")
    gate(records, "everything (what it did before)")
    print()

    print("[4b] the culprit-only reliability diagram")
    diagram(compute_calibration(records, modes=(CULPRIT,)))
    print()

    print("[5] the inconclusive rows, reported as what they actually measure")
    h = hedging_rate(records)
    print(
        f"  hedged appropriately on {h['hedged']}/{h['labeled']} non-incidents "
        f"(rate {h['rate']}), mean stated confidence {h['mean_confidence']}"
    )


if __name__ == "__main__":
    main()
