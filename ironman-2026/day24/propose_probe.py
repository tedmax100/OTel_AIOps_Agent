"""Run one real RCA and look at what the on-call is actually offered afterwards.

Two alerts, identical except for the alertname: one spelled the way the runbook
declares its trigger, one spelled the way an alert rule in Grafana would
normally name it. Everything downstream of the runbook match — auto-run
diagnostics, remediation proposals, the action request the plugin renders — is
downstream of that one string comparison.

For each run it prints the matched runbook, the governance decisions, and every
ActionRequest that was created, including whether it carries a footprint.

Costs real tokens. Run from `aiops-agent/service/`:
    uv run python ../../otel-aiops-agent/ironman-2026/day24/propose_probe.py
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app import action_requests
from app.agent import run_headless
from app.runbook import match_runbook

ALERTS = {
    "as the alert rule names it": "PaymentDeclineRateHigh",
    "as the runbook declares it": "payment-decline-rate-high",
}


def _alert(alertname: str) -> dict:
    return {
        "labels": {
            "alertname": alertname,
            "service_name": "payment-service",
            "severity": "critical",
        },
        "annotations": {"summary": "payment-service declined rate above objective"},
        "startsAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


async def one(label: str, alertname: str) -> None:
    print(f"\n{'=' * 78}\n{label}: alertname={alertname!r}\n{'=' * 78}")
    alert = _alert(alertname)
    rb = match_runbook(alert["labels"], alert["annotations"])
    print(f"runbook matched: {rb.id if rb else None}")

    before = {r["request_id"] for r in action_requests.list_requests(limit=200)}
    result = await run_headless(alert, thread_id=f"day24-{alertname}-{alert['startsAt']}")

    findings = result["findings"]
    print(f"confidence     : {getattr(findings, 'confidence', 0.0):.2f}")
    decisions = result.get("decisions") or []
    print(f"decisions      : {len(decisions)}")
    for d in decisions:
        print(f"  - {d.action} → {d.autonomy.value} ({d.reason})")

    new = [r for r in action_requests.list_requests(limit=200) if r["request_id"] not in before]
    print(f"action requests: {len(new)}")
    for r in new:
        print(f"  - {r['action']} status={r['status']} args={r['args']}")
        print(f"    footprint at proposal time: {r.get('blast_radius')}")


async def main() -> None:
    for label, alertname in ALERTS.items():
        await one(label, alertname)


if __name__ == "__main__":
    asyncio.run(main())
