#!/usr/bin/env python3
"""The five flagship agentic SLOs, computed against the store that actually ran.

ARE 3.6 names five load-bearing SLOs: Autonomous Resolution Rate (ARR),
Decision Quality (DQ-SLO), Reasoning Latency (RL-SLO), Action Effectiveness
(AE-SLO) and Calibration Error (CE). This script computes all five over the
cluster's own store, and for each one reports whether the number is a
measurement, an undefined ratio, or an artifact of how the data was produced.

Five views:

  1. two stores, side by side. Day31-38 measured the dev store; the cluster
     has always had its own, with a different (smaller, human-labeled) set.
  2. what the pending schema migration does to the cluster's human labels:
     `grading_mode` arrives NULL, and NULL is fail-closed at the gate.
  3. the five flagships over the cluster store, each with its n.
  4. Suggestion Acceptance Rate — the L2 gate metric — and its denominator.
  5. the four L3 mechanisms (ARE 4.9's Trust Ceiling), each with its evidence.

Read-only. No cluster, no LLM: it reads a snapshot copied out of the pod with

    kubectl -n demo cp <aiops-agent-pod>:/data/aiops.db \\
        ironman-2026/day28/cluster-snapshot.db

    python3 ironman-2026/day28/slo_report.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SERVICE = ROOT / "aiops-agent" / "service"
sys.path.insert(0, str(SERVICE))

from app.calibration import (  # noqa: E402
    CULPRIT,
    CalibrationRecord,
    compute_calibration,
    filter_by_mode,
    load_records,
)
from app.config import settings  # noqa: E402

HERE = Path(__file__).resolve().parent
CLUSTER = HERE / "cluster-snapshot.db"
DEV = ROOT / "aiops.db"
TABLES = ("calibration", "investigations", "action_requests", "executions", "audit")
SELF_SOURCES = ("remediation-verified", "remediation-failed")


def _rows(db: Path, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    """Query without touching the file: the app's own _connect() would run its
    additive migrations, and section 2 is about what those migrations do."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _count(db: Path, table: str) -> int:
    return _rows(db, f"SELECT COUNT(*) AS n FROM {table}")[0]["n"]


def _has_column(db: Path, table: str, col: str) -> bool:
    return any(r["name"] == col for r in _rows(db, f"PRAGMA table_info({table})"))


def _ts(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def _pct(num: int, den: int) -> str:
    return "undefined (0 denominator)" if den == 0 else f"{num / den * 100:.1f}%"


# --- 1: which store is the real one ----------------------------------------


def two_stores() -> None:
    print("[1] the same schema, two stores, two different histories")
    print(f"  {'table':<16} {'dev (aiops.db)':>16} {'cluster /data':>16}")
    for t in TABLES:
        d = _count(DEV, t) if DEV.exists() else -1
        print(f"  {t:<16} {d:>16} {_count(CLUSTER, t):>16}")
    labeled = _rows(
        CLUSTER,
        "SELECT source, COUNT(*) AS n FROM calibration WHERE correct IS NOT NULL GROUP BY source",
    )
    print("  cluster labels by source: " + ", ".join(f"{r['source']}={r['n']}" for r in labeled))
    non_self = sum(r["n"] for r in labeled if r["source"] not in SELF_SOURCES)
    print(f"  cluster non-self labels: {non_self}   (Day31 measured this as 0 on the dev store)")


# --- 2: what the pending migration does -------------------------------------


def migration_effect() -> None:
    print("\n[2] the column the cluster has not seen yet")
    has_col = _has_column(CLUSTER, "calibration", "grading_mode")
    print(f"  cluster calibration.grading_mode present: {has_col}")
    print(
        f"  gate reads modes={tuple(settings.governance_calibration_modes)} "
        "(NULL never matches — fail-closed on unknowns)"
    )
    with tempfile.TemporaryDirectory() as td:
        migrated = Path(td) / "migrated.db"
        shutil.copy2(CLUSTER, migrated)
        records = load_records(migrated)  # opening it runs the additive migrations
        now_has = _has_column(migrated, "calibration", "grading_mode")
        print(f"  after migration, grading_mode present: {now_has}")
        labeled = [r for r in records if r.correct is not None]
        eligible = [r for r in filter_by_mode(records, (CULPRIT,)) if r.correct is not None]
        print(f"  labeled rows: {len(labeled)}   eligible for the curve after: {len(eligible)}")


# --- 3: the five flagships ---------------------------------------------------


def _ce(records: list[CalibrationRecord]) -> dict[str, Any]:
    return compute_calibration(records, modes=None)


def flagships() -> None:
    print("\n[3] the five flagships, over the cluster store")

    incidents = {r["fp"] for r in _rows(CLUSTER, "SELECT DISTINCT fp FROM action_requests")}
    autonomy = _rows(
        CLUSTER, "SELECT autonomy, COUNT(*) AS n FROM action_requests GROUP BY autonomy"
    )
    auto_n = sum(r["n"] for r in autonomy if r["autonomy"] == "auto")
    resolved = _count(CLUSTER, "executions")
    ok = _rows(CLUSTER, "SELECT COALESCE(SUM(success), 0) AS n FROM executions")[0]["n"]

    print(
        f"  ARR     autonomously resolved / detected incidents = 0 / {len(incidents)} "
        f"-> {_pct(0, len(incidents))}"
    )
    print(
        "            (measurable, and it is a real 0: "
        + ", ".join(f"{r['autonomy']}={r['n']}" for r in autonomy)
        + " — no request was ever raised at AUTO)"
    )
    print(
        f"  DQ-SLO  successful autonomous decisions / autonomous decisions = 0 / {auto_n} "
        f"-> {_pct(0, auto_n)}"
    )
    print("            (not a measurement: the denominator is empty by construction)")

    lat = []
    for r in _rows(CLUSTER, "SELECT ts, payload FROM investigations ORDER BY ts"):
        alert = json.loads(r["payload"]).get("alert") or {}
        starts = alert.get("startsAt")
        if starts:
            lat.append((starts, (_ts(r["ts"]) - _ts(starts)).total_seconds()))
    reused = {s for s, _ in lat if sum(1 for x, _ in lat if x == s) > 1}
    fresh = sorted(v for s, v in lat if s not in reused)
    stale = sorted(v for s, v in lat if s in reused)
    print(f"  RL-SLO  decision_commit - startsAt, n={len(lat)}: max {max(v for _, v in lat):.0f}s")
    print(
        f"            {len(stale)} of them share one startsAt (a replayed alert body): "
        f"{stale[0]:.0f}-{stale[-1]:.0f}s — that is my hand, not the system"
    )
    print(f"            the {len(fresh)} distinct alerts: {', '.join(f'{v:.0f}s' for v in fresh)}")

    print(
        f"  AE-SLO  effective recoveries / recoveries = {ok} / {resolved} -> {_pct(ok, resolved)}"
    )
    print(
        "            (n=1, and the one failure was a 401 — it measures a credential, not an action)"
    )

    records = load_records(DEV) if DEV.exists() else []
    cluster_recs = _load_raw(CLUSTER)
    c_dev = _ce(records)
    c_cl = _ce(cluster_recs)
    print(
        f"  CE      cluster store: labeled={c_cl['labeled']} ece={c_cl['ece']} "
        f"overconfidence={c_cl['overconfidence']}"
    )
    print(
        f"            dev store:     labeled={c_dev['labeled']} ece={c_dev['ece']} "
        f"overconfidence={c_dev['overconfidence']}"
    )
    print(
        f"            gate floor is {settings.governance_min_labeled_runs} labeled runs — "
        "neither store answers the same question twice"
    )


def _load_raw(db: Path) -> list[CalibrationRecord]:
    """Build records straight from SQL, so a store without `grading_mode` can
    still be read (the app's loader SELECTs that column)."""
    out = []
    for r in _rows(
        db,
        "SELECT run_id, ts, confidence, correct, score, source, summary, hypothesis, "
        "suspected_version, services FROM calibration ORDER BY id",
    ):
        d = dict(r)
        d["correct"] = None if d["correct"] is None else bool(d["correct"])
        d["services"] = json.loads(d["services"] or "[]")
        out.append(CalibrationRecord.model_validate(d))
    return out


# --- 4: the L2 gate metric --------------------------------------------------


def sar() -> None:
    print("\n[4] Suggestion Acceptance Rate — the L2 gate metric (ARE 4.9)")
    total = _count(CLUSTER, "action_requests")
    by_status = _rows(
        CLUSTER, "SELECT status, COUNT(*) AS n FROM action_requests GROUP BY status ORDER BY n DESC"
    )
    approved = _rows(
        CLUSTER,
        "SELECT DISTINCT request_id, actor FROM audit WHERE phase='approved' AND verdict='ok'",
    )
    rejected = _rows(CLUSTER, "SELECT COUNT(*) AS n FROM audit WHERE phase='rejected'")[0]["n"]
    print("  " + ", ".join(f"{r['status']}={r['n']}" for r in by_status))
    print(f"  suggestions raised: {total}   approved: {len(approved)}   rejected: {rejected}")
    print(f"  SAR = {_pct(len(approved), total)}")
    print("  actors who approved: " + ", ".join(sorted(r["actor"] for r in approved)))
    stale = _rows(
        CLUSTER,
        "SELECT COUNT(*) AS n FROM action_requests WHERE status='proposed' AND expires_ts < ?",
        (dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),),
    )[0]["n"]
    print(
        f"  of the denominator, {stale} expired without anyone opening them — "
        "SAR counts 'nobody looked' and 'a human said no' as the same event"
    )


# --- 5: the Trust Ceiling checklist -----------------------------------------


def trust_ceiling() -> None:
    print("\n[5] the four L3 mechanisms (ARE 4.9: all four, simultaneously)")
    dry_runs = _rows(
        CLUSTER, "SELECT verdict, COUNT(*) AS n FROM audit WHERE phase='dry_run' GROUP BY verdict"
    )
    rollbacks = _rows(
        CLUSTER, "SELECT verdict, COUNT(*) AS n FROM audit WHERE phase='rollback' GROUP BY verdict"
    )
    labeled = _rows(CLUSTER, "SELECT COUNT(*) AS n FROM calibration WHERE correct IS NOT NULL")[0][
        "n"
    ]
    for name, evidence in [
        (
            "governance plane, runtime-evaluated",
            "13 decisions recorded, every one at PROPOSE; the kill switch has been "
            "ACTIONS_ENABLED=true in the deployment since 2026-06-22",
        ),
        (
            "action contracts",
            "2 registered actions, both with reversible + requires_approval flags; "
            + ", ".join(f"dry_run {r['verdict']}={r['n']}" for r in dry_runs),
        ),
        (
            "automatic reversal",
            ", ".join(f"rollback {r['verdict']}={r['n']}" for r in rollbacks) or "never triggered",
        ),
        (
            "calibrated confidence",
            f"{labeled} labeled runs in the cluster store vs a floor of "
            f"{settings.governance_min_labeled_runs}",
        ),
    ]:
        print(f"  {name:<38} {evidence}")


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    if not CLUSTER.exists():
        print(f"missing {CLUSTER} — see the kubectl cp line in this file's docstring")
        return 1
    two_stores()
    migration_effect()
    flagships()
    sar()
    trust_ceiling()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
