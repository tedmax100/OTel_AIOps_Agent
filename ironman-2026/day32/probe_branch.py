"""Let the diagnosis pick the fix, instead of striking the wrong one off afterwards.

Yesterday's applicability check worked backwards: the runbook offered
`k8s.rollout_undo` for every decline-rate page, and the provenance check removed
it again when the cluster said nothing had actually shipped. The action was
still on the list; it just got vetoed. Today the runbook has two branches and
the Tier 1 diagnostics choose between them, so the wrong fix is never proposed
in the first place.

Four sections, none of which call an LLM:

  1. what the shipped payment runbook looks like now (its branch points)
  2. the same runbook, branched against the three shapes of the same alert
  3. what the on-call is shown — including the branch that was *not* taken
  4. fail-open: no diagnostics, an unknown id, a diagnostic that errored

Section 1 reads the runbook file; the rest is fixtures, on purpose — this layer
has to be recomputable without a model and without a live incident.

Run from `aiops-agent/service/`:
    uv run python ../../otel-aiops-agent/ironman-2026/day32/probe_branch.py
"""

from __future__ import annotations

import asyncio

from app.actions import registry
from app.runbook import (
    DiagnosticResult,
    Runbook,
    format_remediation_choices,
    load_runbooks,
    select_remediation,
)

RULE = "=" * 78

# The two verdicts `k8s_change_provenance` actually emits, verbatim.
TEMPLATE_CHANGED = (
    "the last rollout changed image — a rollback restores a genuinely different pod template"
)
CONFIG_CHANGED = (
    "the last rollout changed nothing the process runs (at most a version label or a restart). "
    "If behaviour changed, the cause is outside the template — check the mounted config: "
    "configMap/payment-flags"
)

SHAPES = {
    "a real deploy: the image changed": TEMPLATE_CHANGED,
    "a ConfigMap flip, plus a restart": CONFIG_CHANGED,
}


def _rb() -> Runbook:
    return next(b for b in load_runbooks("runbooks") if b.id == "payment-bad-deploy")


def _prov(text: str, status: str = "ran") -> DiagnosticResult:
    return DiagnosticResult(
        id="provenance",
        desc="what the last rollouts actually changed",
        action="k8s_change_provenance",
        status=status,
        output_preview=text[:500],
        output_text=text,
    )


def section_one() -> None:
    print(RULE)
    print("1. the shipped runbook: where it branches")
    print(RULE)
    rb = _rb()
    print(f"\n  {rb.id} — {rb.title}\n")
    for s in rb.diagnostics:
        tag = f"id={s.id}" if s.id else "(no id — not a branch point)"
        check = "check" if s.check else "no check"
        print(f"  diag  {tag:<32} {s.action:<24} {check}")
    print()
    for s in rb.remediation:
        cond = "unconditional" if s.when is None else f"when {s.when.diagnostic} says …"
        registered = "registered" if registry.get(s.action) else "human-only (not registered)"
        print(f"  fix   {s.action:<42} {cond:<26} {registered}")
    print("\n  The branch diagnostic carries no `check` on purpose: execution.py aborts an")
    print("  approved action when any diagnostic check fails, and this step exists to sort")
    print("  incidents, not to assert a precondition.")


def section_two() -> None:
    print("\n" + RULE)
    print("2. same alert, same git_version label, two different fixes")
    print(RULE)
    rb = _rb()
    for label, verdict in SHAPES.items():
        chosen = [c for c in select_remediation(rb, [_prov(verdict)], {}) if c.applicable]
        print(f"\n{label}")
        for c in chosen:
            print(f"  -> {c.step.action}")


def section_three() -> None:
    print("\n" + RULE)
    print("3. what the on-call reads (the branch not taken stays visible)")
    print(RULE)
    rb = _rb()
    print()
    print(format_remediation_choices(select_remediation(rb, [_prov(CONFIG_CHANGED)], {})))
    print("\n  'We didn't roll back because the last rollouts changed nothing' is a fact about")
    print("  the incident. A silently shortened list is not.")


def section_four() -> None:
    print("\n" + RULE)
    print("4. fail-open: a step is dropped only when a condition is decidedly false")
    print(RULE)
    rb = _rb()
    unknown = _prov(TEMPLATE_CHANGED)
    unknown.id = "typo-in-the-runbook"
    cases = {
        "diagnostics never ran": None,
        "the condition names an id that does not exist": [unknown],
        "the provenance query errored": [_prov("", status="error")],
    }
    print(f"\n{'case':<48} offered")
    for label, results in cases.items():
        offered = [c.step.action for c in select_remediation(rb, results, {}) if c.applicable]
        print(f"{label:<48} {len(offered)} (both branches)")
    print("\n  The cost of a wrong drop is that the on-call is never shown the fix. The cost of")
    print("  a wrong keep is one more line the governance gate still has to clear.")


async def main() -> None:
    section_one()
    section_two()
    section_three()
    section_four()


if __name__ == "__main__":
    asyncio.run(main())
