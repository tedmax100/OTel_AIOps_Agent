"""Ask the cluster what the last rollout changed, then watch the same action
get two different verdicts.

Four sections, none of which call an LLM:

  1. what `k8s_change_provenance` says about this cluster right now
  2. the same tool over the three shapes that matter, as fixtures
  3. what the applicability check rules out, and what it leaves alone
  4. the decision `k8s.rollout_undo` gets in each case

Section 1 talks to the live cluster, so have k3d up. The rest is fixtures, on
purpose: the whole point of this layer is that it can be recomputed without a
model and without a running incident.

Run from `aiops-agent/service/`:
    uv run python ../../otel-aiops-agent/ironman-2026/day35/probe_applicability.py
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

from app.actions import registry
from app.governance import Autonomy, decide, inapplicable_by_provenance
from app.tools.k8s import get_change_provenance

RULE = "=" * 74
CALIB = {"labeled": 0, "overconfidence": None}

# The three shapes an alert cannot tell apart. Only the third one is a deploy.
SHAPES: dict[str, dict] = {
    "a ConfigMap flip, plus a restart": {
        "service": "payment-service",
        "found": True,
        "revisions": [
            {
                "revision": 71,
                "git_version": "v2.5.0",
                "image": "payment:dev",
                "mounted_config": ["configMap/payment-flags"],
                "changed_vs_previous": [],
            }
        ],
        "verdict": "the last rollout changed nothing the process runs (at most a version label "
        "or a restart). If behaviour changed, the cause is outside the template — check the "
        "mounted config: configMap/payment-flags",
    },
    "only the version label moved": {
        "service": "payment-service",
        "found": True,
        "revisions": [
            {
                "revision": 71,
                "git_version": "v2.5.0",
                "image": "payment:dev",
                "mounted_config": ["configMap/payment-flags"],
                "changed_vs_previous": ["git_version(label only)"],
            }
        ],
        "verdict": "the last rollout changed nothing the process runs (at most a version label "
        "or a restart). If behaviour changed, the cause is outside the template — check the "
        "mounted config: configMap/payment-flags",
    },
    "a real deploy: the image changed": {
        "service": "payment-service",
        "found": True,
        "revisions": [
            {
                "revision": 71,
                "git_version": "v2.5.0",
                "image": "payment:v2.5.0",
                "mounted_config": ["configMap/payment-flags"],
                "changed_vs_previous": ["image"],
            }
        ],
        "verdict": "the last rollout changed image — a rollback restores a genuinely different "
        "pod template",
    },
    "the cluster cannot answer": {"unavailable": True, "detail": "kubernetes not reachable"},
}


async def section_one() -> None:
    print(RULE)
    print("1. what this cluster says right now")
    print(RULE)
    out = await get_change_provenance("payment-service")
    if out.get("unavailable"):
        print("\n  k8s not reachable:", out["detail"])
        print("  (sections 2-4 are fixtures and still run)")
        return
    for row in out.get("revisions", []):
        changed = row["changed_vs_previous"]
        print(
            f"\n  rev {row['revision']:<4} {row['git_version']!s:<10} {row['image']:<28}"
            f" changed={'(first)' if changed is None else changed}"
        )
    print(f"\n  verdict: {out.get('verdict')}")


async def section_two() -> None:
    print("\n" + RULE)
    print("2. the three shapes an alert cannot tell apart")
    print(RULE)
    for label, payload in SHAPES.items():
        if payload.get("unavailable"):
            continue
        rev = payload["revisions"][-1]
        print(f"\n{label}")
        print(f"  image={rev['image']}  changed_vs_previous={rev['changed_vs_previous']}")
        print(f"  -> {payload['verdict'][:96]}...")


async def section_three() -> None:
    print("\n" + RULE)
    print("3. what the check rules out")
    print(RULE)
    for label, payload in SHAPES.items():
        with patch("app.tools.k8s.get_change_provenance", AsyncMock(return_value=payload)):
            out = await inapplicable_by_provenance("payment-service")
        ruled = ", ".join(out) if out else "nothing"
        print(f"\n{label:<38} rules out: {ruled}")
        if out:
            print(f"  reason: {json.dumps(out, ensure_ascii=False)[:150]}...")
    print("\nThe unreachable case rules out nothing on purpose: failing closed would strip")
    print("every proposal the moment k8s goes quiet, which is when the on-call needs them.")


async def section_four() -> None:
    """Confidence is about the diagnosis; applicability is about the fix. Two
    different questions, and only one of them is the model's to answer."""
    print("\n" + RULE)
    print("4. the verdict k8s.rollout_undo gets, at the same confidence")
    print(RULE)
    spec = registry.get("k8s.rollout_undo")
    print(f"\n{'shape':<38} {'conf':>5}  verdict")
    for label, payload in SHAPES.items():
        with patch("app.tools.k8s.get_change_provenance", AsyncMock(return_value=payload)):
            blocked = await inapplicable_by_provenance("payment-service")
        d = decide(spec, 0.95, CALIB, inapplicable=blocked.get("k8s.rollout_undo"))
        mark = "ESCALATE (not proposed)" if d.autonomy is Autonomy.ESCALATE else d.autonomy.value
        print(f"{label:<38} {0.95:>5}  {mark}")


async def main() -> None:
    await section_one()
    await section_two()
    await section_three()
    await section_four()


if __name__ == "__main__":
    asyncio.run(main())
