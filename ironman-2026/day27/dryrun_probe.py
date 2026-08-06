"""What a proposed action would touch, computed without touching anything.

Part 1 runs every dry-run against the live cluster and prints the footprint plus
the policy verdict. Part 2 proves the claim in the module docstring of
`blast_radius.py` — that it never mutates — by reading the Deployment's
generation and resourceVersion before and after.

No LLM, no tokens; the whole point is that this half of "next step" is
arithmetic on cluster state, not a judgement call.

Run from `aiops-agent/service/` with kubeconfig pointing at the demo cluster:
    uv run python ../../otel-aiops-agent/ironman-2026/day27/dryrun_probe.py
"""

from __future__ import annotations

import asyncio

from app.blast_radius import (
    dry_run_rollout_undo,
    dry_run_scale,
    evaluate_policy,
    format_blast_radius,
)
from app.config import settings

NS = settings.k8s_namespace or "demo"

CASES: list[tuple[str, str, dict]] = [
    ("roll back the suspect deploy", "undo", {"namespace": NS, "deployment": "payment-service"}),
    ("roll back a single-replica service", "undo", {"namespace": NS, "deployment": "user-service"}),
    (
        "roll back something that isn't there",
        "undo",
        {"namespace": NS, "deployment": "typo-service"},
    ),
    ("roll back in kube-system", "undo", {"namespace": "kube-system", "deployment": "coredns"}),
    ("scale 2 -> 4", "scale", {"namespace": NS, "deployment": "payment-service", "replicas": 4}),
    ("scale 2 -> 60", "scale", {"namespace": NS, "deployment": "payment-service", "replicas": 60}),
    ("scale to zero", "scale", {"namespace": NS, "deployment": "payment-service", "replicas": 0}),
    ("scale without a replica count", "scale", {"namespace": NS, "deployment": "payment-service"}),
]


async def _deployment_state(name: str) -> tuple[int | None, str | None, str | None]:
    from app.tools import k8s

    _, apps = await asyncio.to_thread(k8s._load_client)
    dep = await asyncio.to_thread(apps.read_namespaced_deployment, name=name, namespace=NS)
    return dep.spec.replicas, str(dep.metadata.generation), dep.metadata.resource_version


async def footprints() -> None:
    print(f"{'=' * 78}\n1. what each proposal would touch\n{'=' * 78}")
    for label, kind, args in CASES:
        br = await (dry_run_rollout_undo(args) if kind == "undo" else dry_run_scale(args))
        ok, reason = evaluate_policy(br)
        print(f"\n{label}")
        print(f"  footprint: {format_blast_radius(br)}")
        print(f"  policy   : {'ALLOW' if ok else 'REFUSE'} — {reason}")


async def read_only() -> None:
    print(f"\n{'=' * 78}\n2. is it really read-only\n{'=' * 78}")
    before = await _deployment_state("payment-service")
    for _ in range(3):
        await dry_run_rollout_undo({"namespace": NS, "deployment": "payment-service"})
        await dry_run_scale({"namespace": NS, "deployment": "payment-service", "replicas": 60})
    after = await _deployment_state("payment-service")
    print(f"  before: replicas={before[0]} generation={before[1]} resourceVersion={before[2]}")
    print(f"  after : replicas={after[0]} generation={after[1]} resourceVersion={after[2]}")
    print(f"  6 dry-runs later, the object is {'unchanged' if before == after else 'DIFFERENT'}")


async def main() -> None:
    await footprints()
    await read_only()


if __name__ == "__main__":
    asyncio.run(main())
