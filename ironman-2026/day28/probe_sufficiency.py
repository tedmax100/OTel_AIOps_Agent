"""Stop the investigation on the evidence, not on what the model says about it.

The old stopping rule read one number the model wrote about its own work. This
probe puts that number and the four deterministic checks side by side on the
same runs, so the disagreements are visible rather than argued about:

  1. four investigations, each judged check by check
  2. the instruction a run gets when it is not done yet
  3. where the old rule and the new one disagree, in both directions
  4. what moving the thresholds to three would cost

Nothing here calls an LLM or touches the stack: every fact below is hand-built,
which is the point — the whole rule is recomputable from a stored run.

Run from `aiops-agent/service/`:
    uv run python ../../otel-aiops-agent/ironman-2026/day28/probe_sufficiency.py
"""

from __future__ import annotations

from app.facts import DiagnosticFact
from app.sufficiency import evaluate_sufficiency, pivot_instruction

RULE = "=" * 72


def fact(
    n: int, tool: str, domain: str, role: str, digest: str, *, usable: bool = True
) -> DiagnosticFact:
    return DiagnosticFact(
        fact_id=f"f{n:02d}",
        tool=tool,
        source_domain=domain,
        role_hint=role,
        disposition="observed" if usable else "empty",
        usable=usable,
        digest=digest,
    )


# Four run shapes, hand-built so each one isolates a single check. The stated
# confidences are illustrative, not measurements: the point of the table in
# section 3 is which decision each rule makes, not what any one run scored.
RUNS: list[tuple[str, float, list[DiagnosticFact], list[str]]] = [
    (
        "one store, one role, sounds certain",
        0.90,
        [
            fact(1, "query_prometheus", "runtime", "mechanism", "error rate 0.42"),
            fact(2, "query_prometheus", "runtime", "mechanism", "p95 1.2s"),
        ],
        ["prometheus: error rate 0.42"],
    ),
    (
        "three stores, two roles, sounds unsure",
        0.55,
        [
            fact(1, "query_prometheus", "runtime", "mechanism", "error rate 0.42"),
            fact(2, "query_loki_logs", "log", "impact", "312 decline events"),
            fact(3, "query_tempo_traces", "trace", "mechanism", "8 traces, validator span"),
            fact(4, "k8s_rollout_history", "change", "trigger", "v2.5.0 rolled out 14:02"),
        ],
        ["loki: 312 decline events", "rollout: v2.5.0 at 14:02"],
    ),
    (
        "everything came back empty",
        0.65,
        [
            fact(1, "query_prometheus", "runtime", "mechanism", "no data", usable=False),
            fact(2, "query_loki_logs", "log", "impact", "no data", usable=False),
            fact(3, "discover_metrics_tool", "catalog", "context", "6 metrics listed"),
        ],
        ["the payment service is failing validation"],
    ),
    (
        "solid evidence, conclusion cites none of it",
        0.80,
        [
            fact(1, "query_prometheus", "runtime", "mechanism", "error rate 0.42"),
            fact(2, "query_loki_logs", "log", "impact", "312 decline events"),
            fact(3, "k8s_rollout_history", "change", "trigger", "v2.5.0 rolled out 14:02"),
        ],
        [],
    ),
]


def section_one() -> None:
    print(RULE)
    print("1. four runs, judged check by check")
    print(RULE)
    for label, conf, facts, cited in RUNS:
        v = evaluate_sufficiency(facts, cited)
        print(f"\n{label}  (stated confidence {conf:.2f})")
        print(f"  verdict : sufficient={v.sufficient}")
        for c in v.checks:
            print(f"    {'ok' if c.passed else 'XX'} {c.name:<26} {c.detail}")


def section_two() -> None:
    print("\n" + RULE)
    print("2. what a run that is not done yet is told to do")
    print(RULE)
    label, _, facts, cited = RUNS[0]
    v = evaluate_sufficiency(facts, cited)
    print(f"\n({label})\n")
    print(pivot_instruction(v, facts))


def section_three() -> None:
    """Both directions matter. A gate that only ever tightens is easy to sell
    and easy to distrust; this one also lets a run stop that the old rule would
    have sent back around for another guess."""
    print("\n" + RULE)
    print("3. where the two rules disagree")
    print(RULE)
    threshold = 0.7
    print(f"\n{'run':<44} {'conf':>5}  {'old':<9} {'new':<9} ")
    for label, conf, facts, cited in RUNS:
        old = "stop" if conf >= threshold else "pivot"
        new = "stop" if evaluate_sufficiency(facts, cited).sufficient else "pivot"
        flag = "  <-- disagree" if old != new else ""
        print(f"{label:<44} {conf:>5.2f}  {old:<9} {new:<9}{flag}")
    print(f"\n(old rule: keep going while confidence < {threshold})")


def section_four() -> None:
    """Three-of-three is the version I wanted and did not ship. The case that
    talked me out of it is the ordinary one: an incident older than the trace
    store's retention, on a day nobody deployed. Two stores and two roles is all
    such a run can ever reach, however well it is conducted."""
    print("\n" + RULE)
    print("4. what three would cost")
    print(RULE)
    retention_closed = [
        fact(1, "query_prometheus", "runtime", "mechanism", "error rate 0.42"),
        fact(2, "query_loki_logs", "log", "impact", "312 decline events"),
        fact(3, "query_tempo_traces", "trace", "mechanism", "no data", usable=False),
    ]
    cases = [(label, facts, cited) for label, _, facts, cited in RUNS]
    cases.insert(2, ("incident older than trace retention", retention_closed, ["loki: 312"]))

    print(f"\n{'run':<44} {'2 of each':<12} {'3 of each':<12}")
    for label, facts, cited in cases:
        two = evaluate_sufficiency(facts, cited).sufficient
        three = evaluate_sufficiency(facts, cited, min_sources=3, min_roles=3).sufficient
        print(f"{label:<44} {two!s:<12} {three!s:<12}")
    print(
        "\nThe inserted run is what most incidents look like once they are an hour old:"
        "\nmetrics and logs agree, the traces are gone, nothing was deployed. Under"
        "\nthree-of-three it can never stop, and the reason is the stack's retention"
        "\nrather than anything about the investigation."
    )


if __name__ == "__main__":
    section_one()
    section_two()
    section_three()
    section_four()
