#!/usr/bin/env python3
"""Backfill `grading_mode` so the cluster's human labels survive the migration.

`grading_mode` was added to the calibration table to record which question a
row's `correct` column answers, and the gate filters on it fail-closed: a NULL
mode matches no filter, so it never counts. That is the right default for rows
whose mode nobody knows — and the wrong outcome for the cluster's rows, whose
mode *is* known. They came from the plugin's correct/wrong button on an RCA that
named a culprit, which is exactly `culprit` grading. Left alone, the additive
migration would arrive, stamp all seven of them NULL, and silently retire the
only external labels this system has.

So the migration needs a companion: fill in what is known, leave the rest NULL.
Idempotent (only touches rows still NULL), and it prints the gate's verdict
before and after so the change is visible as a decision, not just a row count.

    # dry run against the committed snapshot (default)
    python3 ironman-2026/day28/fix_grading_mode.py

    # against the cluster's own store, in place
    python3 ironman-2026/day28/fix_grading_mode.py --store /data/aiops.db --apply
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "aiops-agent" / "service"))

from app import store  # noqa: E402
from app.calibration import CULPRIT, compute_calibration, load_records  # noqa: E402
from app.config import settings  # noqa: E402
from app.governance import _SELF_LABEL_SOURCES, _calibration_verdict  # noqa: E402

HERE = Path(__file__).resolve().parent
SNAPSHOT = HERE / "cluster-snapshot.db"
# The plugin's correct/wrong button grades "was the blame right" — `culprit`.
UI_SOURCES = ("ui",)


def verdict(db: Path) -> tuple[dict, int, tuple[bool, str]]:
    records = load_records(db)
    modes = tuple(settings.governance_calibration_modes)
    calib = compute_calibration(records, modes=modes)
    human = store.cal_count_by_source(exclude_sources=_SELF_LABEL_SOURCES, modes=modes, path=db)
    return calib, human, _calibration_verdict(calib, human_labeled=human)


def report(label: str, db: Path) -> None:
    calib, human, (good, note) = verdict(db)
    print(f"  {label}")
    print(
        f"    labeled={calib['labeled']} non-self={human} "
        f"ece={calib['ece']} overconfidence={calib.get('overconfidence')}"
    )
    print(f"    gate: {'auto' if good else 'propose'}  {note}")


def backfill(db: Path) -> int:
    placeholders = ",".join("?" for _ in UI_SOURCES)
    conn = sqlite3.connect(db)
    try:
        n = conn.execute(
            f"UPDATE calibration SET grading_mode = ? WHERE grading_mode IS NULL "
            f"AND correct IS NOT NULL AND source IN ({placeholders})",
            (CULPRIT, *UI_SOURCES),
        ).rowcount
        conn.commit()
    finally:
        conn.close()
    return n


def diagram(db: Path) -> None:
    calib, _, _ = verdict(db)
    print("  reliability diagram over the labels that now count")
    print(f"    {'band':<11} {'n':<4} {'stated':<8} {'actual':<8} gap")
    for b in calib.get("bins", []):
        if not b["count"]:
            continue
        band = f"[{b['lo']:.1f},{b['hi']:.1f})"
        print(
            f"    {band:<11} {b['count']:<4} {b['avg_confidence']:<8} {b['accuracy']:<8} {b['gap']}"
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store", type=Path, default=SNAPSHOT, help="calibration store to fix")
    ap.add_argument("--apply", action="store_true", help="write to --store instead of a copy")
    args = ap.parse_args()

    db = args.store
    if not db.exists():
        print(f"missing {db}")
        return 1
    if not args.apply:
        work = Path(f"{db}.dryrun")
        shutil.copy2(db, work)
        print(f"[dry run] working on a copy: {work.name}")
        db = work

    print("[1] before")
    report("as it stands", db)
    print(f"\n[2] backfill grading_mode={CULPRIT!r} for labeled rows from {UI_SOURCES}")
    print(f"  rows updated: {backfill(db)}")
    print("\n[3] after")
    report("with the known modes filled in", db)
    print()
    diagram(db)
    if not args.apply:
        db.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
