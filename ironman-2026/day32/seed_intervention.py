#!/usr/bin/env python3
"""Plant one human intervention, so its effect can be measured.

The four feedback channels were built and never measured: every eval run so far
went against an empty case library with nobody having labeled or declined
anything. This plants exactly one intervention on the session-cache incident
and nothing else, so a before/after on that fixture is about the intervention
rather than about which run happened to get labeled that day.

**What it deliberately does not write is the point.** The agent's three wrong
answers on this fixture were "order-service's own code", "payment declines" and
"payment-service". A person who has read those transcripts knows the answer, and
writing it here would make the next run a retrieval test with a known result.
So the intervention is a *disproof only*:

  case_ruled_out: OrderAuthFailureRateHigh / order-service
    [hypothesis] a code regression in order-service itself   (disproved_by=human)
    [hypothesis] payment-service declines                    (disproved_by=human)

Neither says user-service. Both remove a branch the agent kept walking into.
That is what a colleague standing behind you actually says — "no, it's not the
order code, I looked" — and it is the weakest useful form of the intervention,
which makes it the honest one to measure.

`library_overlap()` will still report this fixture as OPEN BOOK, and it is right
to: the run is being handed something a human learned from an earlier attempt at
the same incident. The claim being tested is narrower than "recall helps" — it
is "does removing two wrong branches change the answer".

    python3 ironman-2026/day32/seed_intervention.py            # into aiops.db
    python3 ironman-2026/day32/seed_intervention.py --clear     # retract it
    python3 ironman-2026/day32/seed_intervention.py --store /tmp/x.db
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "aiops-agent" / "service"))

os.environ.setdefault("GOOGLE_API_KEY", "seed-does-not-call-a-model")

from app import store  # noqa: E402

ALERTNAME = "OrderAuthFailureRateHigh"
SERVICE = "order-service"

# The two branches the transcripts actually went down, in the words a person
# would use. No third entry naming the cause.
DISPROVED = [
    (
        "a code regression in order-service itself",
        "read the order-service diff for the window, nothing shipped",
    ),
    (
        "payment-service declines causing the cancellations",
        "the cancellations are tagged reason=auth, not reason=payment",
    ),
]


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=None, help="store path (default: settings.store_path)")
    ap.add_argument("--clear", action="store_true", help="retract the intervention")
    args = ap.parse_args()
    path = args.store
    if path:
        store.settings.store_path = path

    key = store.case_key(ALERTNAME, SERVICE)
    if args.clear:
        print(f"case {key} -> {store.case_forget(key, path=path)}")
        return 0

    store.case_upsert(key=key, ts=now(), alertname=ALERTNAME, service=SERVICE, path=path)
    for subject, evidence in DISPROVED:
        store.ruled_out_insert(
            key=key,
            run_id="manual-intervention",
            ts=now(),
            kind="hypothesis",
            subject=subject,
            evidence=evidence,
            disproved_by="human",
            path=path,
        )

    live = store.case_ruled_out_for([key], path=path)
    print(f"case {key}  ({ALERTNAME} / {SERVICE})")
    print(f"  root cause recorded: {store.case_get(key, path)['root_cause']!r}")
    for row in live:
        print(f"  ruled out [{row['kind']}] {row['subject']}")
    print()
    print("what the next run will be handed:")
    from app.agent import _past_incident_context

    block = _past_incident_context(SERVICE, ALERTNAME)
    print("  " + (block.replace("\n", "\n  ") if block else "(nothing)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
