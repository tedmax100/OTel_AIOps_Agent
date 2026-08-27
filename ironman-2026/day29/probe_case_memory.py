#!/usr/bin/env python3
"""One fingerprint doing four jobs, and what the case memory costs to fix.

Day32 blamed the empty past-incident library on this JOIN:

    SELECT i.payload FROM investigations i
    JOIN calibration c ON c.run_id = i.fp
    WHERE ... AND c.correct = 1

That was the symptom. The JOIN is over `fp` = sha256(alertname|service|
git_version), and that one column is simultaneously the LangGraph thread_id, the
cooldown key, the per-run record id, and the cross-incident memory key. Those
are three different granularities, so the key is wrong in two directions at
once — and the day36 drill snapshot happens to contain both.

Six probes. The first four read the real snapshot from day36; the last two use a
temp store. No cluster, no LLM.

  1. the snapshot's shape: runs, fingerprints, incidents
  2. too narrow — one incident split across six fingerprints by image tag
  3. too wide  — two human verdicts fanned out over ten conclusions, three of
                 which say "false alarm", all of them retrievable as precedent
  4. after backfill — recall drops to ~0, and that is the correct number
  5. who may write a root cause (self-verification must not)
  6. dead ends: recorded, scoped, and allowed to expire

The snapshot is copied to a temp directory first. `store._connect()` runs the
schema and the migrations on open, so reading an old store through the normal
path silently upgrades it — which is exactly how a read-only probe once added a
column to the very snapshot being kept as evidence that the column was absent.

    python3 ironman-2026/day29/probe_case_memory.py
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
SERVICE = ROOT / "aiops-agent" / "service"
sys.path.insert(0, str(SERVICE))

SNAPSHOT = HERE.parents[1] / "day36" / "snapshot-after-b-20260816T062002Z.db"

from app import case_memory, store  # noqa: E402

SERVICE_NAME = "payment-service"


def h(n: int, title: str) -> None:
    print(f"\n[{n}] {title}")


def copy_snapshot() -> Path:
    """Never open the evidence in place — see the module docstring."""
    tmp = Path(tempfile.mkdtemp()) / "snapshot.db"
    shutil.copy2(SNAPSHOT, tmp)
    return tmp


def ro(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ---- 1-3: what the snapshot already contains -------------------------------


def probe_snapshot_shape(db: Path) -> None:
    h(1, "the snapshot's shape")
    conn = ro(db)
    runs = conn.execute("SELECT COUNT(*) FROM investigations").fetchone()[0]
    fps = conn.execute("SELECT COUNT(DISTINCT fp) FROM investigations").fetchone()[0]
    keys = {
        store.case_key(r["alertname"], r["service"])
        for r in conn.execute(
            "SELECT json_extract(payload,'$.alertname') alertname,"
            "       json_extract(payload,'$.service')   service"
            "  FROM investigations"
        )
    }
    print(f"    investigation rows: {runs}")
    print(f"    distinct fp:        {fps}")
    print(f"    distinct case_key:  {len(keys)}")
    conn.close()


def probe_too_narrow(db: Path) -> None:
    h(2, "too narrow: one incident, six fingerprints")
    conn = ro(db)
    rows = conn.execute(
        "SELECT json_extract(payload,'$.alertname') alertname,"
        "       json_extract(payload,'$.git_version') gv, COUNT(*) n, COUNT(DISTINCT fp) fps"
        "  FROM investigations"
        " WHERE json_extract(payload,'$.alertname') = 'payment-decline-rate-high'"
        " GROUP BY 1,2 ORDER BY 2"
    ).fetchall()
    for r in rows:
        print(f"    git_version={r['gv'] or '(none)':<24} rows={r['n']}  fp={r['fps']}")
    key = store.case_key(rows[0]["alertname"], SERVICE_NAME)
    print(f"    -> {len(rows)} fingerprints, 1 case_key: {key}")
    conn.close()


def probe_too_wide(db: Path) -> None:
    h(3, "too wide: two verdicts, ten precedent rows")
    conn = ro(db)
    rows = conn.execute(
        """
        SELECT i.fp, c.source, json_extract(i.payload,'$.summary') summary
          FROM investigations i
          JOIN calibration c ON c.run_id = i.fp
         WHERE c.correct = 1 AND c.grading_mode = 'culprit'
         ORDER BY i.id DESC
        """
    ).fetchall()
    print(f"    rows the old JOIN calls precedent: {len(rows)}")
    verdicts = conn.execute(
        "SELECT COUNT(*) FROM calibration WHERE correct = 1 AND grading_mode='culprit'"
    ).fetchone()[0]
    print(f"    human verdicts actually recorded:  {verdicts}")
    hedged = [r for r in rows if "false positive" in r["summary"] or "inconclusive" in r["summary"]]
    print(f"    of those rows, ones that concluded there was no incident: {len(hedged)}")
    for r in rows[:5]:
        print(f"      - [{r['source']}] {r['summary'][:88]}")
    conn.close()


def probe_after_backfill(db: Path) -> None:
    h(4, "after backfill")
    print(f"    backfill_cases: {store.backfill_cases(db)}")
    for row in sorted(
        (store.case_get(k, db) for k in _case_keys(db)), key=lambda r: -r["occurrences"]
    ):
        print(
            f"    {row['alertname']:<38} occurrences={row['occurrences']:<3}"
            f" status={row['status']:<10} source={row['root_cause_source']}"
        )
    print(f"    retrievable precedent: {store.case_query_similar(SERVICE_NAME, path=db)}")
    print("    -> 0 is the honest number: no old verdict can say which run it judged,")
    print("       so nothing is promoted. The library starts empty and earns its rows.")


def _case_keys(db: Path) -> list[str]:
    conn = ro(db)
    keys = [r[0] for r in conn.execute("SELECT case_key FROM cases")]
    conn.close()
    return keys


# ---- 5-6: the policy, on a temp store --------------------------------------


def probe_who_may_confirm() -> None:
    h(5, "who may write a root cause")
    db = Path(tempfile.mkdtemp()) / "policy.db"
    for source, mode, label in [
        ("remediation-verified", store.CULPRIT, "the agent verifying its own remediation"),
        ("ui", store.INCONCLUSIVE, "a human confirming it rightly blamed nobody"),
        ("ui", None, "a human, but nobody recorded what the verdict is about"),
        ("ui", store.CULPRIT, "a human confirming the blame"),
        ("eval-harness", store.CULPRIT, "the o11y-bench grader"),
    ]:
        key = store.case_key(f"alert-{source}-{mode}", SERVICE_NAME)
        store.case_upsert(
            key=key, ts="2026-08-18T00:00:00Z", alertname="a", service=SERVICE_NAME, path=db
        )
        verdict = case_memory.confirm_from_label(
            case_key=key,
            correct=True,
            source=source,
            grading_mode=mode,
            root_cause="new_validator rejects odd cents",
            run_id="r1",
            path=db,
        )
        row = store.case_get(key, db)
        print(
            f"    {source:<22} mode={mode!s:<13} -> {verdict:<15}"
            f" status={row['status']:<15} {label}"
        )
    print(f"    retrievable precedent: {len(store.case_query_similar(SERVICE_NAME, path=db))}")


def probe_dead_ends() -> None:
    h(6, "dead ends")
    db = Path(tempfile.mkdtemp()) / "deadends.db"
    print(
        "    outside a scope:",
        case_memory.remember_dead_end("query", "x", disproved_by="tool_result", path=db),
        "(chat turns and unit tests record nothing)",
    )
    with case_memory.case_scope(
        fp="fp1", alertname="PaymentDeclineRateHigh", service=SERVICE_NAME
    ) as sc:
        print(f"    scope: case={sc.case_key} run={sc.run_id}")
        case_memory.remember_dead_end(
            "query",
            "PromQL referencing http_requests_total",
            disproved_by="tool_result",
            evidence="no such metric in this Prometheus",
            path=db,
        )
        case_memory.remember_dead_end(
            "hypothesis",
            "downstream DB saturation",
            disproved_by="model",
            evidence="the model says it checked",
            path=db,
        )
        case_memory.remember_dead_end(
            "query",
            "trace lookup older than the retention window",
            disproved_by="tool_result",
            ttl_seconds=3600,
            path=db,
        )
    for when, note in [
        ("2026-08-18T00:00:00Z", "inside the TTL"),
        ("2099-01-01T00:00:00Z", "after it"),
    ]:
        got = [r["subject"] for r in store.case_ruled_out_for([sc.case_key], now_ts=when, path=db)]
        print(f"    recalled {note:<14}: {got}")
    print("    -> the model's own 'I ruled that out' is stored and never recalled;")
    print("       'Tempo had nothing' expires, because that was about the window.")


def main() -> int:
    if not SNAPSHOT.exists():
        print(f"missing snapshot: {SNAPSHOT}")
        return 1
    db = copy_snapshot()
    print(f"working on a copy: {db}")
    probe_snapshot_shape(db)
    probe_too_narrow(db)
    probe_too_wide(db)
    probe_after_backfill(db)
    probe_who_may_confirm()
    probe_dead_ends()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
