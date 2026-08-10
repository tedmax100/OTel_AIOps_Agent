#!/usr/bin/env python3
"""Break every guard on purpose and assert it goes red, with a hard exit code.

A guard that has never refused anything is, evidentially, the same as a guard
that does not exist. `test_*.py` prove each mechanism in isolation; this asserts
the *refusals* as a suite, the way `day12/regress.sh` asserts registry policy:
every case names the guard, the input that should trip it, and the exact refusal
expected. Exit 0 = every guard refused as specified. Exit 1 = one of them let
something through, which is the only failure mode that matters here.

Grouped by which plane the guard lives in:

  governance   autonomy is withheld: irreversibility, confidence, calibration,
               label provenance, grading mode
  blast radius the read-only footprint gate: protected/off-allowlist namespaces,
               singletons, scale-to-zero, pod ceiling, unreadable dry-run
  calibration  the reliability curve, not the signed mean: offsetting errors,
               an empty decision band, and thin bins that must be skipped loudly
  actuation    can this credential still act — never checked, dead (401), stale,
               denied, or quietly holding a verb the safety design forbids
  reconcile    time itself moves the state machine now, and it may only make the
               record honest: no retry, no rollback, no decision on a human's behalf
  breaker      runaway (global rate limit) and flapping (consecutive failures on
               one target), plus "only a human closes it again"

Temp SQLite plus the real modules. No cluster, no LLM.

    python3 ironman-2026/day33/regress_guards.py
    python3 ironman-2026/day33/regress_guards.py -v    # print every case
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[3] / "aiops-agent" / "service"
sys.path.insert(0, str(SERVICE))

from app import audit, blast_radius, breaker, store  # noqa: E402
from app.actions import ActionSpec  # noqa: E402
from app.blast_radius import BlastRadius  # noqa: E402
from app.calibration import CULPRIT, compute_calibration, load_records  # noqa: E402
from app.config import settings  # noqa: E402
from app.governance import Autonomy, decide  # noqa: E402

DB = Path(tempfile.mkdtemp()) / "guards.db"
VERBOSE = "-v" in sys.argv

_results: list[tuple[bool, str, str]] = []


def expect(name: str, ok: bool, got: str) -> None:
    _results.append((ok, name, got))
    if VERBOSE or not ok:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}\n        {got}")


def spec(**kw: object) -> ActionSpec:
    base = dict(name="k8s.test", description="t", reversible=True, requires_approval=False)
    return ActionSpec(**{**base, **kw})


def seed(
    n: int, source: str, mode: str | None, *, confidence: float = 0.9, correct: bool = True
) -> None:
    for i in range(n):
        rid = f"{source}-{mode}-{i}"
        store.cal_insert(
            run_id=rid,
            ts="2026-08-08T00:00:00Z",
            confidence=confidence,
            summary="s",
            hypothesis="h",
            suspected_version=None,
            services=["payment-service"],
            grading_mode=mode,
            path=DB,
        )
        store.cal_label(rid, correct, score=None, source=source, path=DB)


def clear_calibration() -> None:
    with store._connect(DB) as conn:
        conn.execute("DELETE FROM calibration")


# ---- governance -------------------------------------------------------------


def governance_guards() -> None:
    print("governance")
    perfect = {"labeled": 50, "overconfidence": 0.0}

    d = decide(spec(reversible=False), 1.0, perfect, path=DB)
    expect(
        "irreversible action never goes autonomous, even at confidence 1.0",
        d.autonomy is Autonomy.ESCALATE,
        f"{d.autonomy.value}: {d.reason}",
    )

    d = decide(spec(), 0.4, perfect, path=DB)
    expect(
        "confidence below the low threshold escalates",
        d.autonomy is Autonomy.ESCALATE,
        f"{d.autonomy.value}: {d.reason}",
    )

    d = decide(spec(requires_approval=True), 0.99, perfect, path=DB)
    expect(
        "an approval-gated action is never AUTO",
        d.autonomy is Autonomy.PROPOSE,
        f"{d.autonomy.value}: {d.reason}",
    )

    # From here on the human-label floor must already be satisfied, or every
    # case below would pass on that gate instead of the one under test.
    seed(settings.governance_min_human_labeled_runs, "grader", CULPRIT)

    over = {"labeled": 50, "overconfidence": 0.25}
    d = decide(spec(), 0.9, over, path=DB)
    expect(
        f"overconfidence {over['overconfidence']} > {settings.governance_max_overconfidence} "
        "downgrades AUTO to PROPOSE",
        d.autonomy is Autonomy.PROPOSE and "calibration not proven-good" in d.reason,
        f"{d.autonomy.value}: {d.calibration_note}",
    )

    # Provenance: 50 self-produced labels must not unlock autonomy.
    clear_calibration()
    seed(50, "remediation-verified", CULPRIT)
    calib = compute_calibration(load_records(DB), modes=(CULPRIT,))
    d = decide(spec(), 0.9, calib, path=DB)
    expect(
        "50 self-produced labels do not unlock AUTO",
        d.autonomy is Autonomy.PROPOSE and "self-produced" in d.calibration_note,
        f"{d.autonomy.value}: {d.calibration_note}",
    )

    # Grading mode: 50 hedging verdicts are not evidence about blame.
    clear_calibration()
    seed(50, "eval-harness", "inconclusive")
    calib = compute_calibration(load_records(DB), modes=(CULPRIT,))
    d = decide(spec(), 0.9, calib, path=DB)
    expect(
        "50 inconclusive-graded labels do not unlock AUTO",
        d.autonomy is Autonomy.PROPOSE and calib["labeled"] == 0,
        f"{d.autonomy.value}: curve saw {calib['labeled']} eligible row(s); {d.calibration_note}",
    )

    # Unknown provenance fails closed rather than being assumed to be culprit.
    clear_calibration()
    seed(50, "ui", None)
    calib = compute_calibration(load_records(DB), modes=(CULPRIT,))
    d = decide(spec(), 0.9, calib, path=DB)
    expect(
        "labels with no recorded grading mode do not unlock AUTO",
        d.autonomy is Autonomy.PROPOSE,
        f"{d.autonomy.value}: curve saw {calib['labeled']} eligible row(s)",
    )

    # The positive control: without it, every case above could pass for the
    # wrong reason (a gate that refuses everything is not a gate).
    clear_calibration()
    seed(50, "eval-harness", CULPRIT, confidence=0.9, correct=True)
    calib = compute_calibration(load_records(DB), modes=(CULPRIT,))
    d = decide(spec(), 0.9, calib, path=DB)
    expect(
        "[control] 50 culprit-graded grader labels DO reach AUTO",
        d.autonomy is Autonomy.AUTO,
        f"{d.autonomy.value}: {d.calibration_note}",
    )


# ---- calibration curve ------------------------------------------------------


def _curve(*groups: tuple[float, int, int]) -> dict:
    """(stated confidence, n, n_correct)... → a real calibration dict, built by
    running the real math over real records. A hand-written {"labeled": ...,
    "overconfidence": ...} can express a curve `compute_calibration` would never
    produce, and a guard that passes on one is guarding a shape that cannot occur."""
    clear_calibration()
    for conf, n, n_ok in groups:
        for i in range(n):
            rid = f"curve-{conf}-{i}"
            store.cal_insert(
                run_id=rid,
                ts="2026-08-08T00:00:00Z",
                confidence=conf,
                summary="s",
                hypothesis="h",
                suspected_version=None,
                services=["payment-service"],
                grading_mode=CULPRIT,
                path=DB,
            )
            store.cal_label(rid, i < n_ok, score=None, source="grader", path=DB)
    return compute_calibration(load_records(DB), modes=(CULPRIT,))


def calibration_curve_guards() -> None:
    """The mean is a signed average, so two opposite errors cancel into a number
    that reads as healthy. These assert the gate reads the bins, where they can't."""
    print("calibration curve")

    # Underconfident on the easy half, overconfident on the hard half. The mean
    # lands inside tolerance; the agent is wrong in both directions.
    calib = _curve((0.3, 12, 8), (0.9, 10, 5))
    d = decide(spec(), 0.9, calib, path=DB)
    expect(
        "offsetting errors do not unlock AUTO, even though the mean passes",
        d.autonomy is Autonomy.PROPOSE
        and calib["overconfidence"] <= settings.governance_max_overconfidence,
        f"{d.autonomy.value}: mean {calib['overconfidence']:+} is inside tolerance; "
        f"{d.calibration_note}",
    )

    # Plenty of labels, none of them in the band where AUTO is actually granted.
    calib = _curve((0.6, 18, 12), (0.3, 4, 1))
    d = decide(spec(), 0.9, calib, path=DB)
    expect(
        "labels that never reach the decision band do not unlock AUTO",
        d.autonomy is Autonomy.PROPOSE and "no evidence in the band" in d.calibration_note,
        f"{d.autonomy.value}: {d.calibration_note}",
    )

    # A one-row bin is 0% or 100% accurate by construction. It must not be
    # treated as the worst bin, and the skip must be reported rather than hidden.
    calib = _curve((0.9, 45, 45), (0.5, 1, 0))
    d = decide(spec(), 0.9, calib, path=DB)
    expect(
        "[control] a thin bin is skipped, said so, and does not block AUTO",
        d.autonomy is Autonomy.AUTO and "too thin to count" in d.calibration_note,
        f"{d.autonomy.value}: {d.calibration_note}",
    )


# ---- actuation readiness ----------------------------------------------------


def actuation_guards() -> None:
    """"May we act" was always gated; "can we still act" was assumed, and that
    assumption cost this system its only real execution. Every way of not
    knowing must read as not-ready."""
    print("actuation readiness")
    import time

    from app.signals import actuation as act

    def verdict(**kw: object) -> dict:
        base = dict(
            computed_ts=time.time(),
            reachable=True,
            in_cluster=True,
            missing=[],
            excess=[],
            namespaces=["demo"],
            error=None,
        )
        base.update(kw)
        act._last = act.ActuationFit(**base)  # type: ignore[arg-type]
        return act.actuation_verdict()

    act._last = None
    v = act.actuation_verdict()
    expect(
        "a credential that was never checked is not ready",
        not v["proven_good"] and "never checked" in v["note"],
        v["note"],
    )

    v = verdict(reachable=False, error="ApiException: Unauthorized")
    expect(
        "a 401 reads as an authentication failure, not as a denied permission",
        not v["proven_good"] and "did not authenticate" in v["note"],
        v["note"],
    )

    v = verdict(computed_ts=time.time() - 10 * settings.actuation_max_age_seconds)
    expect(
        "a permission checked long enough ago is a permission being assumed",
        not v["proven_good"] and "stale" in v["note"],
        v["note"],
    )

    v = verdict(missing=["patch apps/deployments in demo"])
    expect(
        "a denied required permission is not ready, and names the rule",
        not v["proven_good"] and "patch apps/deployments in demo" in v["note"],
        v["note"],
    )

    # Gaining `delete` is not an improvement: every blast-radius policy in this
    # repo was written assuming the write credential cannot do it.
    v = verdict(excess=["delete apps/deployments in demo"])
    expect(
        "a write credential that gained delete is refused, not congratulated",
        not v["proven_good"] and "forbids" in v["note"],
        v["note"],
    )

    v = verdict(in_cluster=False)
    expect(
        "a dev kubeconfig cannot prove anything about the deployed identity",
        not v["proven_good"] and "local kubeconfig" in v["note"],
        v["note"],
    )

    v = verdict()
    d = decide(
        spec(), 0.9, _curve((0.9, 45, 45)), {"proven_good": True, "note": "dq ok"}, v, path=DB
    )
    expect(
        "[control] healthy credentials are proven-good and do reach AUTO",
        v["proven_good"] and d.autonomy is Autonomy.AUTO,
        f"{d.autonomy.value}: {v['note']}",
    )

    d = decide(
        spec(),
        0.9,
        _curve((0.9, 45, 45)),
        {"proven_good": True, "note": "dq ok"},
        verdict(reachable=False, error="ApiException: Unauthorized"),
        path=DB,
    )
    expect(
        "a dead credential narrows autonomy before anything is proposed",
        d.autonomy is Autonomy.PROPOSE and "actuation readiness" in d.reason,
        f"{d.autonomy.value}: {d.reason}",
    )
    act._last = None


# ---- lifecycle reconciliation -----------------------------------------------


def reconcile_guards() -> None:
    """Reconciliation may make the record honest and may do nothing else. These
    assert both halves: that time now moves the state machine, and that it never
    decides anything on a human's behalf."""
    print("lifecycle reconciliation")
    import sqlite3

    from app import action_requests as arq
    from app.action_requests import Status

    def propose(fp: str) -> str:
        d = decide(spec(name="k8s.rollout_undo", requires_approval=True), 0.6, {}, path=DB)
        req = arq.create_from_decision(fp, d, args={"deployment": "payment-service"}, path=DB)
        return req.request_id

    def backdate(rid: str) -> None:
        conn = sqlite3.connect(str(DB))
        conn.execute(
            "UPDATE action_requests SET created_ts=?, expires_ts=? WHERE request_id=?",
            ("2020-01-01T00:00:00Z", "2020-01-01T00:15:00Z", rid),
        )
        conn.commit()
        conn.close()

    stale = propose("fp-stale")
    backdate(stale)
    fresh = propose("fp-fresh")
    out = arq.reconcile(path=DB)
    expect(
        "a proposal past its TTL expires with nobody knocking",
        stale in out["expired"] and arq.get(stale, DB).status == Status.EXPIRED.value,
        f"expired {len(out['expired'])}, status now {arq.get(stale, DB).status}",
    )
    expect(
        "[control] a proposal still inside its TTL is left alone",
        fresh not in out["expired"] and arq.get(fresh, DB).status == Status.PROPOSED.value,
        f"status still {arq.get(fresh, DB).status}",
    )

    abandoned = propose("fp-abandoned")
    store.ar_transition(abandoned, Status.PROPOSED.value, Status.APPROVED.value, path=DB)
    store.ar_transition(abandoned, Status.APPROVED.value, Status.EXECUTING.value, path=DB)
    backdate(abandoned)
    out = arq.reconcile(path=DB)
    row = arq.get(abandoned, DB)
    expect(
        "an executing row whose executor vanished is written off, not left running",
        abandoned in out["abandoned"] and row.status == Status.FAILED.value,
        f"status {row.status}: {row.outcome}",
    )
    expect(
        "and it is NOT rolled back, because whether the write landed is unknown",
        "unknown" in row.outcome
        and not [
            e
            for e in audit.history(request_id=abandoned, path=DB)
            if e["phase"] == "rollback"
        ],
        f"outcome says: {row.outcome}",
    )

    live = propose("fp-live")
    store.ar_transition(live, Status.PROPOSED.value, Status.APPROVED.value, path=DB)
    store.ar_transition(live, Status.APPROVED.value, Status.EXECUTING.value, path=DB)
    out = arq.reconcile(path=DB)
    expect(
        "[control] an execution still inside the settle window survives a pass",
        live not in out["abandoned"] and arq.get(live, DB).status == Status.EXECUTING.value,
        f"status still {arq.get(live, DB).status}",
    )

    # Day30: reject() had no TTL check while approve() did, so two equally
    # lapsed proposals ended up telling two different stories.
    lapsed = propose("fp-lapsed")
    backdate(lapsed)
    result = arq.reject(lapsed, "nathan", DB)
    expect(
        "rejecting a lapsed proposal expires it instead of recording a human decision",
        result is None and arq.get(lapsed, DB).status == Status.EXPIRED.value,
        f"status {arq.get(lapsed, DB).status}, not rejected-by-a-person",
    )


# ---- blast radius -----------------------------------------------------------


def blast_radius_guards() -> None:
    print("blast radius")

    def br(**kw: object) -> BlastRadius:
        base = dict(
            action="k8s.rollout_undo",
            target="demo/payment-service",
            namespace="demo",
            current_revision="25",
            target_revision="24",
            current_replicas=2,
            target_replicas=2,
            affected_pods=2,
        )
        return BlastRadius(**{**base, **kw})

    cases = [
        (
            "an unreadable dry-run fails closed",
            br(available=False, detail="k8s API unreachable"),
            "fail-closed",
        ),
        (
            "a protected namespace is refused",
            br(namespace="kube-system", in_protected_namespace=True),
            "protected",
        ),
        (
            "a namespace off the allowlist is refused",
            br(namespace="prod"),
            "not in allowlist",
        ),
        (
            "an action crossing namespaces is refused",
            br(cross_namespace=True),
            "crosses namespaces",
        ),
        (
            "scale-to-zero is refused, and says so instead of blaming singleton",
            br(action="k8s.scale", target_replicas=0, current_replicas=1, singleton=True),
            "fully down",
        ),
        (
            "a single-replica target is refused",
            br(current_replicas=1, target_replicas=1, affected_pods=1, singleton=True),
            "singleton",
        ),
        (
            f"more than {settings.max_blast_pods} affected pods is refused",
            br(current_replicas=9, target_replicas=9, affected_pods=9),
            "exceeds max",
        ),
        (
            "a rollback with no previous revision is refused",
            br(target_revision=None),
            "no previous revision",
        ),
    ]
    for name, radius, fragment in cases:
        ok, reason = blast_radius.evaluate_policy(radius)
        expect(name, (not ok) and fragment in reason, f"ok={ok}: {reason}")

    ok, reason = blast_radius.evaluate_policy(br())
    expect("[control] a 2-pod rollback inside demo is allowed", ok, f"ok={ok}: {reason}")


# ---- breaker ----------------------------------------------------------------


def breaker_guards() -> None:
    print("breaker")
    action, target = "k8s.rollout_undo", "demo/payment-service"
    breaker.reset(path=DB)

    ok, reason = breaker.check(action, target, path=DB)
    expect("[control] a fresh breaker allows", ok, f"ok={ok}: {reason}")

    # Flapping: consecutive failures on one target trip that target's breaker.
    for _ in range(settings.breaker_fail_threshold):
        breaker.record_outcome(action, target, success=False, path=DB)
    ok, reason = breaker.check(action, target, path=DB)
    expect(
        f"{settings.breaker_fail_threshold} consecutive failures trip the target breaker",
        (not ok) and "breaker open" in reason,
        f"ok={ok}: {reason}",
    )

    # A tripped breaker must not close on its own — only a human clears it.
    ok, _ = breaker.check(action, target, path=DB)
    expect("a tripped breaker stays open on the next check", not ok, "still open")
    cleared = breaker.reset(scope=breaker.scope_key(action, target), path=DB)
    ok, reason = breaker.check(action, target, path=DB)
    expect(
        "only an explicit human reset closes it again",
        cleared == 1 and ok,
        f"reset cleared {cleared}; now ok={ok}: {reason}",
    )

    # Runaway: the global window rate limit, independent of success/failure.
    breaker.reset(path=DB)
    with store._connect(DB) as conn:
        conn.execute("DELETE FROM executions")
    other = "demo/order-service"
    for _ in range(settings.breaker_max_actions_per_window):
        breaker.record_outcome(action, other, success=True, path=DB)
    ok, reason = breaker.check(action, target, path=DB)
    expect(
        f"{settings.breaker_max_actions_per_window} executions in "
        f"{settings.breaker_window_seconds}s trips the global rate limit",
        (not ok) and "rate limit" in reason,
        f"ok={ok}: {reason}",
    )


def main() -> int:
    governance_guards()
    calibration_curve_guards()
    actuation_guards()
    reconcile_guards()
    blast_radius_guards()
    breaker_guards()

    failed = [name for ok, name, _ in _results if not ok]
    print()
    print(f"{len(_results) - len(failed)}/{len(_results)} guards behaved as specified")
    if failed:
        print("guards that did NOT refuse:")
        for name in failed:
            print(f"  - {name}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
