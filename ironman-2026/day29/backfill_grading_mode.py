#!/usr/bin/env python3
"""Fill `grading_mode` on calibration rows written before the column existed.

Day33 measured that `correct` carries two different questions: `culprit` rows
mean "the blame was right", `inconclusive` rows mean "it hedged appropriately".
Only the first is what ECE/overconfidence assume, so the gate now computes over
`culprit` rows only. Rows written before the column existed are NULL, and NULL is
fail-closed — so without this backfill the gate sees zero eligible rows.

The mode is recoverable because eval run_ids carry their fixture:

    eval-<fixture-id>-seed<n>-<nonce>   ->   fixtures.yaml[fixture-id].expect

Rows that are not eval runs are left NULL: nothing here knows what question a
production label was answering, and guessing is exactly the mistake this column
exists to prevent.

Dry run by default.

    python3 ironman-2026/day29/backfill_grading_mode.py
    python3 ironman-2026/day29/backfill_grading_mode.py --apply
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
SERVICE = ROOT / "aiops-agent" / "service"
sys.path.insert(0, str(SERVICE))

from app import store  # noqa: E402  (imported for its schema/migration side effect)

FIXTURES = SERVICE / "app" / "eval" / "fixtures.yaml"
RUN_ID = re.compile(r"^eval-(.+?)-seed\d+-\d+$")
DEFAULT_DBS = [ROOT / "aiops.db", SERVICE / "app" / "eval" / "eval.db"]


def modes() -> dict[str, str]:
    return {f["id"]: f.get("expect", "culprit") for f in yaml.safe_load(FIXTURES.read_text())}


def backfill(db: Path, expect: dict[str, str], apply: bool) -> None:
    if not db.exists():
        print(f"{db}: not found, skipped")
        return
    # Touch through app.store so the ADD COLUMN migration runs on this file.
    store.cal_load(db)

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, run_id FROM calibration WHERE grading_mode IS NULL").fetchall()

    planned: list[tuple[int, str]] = []
    unknown = 0
    for r in rows:
        m = RUN_ID.match(r["run_id"])
        mode = expect.get(m.group(1)) if m else None
        if mode is None:
            unknown += 1
            continue
        planned.append((r["id"], mode))

    tally = Counter(mode for _, mode in planned)
    print(f"{db}")
    print(f"  {len(rows)} row(s) with no grading_mode")
    print(f"  resolvable: {dict(tally) or '{}'};  left NULL: {unknown}")

    if not apply:
        conn.close()
        return
    conn.executemany(
        "UPDATE calibration SET grading_mode=? WHERE id=?", [(m, i) for i, m in planned]
    )
    conn.commit()
    after = Counter(r[0] for r in conn.execute("SELECT grading_mode FROM calibration").fetchall())
    conn.close()
    print(f"  updated {len(planned)} row(s); now {dict(after)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dbs", nargs="*", type=Path, default=DEFAULT_DBS)
    ap.add_argument("--apply", action="store_true", help="actually write (default: dry run)")
    args = ap.parse_args()

    expect = modes()
    print(f"fixtures: {expect}\n")
    for db in args.dbs:
        backfill(db, expect, args.apply)
        print()
    if not args.apply:
        print("dry run — nothing written. Re-run with --apply.")


if __name__ == "__main__":
    main()
