#!/usr/bin/env python3
"""What the agent keeps when a person intervenes.

Day38 gave the agent a memory of its own incidents. Everything a *person* did
was still thrown away: a verdict of "wrong" moved one calibration row and
taught the case nothing, and a declined action was durable as a status with no
reason attached, so the next run proposed it again — not because the model was
stubborn, but because the record allowed nothing else.

Six probes over the two channels a person actually touches (labeling a finished
investigation, deciding on a proposed action) plus the third that was already
being recorded and never read (what happened when a runbook was executed).
Everything runs through the real entry points against a temp store. No cluster,
no LLM.

  1. a human's "wrong" becomes a disproof, carrying their correction note
  2. who may disprove — the same allowlist shape as the root-cause side
  3. a declined action, its reason, and the gate that now refuses to re-ask
  4. what the next run actually sees
  5. runbook health: one verdict, read by the prompt and by the gate
  6. forgetting: the age-out, and the retraction for when a month is too long

    python3 ironman-2026/day39/probe_intervention_memory.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import ClassVar

# `app.capability` builds a Gemini client at import time, and probe 4 needs the
# recall block, which lives in `app.agent`. Nothing here calls a model — this
# only gets the import past a constructor that validates its key eagerly.
os.environ.setdefault("GOOGLE_API_KEY", "probe-does-not-call-a-model")

HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
SERVICE = ROOT / "aiops-agent" / "service"
sys.path.insert(0, str(SERVICE))

from app import (  # noqa: E402
    action_requests,
    agent,
    calibration,
    case_memory,
    governance,
    investigations,
    store,
)

ALERT = "PaymentChargeLatencyHigh"
SERVICE_NAME = "payment-service"
TARGET = {"namespace": "demo", "deployment": "payment-service"}


def h(n: int, title: str) -> None:
    print(f"\n[{n}] {title}")


def fresh_store() -> Path:
    p = Path(tempfile.mkdtemp()) / "aiops.db"
    store.settings.store_path = str(p)
    case_memory.settings.case_memory_enabled = True
    return p


class Findings:
    """The shape `calibration.record_run` reads. The summary is the thing a
    person is about to say is wrong."""

    confidence = 0.8
    hypothesis = "code regression"
    suspected_version = "v2.5.0"
    services: ClassVar[list[str]] = [SERVICE_NAME]
    summary = "payment v2.5.0 new_validator rejects odd cents"


def one_run(p: Path, *, alertname: str = ALERT, fp: str = "fp1", propose: bool = False) -> tuple:
    """One investigation, recorded the way the headless path records it.

    `propose` matters more than it looks: `create_from_decision` reads the case
    scope to learn which incident it belongs to, and the real gate runs inside
    the run. Building the proposal after the scope closes produces a request
    with no case and no run — which is a legitimate state (it is what a chat
    turn produces) and drops the rejection on the floor.
    """
    with case_memory.case_scope(fp=fp, alertname=alertname, service=SERVICE_NAME) as sc:
        case_memory.observe(sc, path=p)
        rec = investigations.InvestigationRecord(
            fp=fp,
            run_id=sc.run_id,
            ts="2026-08-19T05:00:00Z",
            alertname=alertname,
            service=SERVICE_NAME,
            summary=Findings.summary,
        )
        store.inv_insert(
            fp, rec.ts, rec.model_dump_json(), p, run_id=sc.run_id, case_key=sc.case_key
        )
        calibration.record_run(Findings, run_id=sc.run_id, path=p, case_key=sc.case_key)
        req = proposal(p) if propose else None
    return sc, req


def proposal(p: Path, action: str = "k8s.rollout_undo") -> object:
    return action_requests.create_from_decision(
        "fp1",
        governance.Decision(
            action=action,
            autonomy=governance.Autonomy.PROPOSE,
            reason="runbook step",
            requires_human=True,
            reversible=True,
            confidence=0.8,
            calibration_note="",
            requires_approval=True,
        ),
        args=TARGET,
        path=p,
    )


def probe_1_wrong_becomes_a_disproof() -> None:
    h(1, 'a human says "wrong", and the case keeps it')
    p = fresh_store()
    sc, _ = one_run(p)
    calibration.label_run(
        sc.run_id,
        correct=False,
        source="ui",
        grading_mode=store.CULPRIT,
        correction_note="latency was flat on v2.5.0 — 0.041s vs 0.059s",
        path=p,
    )
    row = store.case_get(sc.case_key, p)
    print(f"    root_cause after a wrong verdict: {row['root_cause']!r}")
    for d in store.case_ruled_out_for([sc.case_key], path=p):
        print(f"    ruled out [{d['kind']}] {d['subject']}")
        print(f"              evidence: {d['evidence']}")
        print(f"              disproved_by: {d['disproved_by']}")


def probe_2_who_may_disprove() -> None:
    h(2, "who may disprove — and what an unfamiliar source gets")
    cases = [
        ("ui", store.CULPRIT, "a person, on a run that blamed someone"),
        ("eval-harness", store.CULPRIT, "the grader"),
        ("remediation-verified", store.CULPRIT, "the run grading its own fix"),
        ("some-new-bot", store.CULPRIT, "a source nobody has heard of"),
        ("ui", store.INCONCLUSIVE, "a person, on a run that blamed nobody"),
    ]
    for source, mode, blurb in cases:
        p = fresh_store()
        sc, _ = one_run(p)
        calibration.label_run(
            sc.run_id,
            correct=False,
            source=source,
            grading_mode=mode,
            correction_note="it was the ConfigMap",
            path=p,
        )
        n = len(store.case_ruled_out_for([sc.case_key], path=p))
        verdict = "recorded" if n else "ignored "
        print(f"    {source:22} {mode!s:14} -> {verdict:8}  ({blurb})")


def probe_3_a_refusal_binds() -> None:
    h(3, "a declined action, and the proposal that is not made again")
    p = fresh_store()
    sc, req = one_run(p, propose=True)
    action_requests.reject(
        req.request_id, actor="nathan", reason="we roll forward here, never back", path=p
    )
    stored = store.ar_get(req.request_id, p)
    print(f"    status={stored['status']}  decision_note={stored['decision_note']!r}")

    hit = case_memory.prior_rejection(sc.case_key, "k8s.rollout_undo", "demo/payment-service")
    d = governance.decide(
        governance.registry.get("k8s.rollout_undo"),
        0.95,
        {"labeled": 100, "overconfidence": 0.0},
        rejected=hit,
    )
    print(f"    next run's gate: {d.autonomy.value.upper()} — {d.reason}")

    for label, action, target in [
        ("same action, another target", "k8s.rollout_undo", "demo/order-service"),
        ("another action, same target", "k8s.restart", "demo/payment-service"),
    ]:
        bound = case_memory.prior_rejection(sc.case_key, action, target) is not None
        print(f"    {label:28} bound: {bound}")


def probe_4_what_the_next_run_sees() -> None:
    h(4, "what the next run is handed")
    p = fresh_store()
    sc, req = one_run(p, propose=True)
    calibration.label_run(
        sc.run_id,
        correct=False,
        source="ui",
        grading_mode=store.CULPRIT,
        correction_note="latency was flat on that version",
        path=p,
    )
    action_requests.reject(
        req.request_id, actor="nathan", reason="not during business hours", path=p
    )
    print("    " + agent._past_incident_context(SERVICE_NAME, ALERT).replace("\n", "\n    "))


def probe_5_runbook_health() -> None:
    h(5, "a runbook's own record, read twice")
    p = fresh_store()
    # The gate column below never says AUTO, and that is not this gate's doing:
    # every action in the shipped registry is `requires_approval=True`, and the
    # human-label floor is unmet on a fresh store. So the `proven_good` column
    # is where the runbook's record actually lands today, and only the
    # `suspended` row changes an outcome. See the README.
    ungated = governance.ActionSpec(
        name="k8s.rollout_undo",
        description="a hypothetical action that policy would let run on its own",
        reversible=True,
        requires_approval=False,
    )
    for label, outcomes in [
        ("never executed", []),
        ("one failure, one run", ["verify_failed"]),
        ("three clean", ["ok", "ok", "ok"]),
        ("failing verification", ["ok", "verify_failed", "verify_failed", "verify_failed"]),
        ("its undo did not work", ["ok", "ok", "ok", "rollback_failed"]),
    ]:
        rb_id = label.replace(" ", "-")
        for o in outcomes:
            store.rb_feedback_insert(runbook_id=rb_id, outcome=o, path=p)
        verdict = governance.runbook_health_verdict(rb_id, path=p)
        d = governance.decide(ungated, 0.95, {"labeled": 100, "overconfidence": 0.0}, rb=verdict)
        print(
            f"    {label:22} {verdict['status']:18} proven_good={verdict['proven_good']!s:5} "
            f"gate={d.autonomy.value:9}{verdict['note']}"
        )


def probe_6_forgetting() -> None:
    h(6, "nothing here is true forever")
    p = fresh_store()
    sc, req = one_run(p, propose=True)
    action_requests.reject(
        req.request_id, actor="nathan", reason="not during business hours", path=p
    )

    def live() -> int:
        return len(store.case_ruled_out_for([sc.case_key], path=p))

    print(f"    recalled now:                       {live()}")
    original = store.settings.case_dead_end_max_age_days
    store.settings.case_dead_end_max_age_days = -1
    print(f"    recalled past the age cutoff:       {live()}")
    store.settings.case_dead_end_max_age_days = original
    print(f"    a person retracts it:               {store.case_forget(sc.case_key, path=p)}")
    print(f"    recalled after the retraction:      {live()}")
    kept = store.case_get(sc.case_key, p)["occurrences"]
    print(f"    occurrences kept:                   {kept}")


def main() -> None:
    probe_1_wrong_becomes_a_disproof()
    probe_2_who_may_disprove()
    probe_3_a_refusal_binds()
    probe_4_what_the_next_run_sees()
    probe_5_runbook_health()
    probe_6_forgetting()
    print()


if __name__ == "__main__":
    main()
