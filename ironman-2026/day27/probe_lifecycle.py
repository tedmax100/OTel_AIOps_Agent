#!/usr/bin/env python3
"""Push the action-request state machine at the edges its unit tests don't reach.

The 9 tests in `test_action_requests.py` pin the happy paths plus three refusals
(double-approve, approve-after-TTL, approve-missing). All three call the API
sequentially, on one thread, and stop at "the second call returns None". That is
enough to prove the intent and not enough to prove the mechanism.

Four probes here, each printing what the row actually looks like afterwards:

  1. real concurrency — N threads calling approve() on the same request at once
  2. reject() has no TTL check, unlike approve()
  3. expiry is lazy: a stale request stays `proposed` in the list until someone
     tries to approve it
  4. a request stuck in `executing` (the pod died mid-run) can never be re-claimed

No cluster, no LLM: a temp SQLite file and the real modules.

    python3 ironman-2026/day27/probe_lifecycle.py
"""

from __future__ import annotations

import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[3] / "aiops-agent" / "service"
sys.path.insert(0, str(SERVICE))

import app.action_requests as arq  # noqa: E402
from app import store  # noqa: E402
from app.action_requests import (  # noqa: E402
    ActionRequest,
    Status,
    approve,
    create_from_decision,
    get,
    reject,
)
from app.governance import Autonomy, Decision  # noqa: E402

DB = Path(tempfile.mkdtemp()) / "probe.db"
arq.settings.store_path = str(DB)
arq.settings.action_requests_enabled = True

THREADS = 8


def decision(action: str = "k8s.rollout_undo") -> Decision:
    return Decision(
        action=action,
        autonomy=Autonomy.PROPOSE,
        requires_human=True,
        confidence=0.9,
        reason="probe",
        calibration_note="probe",
        reversible=True,
        requires_approval=True,
    )


def new_request(fp: str) -> ActionRequest | None:
    return create_from_decision(
        fp, decision(), args={"deployment": "payment-service"}, path=DB
    )


def backdate(request_id: str, seconds: int) -> None:
    """Move a row's expiry into the past without touching status — the same thing
    the clock does while nobody is looking at the plugin."""
    past = datetime.now(UTC) - timedelta(seconds=seconds)
    with store._write_lock, store._connect(DB) as conn:
        conn.execute(
            "UPDATE action_requests SET expires_ts=? WHERE request_id=?",
            [past.strftime("%Y-%m-%dT%H:%M:%SZ"), request_id],
        )


def show(tag: str, request_id: str) -> None:
    r = get(request_id, DB)
    print(f"    {tag:<22} status={r.status:<10} actor={r.actor} outcome={r.outcome!r}")


def probe_concurrent_approve() -> None:
    print(f"[1] {THREADS} threads approve the same request simultaneously")
    req = new_request("fp-concurrent")
    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        results = list(
            pool.map(lambda i: approve(req.request_id, actor=f"human-{i}", path=DB), range(THREADS))
        )
    winners = [r for r in results if r is not None]
    print(f"    approve() returned a request {len(winners)} time(s) out of {THREADS}")
    show("after", req.request_id)


def probe_reject_ignores_ttl() -> None:
    print("\n[2] the same stale request: approve() vs reject()")
    a = new_request("fp-stale-a")
    b = new_request("fp-stale-b")
    backdate(a.request_id, 60)
    backdate(b.request_id, 60)

    print(f"    approve() -> {approve(a.request_id, actor='human', path=DB)}")
    show("approved path", a.request_id)
    r = reject(b.request_id, actor="human", path=DB)
    print(f"    reject()  -> {'a request' if r else None}")
    show("rejected path", b.request_id)


def probe_lazy_expiry() -> None:
    print("\n[3] a stale request nobody touches")
    req = new_request("fp-lazy")
    backdate(req.request_id, 60)
    listed = [r for r in arq.list_requests(status="proposed", limit=50, path=DB)
              if r["request_id"] == req.request_id]
    print(f"    listed under status=proposed: {len(listed)}")
    show("stored", req.request_id)


def probe_stuck_executing() -> None:
    print("\n[4] the pod dies between claim and outcome")
    req = new_request("fp-stuck")
    approve(req.request_id, actor="human", path=DB)
    claimed = store.ar_transition(
        req.request_id, Status.APPROVED.value, Status.EXECUTING.value, path=DB
    )
    print(f"    executor claimed it: {claimed}")
    show("after the crash", req.request_id)
    again = store.ar_transition(
        req.request_id, Status.APPROVED.value, Status.EXECUTING.value, path=DB
    )
    print(f"    a restarted executor re-claims it: {again}")
    print(f"    approve() on it now: {approve(req.request_id, actor='human', path=DB)}")


if __name__ == "__main__":
    print(f"db: {DB}\n")
    probe_concurrent_approve()
    probe_reject_ignores_ttl()
    probe_lazy_expiry()
    probe_stuck_executing()
