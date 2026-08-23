#!/usr/bin/env python3
"""Move graded eval-harness runs into the store the governance gate actually reads.

Day31 measured `non-self=0` and concluded autonomy could never be earned. That
was true of `aiops.db` and false of the repo: `app/eval/harness.py` has been
inserting + labeling every fixture run since June, into its own store —

    DEFAULT_STORE = _HERE / "eval.db"  # separate from prod aiops.db unless overridden

The split is deliberate (eval runs must not silently become production history),
but nothing bridges it, so the one process that produces external verdicts is
invisible to the one gate that requires them.

This is that bridge, made explicit rather than implicit:

  - only labeled records are copied (`correct IS NOT NULL`)
  - `source` is preserved, so promoted rows stay identifiable as `eval-harness`
    forever — they are not laundered into looking like production runs
  - idempotent: a run_id already present in the target is skipped
  - dry-run by default; `--apply` is the only thing that writes

    python3 ironman-2026/day29/promote_labels.py            # show what would move
    python3 ironman-2026/day29/promote_labels.py --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SERVICE = ROOT / "aiops-agent" / "service"
sys.path.insert(0, str(SERVICE))

import app.governance as gov  # noqa: E402
from app import store  # noqa: E402
from app.actions import registry  # noqa: E402
from app.calibration import compute_calibration, load_records  # noqa: E402
from app.governance import decide  # noqa: E402

SRC = SERVICE / "app" / "eval" / "eval.db"
DST = ROOT / "aiops.db"


def snapshot(db: Path, label: str) -> None:
    calib = compute_calibration(load_records(db))
    human = store.cal_count_by_source(exclude_sources=gov._SELF_LABEL_SOURCES, path=db)
    print(
        f"  {label:<10} labeled={calib['labeled']:<3} non-self={human:<3} "
        f"overconfidence={calib.get('overconfidence')}"
    )


def verdict(db: Path) -> None:
    """What the gate says for the real registered actions at confidence 0.9."""
    calib = compute_calibration(load_records(db))
    for name in registry.names():
        d = decide(registry.get(name), 0.9, calib, path=db)
        print(f"  {name:<18} -> {d.autonomy.value:<8} {d.calibration_note}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", type=Path, default=SRC)
    ap.add_argument("--dst", type=Path, default=DST)
    ap.add_argument("--source", default="eval-harness", help="only promote this label source")
    ap.add_argument("--apply", action="store_true", help="actually write (default: dry run)")
    args = ap.parse_args()

    rows = [
        r
        for r in store.cal_load(args.src)
        if r["correct"] is not None and r.get("source") == args.source
    ]
    existing = {r["run_id"] for r in store.cal_load(args.dst)}
    todo = [r for r in rows if r["run_id"] not in existing]

    print(f"source {args.src}")
    print(f"  {len(rows)} labeled record(s) with source={args.source!r}")
    print(f"  {len(rows) - len(todo)} already present in the target, {len(todo)} to promote\n")

    print("before")
    snapshot(args.dst, "target")
    verdict(args.dst)
    print()

    if not args.apply:
        print("dry run — nothing written. Re-run with --apply.")
        return

    for r in todo:
        store.cal_insert(
            run_id=r["run_id"],
            ts=r["ts"],
            confidence=r["confidence"],
            summary=r.get("summary") or "",
            hypothesis=r.get("hypothesis") or "",
            suspected_version=r.get("suspected_version"),
            services=r.get("services") or [],
            path=args.dst,
        )
        store.cal_label(
            r["run_id"],
            bool(r["correct"]),
            score=r.get("score"),
            source=r.get("source") or args.source,
            path=args.dst,
        )

    print(f"promoted {len(todo)} record(s)\n")
    print("after")
    snapshot(args.dst, "target")
    verdict(args.dst)


if __name__ == "__main__":
    main()
