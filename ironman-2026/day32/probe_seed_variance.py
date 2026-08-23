#!/usr/bin/env python3
"""What `-n 3` actually buys.

Two experiments on the same fixture, hours apart on unchanged code, gave 3/3 and
0/3. The obvious reading is "the model is noisy, add seeds" — which is the
recommendation this project has been repeating since it measured a +-67pp floor.
This checks that reading against the recorded runs instead of assuming it.

The eval's `seed` sets the LangGraph thread id and the calibration run id. It
does not reach the model call: the RCA model is constructed at temperature 0 and
no per-seed sampling parameter is passed. So the seeds are the same request,
issued n times, and whatever differs between them is the provider not being
bit-deterministic rather than a sample of anything.

Reads the eval store, groups by (fixture, run) and asks two questions:
does the *text* differ between seeds, and does the *verdict*.

    python3 ironman-2026/day32/probe_seed_variance.py
    python3 ironman-2026/day32/probe_seed_variance.py --store path/to/eval.db
"""

from __future__ import annotations

import argparse
import collections
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STORE = ROOT / "aiops-agent" / "service" / "app" / "eval" / "eval.db"


def load(store: Path) -> dict[tuple[str, str], list[tuple[str, str, int]]]:
    conn = sqlite3.connect(store)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT run_id, summary, correct FROM calibration "
        "WHERE run_id LIKE 'eval-%' AND summary IS NOT NULL"
    ).fetchall()
    grouped: dict[tuple[str, str], list[tuple[str, str, int]]] = collections.defaultdict(list)
    for r in rows:
        body = r["run_id"][len("eval-") :]
        if "-seed" not in body:
            continue
        fixture, rest = body.rsplit("-seed", 1)
        seed, _, nonce = rest.partition("-")
        grouped[(fixture, nonce)].append((seed, r["summary"], r["correct"]))
    return grouped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", type=Path, default=DEFAULT_STORE)
    args = ap.parse_args()
    if not args.store.exists():
        print(f"no eval store at {args.store}", file=sys.stderr)
        return 1

    groups = {k: v for k, v in load(args.store).items() if len(v) > 1}
    if not groups:
        print("no multi-seed runs recorded yet")
        return 1

    same_text = sum(1 for v in groups.values() if len({t for _, t, _ in v}) == 1)
    same_verdict = sum(1 for v in groups.values() if len({c for _, _, c in v}) == 1)
    n = len(groups)

    print(f"[1] multi-seed runs recorded: {n}")
    print(f"    every seed produced the same text    : {same_text}/{n}")
    print(f"    every seed produced the same verdict : {same_verdict}/{n}")

    print("\n[2] the runs whose seeds disagreed on the verdict")
    split = [(k, v) for k, v in groups.items() if len({c for _, _, c in v}) > 1]
    if not split:
        print("    (none)")
    for (fixture, nonce), v in split:
        print(f"    {fixture} @{nonce}: {[c for _, _, c in sorted(v)]}")

    print("\n[3] what that means for -n")
    print("    A fixture's score is a verdict, not a sentence. If the seeds inside")
    print(f"    one run agree on the verdict {same_verdict}/{n} of the time, then -n mostly buys")
    print("    correlated repeats of one answer, and the variance that moved 3/3 to")
    print("    0/3 lives between runs. Adding seeds does not reach it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
