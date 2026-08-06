"""Read back what the agent produced, over its own HTTP API.

Split out of `e2e.sh` because quoting a JSON-parsing one-liner inside a bash
function inside a shell string is how you end up debugging backslashes instead
of the system you meant to test.

    python3 report.py investigation http://localhost:8091
    python3 report.py proposal      http://localhost:8091
"""

from __future__ import annotations

import json
import sys
import urllib.request


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=20) as resp:
        return json.load(resp)


def investigation(base: str) -> int:
    rows = _get(f"{base}/investigations?limit=1").get("investigations") or []
    if not rows:
        print("no investigation recorded")
        return 1
    r = rows[0]
    print(f"conclusion : {(r.get('summary') or '')[:110]}")
    print(f"confidence : {r.get('confidence')}")
    print(f"trace_id   : {r.get('trace_id')}")
    for d in r.get("decisions") or []:
        print(f"next step  : {d['action']} -> {d['autonomy']}")
    return 0 if r.get("summary") else 1


def proposal(base: str) -> int:
    rows = _get(f"{base}/actions/requests?limit=1").get("requests") or []
    if not rows:
        print("no proposal")
        return 1
    r = rows[0]
    br = r.get("blast_radius") or {}
    print(f"action    : {r['action']} ({r['status']})")
    if not br:
        print("footprint : none stored")
        return 1
    print(
        f"footprint : {br.get('affected_pods')} pod(s), "
        f"revision {br.get('current_revision')}->{br.get('target_revision')}, "
        f"policy_ok={br.get('policy_ok')}"
    )
    print(f"policy    : {br.get('policy_reason')}")
    return 0


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "investigation"
    url = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8091"
    raise SystemExit({"investigation": investigation, "proposal": proposal}[what](url))
