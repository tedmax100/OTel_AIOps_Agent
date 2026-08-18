#!/usr/bin/env python3
"""Plant one confirmed case so the recall A/B has something to recall.

Without this the experiment is not reproducible: you would run the suite, label
a run by hand in the plugin, and run it again — and the thing you labeled is a
different investigation each time, so the two arms differ by more than the
setting under test.

What it writes is deliberately minimal, and goes through the real entry points
(`case_upsert` + `confirm_from_label`) rather than raw SQL, so the policy that
decides what may become precedent is the one being exercised:

  cases: PaymentHighDeclineRate / payment-service
    root_cause        the v2.5.0 regression, in the words a human would use
    root_cause_source "manual" (a person at a CLI — a trusted, non-self source)
    status            resolved

  case_ruled_out: two dead ends the transcripts really produced
    [query] Loki stream selector on `service`     — not indexable here
    [query] Tempo tags spelled `service_name`     — 400, wants resource.service.name

The git_version in `--fp-version` is what makes this a *recurrence* test: the
seeded fingerprint is computed from a different version than the one the eval
alert will carry, so under the old key the two are unrelated investigations and
recall cannot fire. If it fires, the case key survived the redeploy.

    python3 ironman-2026/day38/seed_case.py                 # into aiops.db
    python3 ironman-2026/day38/seed_case.py --clear         # remove it again
    python3 ironman-2026/day38/seed_case.py --store /tmp/x.db
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SERVICE = ROOT / "aiops-agent" / "service"
sys.path.insert(0, str(SERVICE))

from app import case_memory, store  # noqa: E402

ALERTNAME = "PaymentHighDeclineRate"
SERVICE_NAME = "payment-service"
ROOT_CAUSE = (
    "v2.5.0 shipped a new charge validator that rejects odd-cent amounts; "
    "the decline rate tracks the rollout, not traffic"
)
DEAD_ENDS = [
    (
        "query",
        'LogQL stream selector {service="payment-service"}',
        "`service` is not an indexable stream label here — the selector is valid "
        "and matches nothing; use service_name",
    ),
    (
        "query",
        'TraceQL tag service_name="payment-service"',
        "Tempo answers 400 unexpected IDENTIFIER — the tag is resource.service.name",
    ),
]


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fp(version: str) -> str:
    """The same computation as `webhook.fingerprint`, for a past occurrence on
    another version. Imported would be cleaner, but importing webhook drags in
    the agent graph for one sha256."""
    key = "|".join([ALERTNAME, SERVICE_NAME, version])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def seed(store_path: Path, fp_version: str) -> None:
    key = store.case_key(ALERTNAME, SERVICE_NAME)
    run_id = f"{_fp(fp_version)}-seeded"
    store.case_upsert(
        key=key,
        ts=_now(),
        alertname=ALERTNAME,
        service=SERVICE_NAME,
        path=store_path,
    )
    verdict = case_memory.confirm_from_label(
        case_key=key,
        correct=True,
        source="manual",
        grading_mode=store.CULPRIT,
        root_cause=ROOT_CAUSE,
        run_id=run_id,
        resolution={"action": "k8s.rollout_undo", "outcome": "decline rate returned to baseline"},
        path=store_path,
    )
    for kind, subject, evidence in DEAD_ENDS:
        store.ruled_out_insert(
            key=key,
            run_id=run_id,
            ts=_now(),
            kind=kind,
            subject=subject,
            evidence=evidence,
            disproved_by="tool_result",
            path=store_path,
        )
    row = store.case_get(key, store_path)
    print(f"case {key} -> {verdict}")
    print(f"  occurrences       {row['occurrences']}")
    print(f"  status            {row['status']}")
    print(f"  root_cause_source {row['root_cause_source']}")
    print(f"  seeded from fp    {_fp(fp_version)}  (git_version {fp_version})")
    print(f"  dead ends         {len(store.case_ruled_out_for([key], path=store_path))}")


def clear(store_path: Path) -> None:
    key = store.case_key(ALERTNAME, SERVICE_NAME)
    retired = store.ruled_out_invalidate(key, path=store_path)
    ok = store.case_set_status(key, "false_positive", path=store_path)
    # Status alone would still leave the root cause on the row; blank it so the
    # control arm really is a control.
    with store._connect(store_path) as conn:
        conn.execute(
            "UPDATE cases SET root_cause=NULL, root_cause_source=NULL, status='open' "
            "WHERE case_key=?",
            (key,),
        )
    print(f"cleared case {key} (row existed: {ok}), retired {retired} dead end(s)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--store",
        type=Path,
        default=SERVICE / "aiops.db",
        help="store the agent reads at runtime (settings.store_path), NOT the eval store",
    )
    ap.add_argument(
        "--fp-version",
        default="v2.4.9",
        help="git_version of the past occurrence this case was learned from",
    )
    ap.add_argument("--clear", action="store_true", help="undo the seed")
    args = ap.parse_args()

    print(f"store: {args.store}")
    if args.clear:
        clear(args.store)
    else:
        seed(args.store, args.fp_version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
