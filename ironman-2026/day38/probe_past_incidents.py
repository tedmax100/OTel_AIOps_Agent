#!/usr/bin/env python3
"""Why the past-incident library is still empty after 35 labeled runs.

`_past_incident_context()` retrieves precedent with one JOIN:

    SELECT i.payload FROM investigations i
    JOIN calibration c ON c.run_id = i.fp
    WHERE ... AND c.correct = 1

Day38 filled the calibration side. The library is still empty, because the two
tables have different writers: `webhook.handle_alert` writes both, and the eval
harness — the only thing producing graded runs — calls `run_headless` directly
and writes only calibration. A JOIN over a table nobody fills returns nothing no
matter how good the other side looks.

Four probes on a temp store, no cluster and no LLM:

  1. the real store: labeled runs vs retrievable precedent
  2. calibration-only rows retrieve nothing (the seam, reproduced)
  3. both tables written under the same id → precedent appears
  4. a hedged non-incident must NOT come back as precedent (the Day39 column
     doing its job), and neither must an unlabeled or unknown-mode row

    python3 ironman-2026/day38/probe_past_incidents.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SERVICE = ROOT / "aiops-agent" / "service"
sys.path.insert(0, str(SERVICE))

from app import store  # noqa: E402

DB = Path(tempfile.mkdtemp()) / "probe.db"
SERVICE_NAME = "payment-service"
ALERTNAME = "PaymentDeclineSpike"


def plant_calibration(run_id: str, *, correct: bool | None, mode: str | None) -> None:
    store.cal_insert(
        run_id=run_id,
        ts="2026-08-01T00:00:00Z",
        confidence=0.8,
        summary=f"summary for {run_id}",
        hypothesis="h",
        suspected_version="v2.5.0",
        services=[SERVICE_NAME],
        grading_mode=mode,
        path=DB,
    )
    if correct is not None:
        store.cal_label(run_id, correct, score=None, source="eval-harness", path=DB)


def plant_investigation(fp: str) -> None:
    payload = {
        "fp": fp,
        "ts": "2026-08-01T00:00:00Z",
        "service": SERVICE_NAME,
        "alertname": ALERTNAME,
        "summary": f"summary for {fp}",
        "hypothesis": "h",
        "confidence": 0.8,
        "suspected_version": "v2.5.0",
    }
    store.inv_insert(fp, payload["ts"], json.dumps(payload), path=DB)


def retrieved() -> list[str]:
    rows = store.inv_query_similar(service=SERVICE_NAME, alertname=ALERTNAME, path=DB)
    return [r["fp"] for r in rows]


def main() -> None:
    print("[1] the real store")
    real = ROOT / "aiops.db"
    labeled = store.cal_count_by_source(path=real)
    invs = len(store.inv_load(real))
    hits = store.inv_query_similar(service=SERVICE_NAME, path=real)
    print(f"    calibration labeled rows: {labeled}")
    print(f"    investigations rows:      {invs}")
    print(f"    retrievable precedent:    {len(hits)}")
    print()

    print("[2] a graded run with no investigation row (what the harness writes today)")
    plant_calibration("calib-only", correct=True, mode=store.CULPRIT)
    print(f"    retrieved: {retrieved()}")
    print()

    print("[3] the same run, both tables, same id")
    plant_calibration("both", correct=True, mode=store.CULPRIT)
    plant_investigation("both")
    print(f"    retrieved: {retrieved()}")
    print()

    print("[4] rows that must never come back as precedent")
    cases = [
        ("hedged-non-incident", True, store.INCONCLUSIVE, "correct=1 but it blamed nobody"),
        ("wrong-run", False, store.CULPRIT, "graded wrong"),
        ("unlabeled", None, store.CULPRIT, "no verdict yet"),
        ("unknown-mode", True, None, "correct=1, but nobody said what that means"),
    ]
    for fp, correct, mode, why in cases:
        plant_calibration(fp, correct=correct, mode=mode)
        plant_investigation(fp)
        got = retrieved()
        print(f"    +{fp:<22} ({why})")
        print(f"     retrieved: {got}  -> {'LEAKED' if fp in got else 'excluded'}")

    print()
    print(f"    final: {retrieved()}")


if __name__ == "__main__":
    main()
